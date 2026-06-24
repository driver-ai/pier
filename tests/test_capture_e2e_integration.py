"""Gated end-to-end integration tests for controlled-run capture.

These tests prove that a REAL Pier trial, run on the Docker backend with
``PIER_CAPTURE_STRACE=1``, emits both per-trial capture artifacts at their
final host paths:

* ``trial_paths.agent_dir / "strace.log"`` — written by strace while the
  primary agent command runs (via ``build_capture_command``).
* ``trial_paths.agent_dir / "model.patch"`` — the staged ``git diff`` written
  by ``Trial._finalize_capture()`` after the agent run, before the first
  ``_maybe_download_logs()`` (C1), on both the success and the handled-failure
  paths (C2).

They are HEAVY and GATED. They build a Linux container, grant it
``SYS_PTRACE`` (capabilities compose override) and ``seccomp:unconfined``, and
drive a real installed agent that calls a model API. They are therefore
opt-in: an operator who intends to spend the build/model time exports
``PIER_RUN_CAPTURE_E2E=1`` (and supplies model credentials). They also require
a usable Docker daemon — the same preflight Pier's ``DockerEnvironment`` runs
(``shutil.which("docker")`` + a ``docker info`` probe).

On a host without that opt-in, or without a usable Docker daemon, these tests
SKIP cleanly (they never error and never run a container). macOS cannot ptrace
Linux syscalls on the host, but the Linux container provides ptrace, so the
host OS itself is not the gate — the gate is "operator opted in AND Docker
daemon usable".

The strace-writes-are-a-subset-of-the-diff containment assertion is Plan 04;
it is intentionally NOT made here.
"""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pier.agents.installed.base import NonZeroAgentExitCodeError
from pier.models.agent.name import AgentName
from pier.models.environment_type import EnvironmentType
from pier.models.trial.config import (
    AgentConfig,
    EnvironmentConfig,
    TaskConfig,
    TrialConfig,
)
from pier.models.trial.paths import TrialPaths
from pier.trial.execution import AgentTimeoutError
from pier.trial.trial import Trial

# Repo-relative path to the in-repo fixture task driven by these e2e runs.
_HELLO_WORLD_TASK = (
    Path(__file__).resolve().parents[1] / "examples" / "tasks" / "hello-world"
)

# Syscalls strace is configured to trace (must match build_capture_command).
_TRACED_SYSCALLS = (
    "openat",
    "renameat2",
    "rename",
    "renameat",
    "unlink",
    "unlinkat",
)

# Process-lifecycle syscalls added for actor provenance (Plan 07): execve names
# each PID, clone/clone3 link the process tree.
_CLONE_SYSCALLS = ("clone(", "clone3(")

# Opt-in flag: an operator sets this when they intend to pay the build/model
# cost of a real capture run. The capture agent and its model are configurable
# so the operator can point the run at credentials they hold.
_OPT_IN_VAR = "PIER_RUN_CAPTURE_E2E"
_AGENT_NAME = os.environ.get("PIER_E2E_AGENT", AgentName.MINI_SWE_AGENT.value)
_MODEL_NAME = os.environ.get("PIER_E2E_MODEL", "anthropic/claude-sonnet-4-5")

# Actor-provenance e2e trigger (Plan 07 Task 8). Subagents are a claude-code-only
# concept, so this run needs the claude-code agent AND a task whose prompt
# reliably dispatches a subagent via the Task tool (e.g. "use the Task tool to
# launch an Explore subagent that lists the repo, then summarize"). The operator
# supplies that task's path via PIER_E2E_SUBAGENT_TASK; absent it, the test skips
# rather than driving the generic fixture (which would not dispatch a subagent).
_SUBAGENT_TASK_VAR = "PIER_E2E_SUBAGENT_TASK"


def _docker_daemon_usable() -> bool:
    """Mirror DockerEnvironment.preflight: docker on PATH + a live daemon."""
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    return True


def _skip_reason() -> str | None:
    if os.environ.get(_OPT_IN_VAR, "").strip().lower() not in {"1", "true", "yes"}:
        return (
            f"capture e2e is opt-in; set {_OPT_IN_VAR}=1 (and model credentials) "
            "to run the real container capture trial"
        )
    if not _docker_daemon_usable():
        return "Docker daemon not usable (docker not on PATH or `docker info` failed)"
    return None


# Module-level gate: evaluated once at collection time so the whole module
# SKIPS cleanly on a host that has not opted in or has no usable Docker daemon.
_SKIP_REASON = _skip_reason()
pytestmark = pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")


def _capture_trial_config(tmp_path, *, agent_timeout_multiplier: float | None = None):
    """Build a real TrialConfig that drives the hello-world fixture task.

    Uses the Docker backend and a capture-emitting installed agent. Capture is
    armed by the ``PIER_CAPTURE_STRACE=1`` env var the tests set before the run
    (read by the agent layer and the Docker environment alike).
    """
    return TrialConfig(
        task=TaskConfig(path=_HELLO_WORLD_TASK),
        trials_dir=tmp_path / "trials",
        agent=AgentConfig(name=_AGENT_NAME, model_name=_MODEL_NAME),
        environment=EnvironmentConfig(type=EnvironmentType.DOCKER),
        agent_timeout_multiplier=agent_timeout_multiplier,
    )


def _assert_capture_artifacts(trial_paths: TrialPaths) -> None:
    """Both artifacts exist at their FINAL host paths and are non-trivial."""
    strace_log = trial_paths.agent_dir / "strace.log"
    model_patch = trial_paths.agent_dir / "model.patch"

    assert strace_log.exists(), f"missing strace.log at {strace_log}"
    assert model_patch.exists(), f"missing model.patch at {model_patch}"

    strace_text = strace_log.read_text()
    assert strace_text.strip(), "strace.log is empty"
    assert any(syscall in strace_text for syscall in _TRACED_SYSCALLS), (
        "strace.log contains none of the traced syscalls "
        f"{_TRACED_SYSCALLS!r}; capture did not record file activity"
    )

    # model.patch must exist; a real edit yields a non-empty staged diff.
    assert model_patch.read_text().strip(), "model.patch is empty"


def test_controlled_run_emits_strace_and_model_patch(tmp_path, monkeypatch):
    """C1: a real controlled run emits both strace.log and model.patch.

    Runs the in-repo ``examples/tasks/hello-world`` fixture through a real
    Pier trial on Docker with capture enabled and asserts both artifacts land
    at ``trial_paths.agent_dir`` and are non-trivial.
    """
    monkeypatch.setenv("PIER_CAPTURE_STRACE", "1")

    config = _capture_trial_config(tmp_path)

    async def _run() -> Trial:
        trial = await Trial.create(config)
        await trial.run()
        return trial

    trial = asyncio.run(_run())

    _assert_capture_artifacts(TrialPaths(trial_dir=trial.trial_dir))


def test_capture_retained_on_agent_failure(tmp_path, monkeypatch):
    """C2: a handled agent failure STILL yields both capture artifacts.

    The handled-failure branch in ``Trial.run`` finalizes capture and downloads
    logs exactly like the success branch (both before the first
    ``_maybe_download_logs``). We induce it with a near-zero agent timeout so
    the agent starts under strace (begins writing) and is then interrupted with
    an ``AgentTimeoutError`` — a handled failure. Both artifacts must survive.
    """
    monkeypatch.setenv("PIER_CAPTURE_STRACE", "1")

    # Drive the agent into the handled-failure branch via a tiny timeout.
    config = _capture_trial_config(tmp_path, agent_timeout_multiplier=0.001)

    async def _run() -> Trial:
        trial = await Trial.create(config)
        await trial.run()
        return trial

    trial = asyncio.run(_run())
    result = trial.result

    # The run was handled (not crashed): a failure was recorded for the agent.
    assert result.exception_info is not None
    assert result.exception_info.exception_type in {
        AgentTimeoutError.__name__,
        NonZeroAgentExitCodeError.__name__,
    }

    _assert_capture_artifacts(TrialPaths(trial_dir=trial.trial_dir))


def _assert_actor_provenance_signals(trial_paths: TrialPaths) -> None:
    """Both actor-provenance signals are present in the real artifacts.

    1. ``strace.log`` carries process-lifecycle records: ``execve(`` (names
       each PID) and a ``clone(``/``clone3(`` line (links the process tree).
    2. ``trajectory.json`` has a non-empty ``subagent_trajectories`` array, each
       entry a valid embedded trajectory with a ``trajectory_id``.
    """
    strace_log = trial_paths.agent_dir / "strace.log"
    trajectory_json = trial_paths.agent_dir / "trajectory.json"

    assert strace_log.exists(), f"missing strace.log at {strace_log}"
    strace_text = strace_log.read_text()
    assert "execve(" in strace_text, "strace.log has no execve( lines (no PID naming)"
    assert any(sc in strace_text for sc in _CLONE_SYSCALLS), (
        f"strace.log has none of {_CLONE_SYSCALLS!r}; the process tree is not linkable"
    )

    assert trajectory_json.exists(), f"missing trajectory.json at {trajectory_json}"
    trajectory = json.loads(trajectory_json.read_text())
    subs = trajectory.get("subagent_trajectories")
    assert isinstance(subs, list) and subs, (
        "trajectory.json has no subagent_trajectories; the dispatch was not captured"
    )
    for sub in subs:
        assert sub.get("trajectory_id"), "embedded subagent missing trajectory_id"


def test_capture_records_actor_provenance(tmp_path, monkeypatch):
    """Plan 07 Task 8: a real capture carries both actor-provenance signals.

    Drives a claude-code run on a subagent-dispatching task (operator-supplied
    via ``PIER_E2E_SUBAGENT_TASK``) under capture and asserts ``strace.log`` has
    ``execve(``/``clone(`` lines and ``trajectory.json`` has a populated
    ``subagent_trajectories``. Skips (in addition to the module Docker/opt-in
    gate) unless the agent is claude-code and a dispatch task is supplied.
    """
    if _AGENT_NAME != AgentName.CLAUDE_CODE.value:
        pytest.skip(
            "actor-provenance e2e needs the claude-code agent "
            f"(set PIER_E2E_AGENT={AgentName.CLAUDE_CODE.value}); subagents are "
            "claude-code-only"
        )
    task_path = os.environ.get(_SUBAGENT_TASK_VAR, "").strip()
    if not task_path:
        pytest.skip(
            f"set {_SUBAGENT_TASK_VAR} to a task that dispatches a subagent via "
            "the Task tool to run the actor-provenance capture assertion"
        )

    monkeypatch.setenv("PIER_CAPTURE_STRACE", "1")

    config = TrialConfig(
        task=TaskConfig(path=Path(task_path)),
        trials_dir=tmp_path / "trials",
        agent=AgentConfig(name=_AGENT_NAME, model_name=_MODEL_NAME),
        environment=EnvironmentConfig(type=EnvironmentType.DOCKER),
    )

    async def _run() -> Trial:
        trial = await Trial.create(config)
        await trial.run()
        return trial

    trial = asyncio.run(_run())

    trial_paths = TrialPaths(trial_dir=trial.trial_dir)
    _assert_capture_artifacts(trial_paths)
    _assert_actor_provenance_signals(trial_paths)
