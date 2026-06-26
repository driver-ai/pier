"""Tests for the run-sweep orchestrator and capture-index layer.

These tests exercise :func:`classify_trial_status`, :func:`run_sweep`, and the
capture-index entry schema WITHOUT Docker. ``run_sweep`` accepts an injected
``run_trial`` callable so each test feeds synthesized :class:`TrialResult`
objects and lays artifact files on disk by hand; no container is ever started.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pier.models.agent.name import AgentName
from pier.models.task.id import LocalTaskId
from pier.models.trial.config import (
    AgentConfig,
    TaskConfig,
    TrialConfig,
    VerifierConfig,
)
from pier.models.trial.result import (
    AgentInfo,
    ExceptionInfo,
    ModelInfo,
    TimingInfo,
    TrialResult,
)
from pier.trial.sweep import (
    SweepCell,
    cell_id,
    classify_trial_status,
    run_sweep,
)


def _trial_config(trials_dir: Path) -> TrialConfig:
    return TrialConfig(
        task=TaskConfig(path=trials_dir / "task"),
        trials_dir=trials_dir,
        agent=AgentConfig(
            name=AgentName.CLAUDE_CODE.value, model_name="anthropic/claude-sonnet-4-5"
        ),
        verifier=VerifierConfig(disable=True),
    )


def _agent_info(model_info: ModelInfo | None) -> AgentInfo:
    return AgentInfo(name="claude-code", version="1.0", model_info=model_info)


def _trial_result(
    config: TrialConfig,
    *,
    exception_type: str | None = None,
    model_info: ModelInfo | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> TrialResult:
    exc_info = None
    if exception_type is not None:
        exc_info = ExceptionInfo(
            exception_type=exception_type,
            exception_message="boom",
            exception_traceback="trace",
            occurred_at=datetime.now(timezone.utc),
        )
    timing = None
    if started_at is not None or finished_at is not None:
        timing = TimingInfo(started_at=started_at, finished_at=finished_at)
    return TrialResult(
        task_name="task",
        trial_name="trial-name",
        trial_uri="file:///tmp/trial",
        task_id=LocalTaskId(path=str(config.task.path)),
        task_checksum="checksum",
        config=config,
        agent_info=_agent_info(model_info),
        exception_info=exc_info,
        agent_execution=timing,
    )


def _write_artifacts(
    trial_dir: Path,
    *,
    trajectory: bool = False,
    strace: str | None = None,
    model_patch: str | None = None,
    result: bool = False,
) -> None:
    agent_dir = trial_dir / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    if trajectory:
        (agent_dir / "trajectory.json").write_text("{}")
    if strace is not None:
        (agent_dir / "strace.log").write_text(strace)
    if model_patch is not None:
        (agent_dir / "model.patch").write_text(model_patch)
    if result:
        (trial_dir / "result.json").write_text("{}")


# --- classify_trial_status -------------------------------------------------


def test_classify_trial_status_timeout_with_artifacts_is_completed_with_failure_class(
    tmp_path,
):
    config = _trial_config(tmp_path)
    result = _trial_result(config, exception_type="AgentTimeoutError")

    status, failure_class = classify_trial_status(
        result, has_trajectory=True, has_strace=True
    )

    assert status == "completed"
    assert failure_class == "agent_timeout"


def test_classify_trial_status_env_and_agent_setup_failures_are_non_completed(tmp_path):
    config = _trial_config(tmp_path)

    env_result = _trial_result(config, exception_type="EnvironmentStartTimeoutError")
    env_status, env_class = classify_trial_status(
        env_result, has_trajectory=False, has_strace=False
    )
    assert env_status == "env_error"
    assert env_class == "EnvironmentStartTimeoutError"

    setup_result = _trial_result(config, exception_type="AgentSetupTimeoutError")
    setup_status, setup_class = classify_trial_status(
        setup_result, has_trajectory=False, has_strace=False
    )
    assert setup_status == "agent_error"
    assert setup_class == "AgentSetupTimeoutError"


def test_classify_trial_status_strace_missing_image_is_env_error(tmp_path):
    config = _trial_config(tmp_path)
    # The agent-env strace preflight raises a plain RuntimeError when the
    # strace-enabled image is unavailable.
    result = _trial_result(config, exception_type="RuntimeError")

    status, _ = classify_trial_status(result, has_trajectory=False, has_strace=False)

    assert status == "env_error"


def test_classify_trial_status_none_model_info_is_guarded(tmp_path):
    config = _trial_config(tmp_path)
    result = _trial_result(config, exception_type=None, model_info=None)

    status, failure_class = classify_trial_status(
        result, has_trajectory=True, has_strace=True
    )

    assert status == "completed"
    assert failure_class is None


# --- run_sweep -------------------------------------------------------------


def _cell(
    config: TrialConfig,
    cid: str,
    *,
    replicate_index: int = 0,
    task_commit: str = "unknown",
    repo_root: str = "unknown",
) -> SweepCell:
    return SweepCell(
        cell_id=cid,
        task="task",
        model="anthropic/claude-sonnet-4-5",
        replicate_index=replicate_index,
        config=config,
        task_commit=task_commit,
        repo_root=repo_root,
    )


def test_run_sweep_writes_pending_then_terminal_and_isolates_failure(tmp_path):
    index_path = tmp_path / "capture_index.json"

    cfg_ok = _trial_config(tmp_path / "ok")
    cfg_boom = _trial_config(tmp_path / "boom")
    cfg_after = _trial_config(tmp_path / "after")

    cell_ok = _cell(cfg_ok, "explore/task/m/0/arm64")
    cell_boom = _cell(cfg_boom, "explore/task/m/1/arm64", replicate_index=1)
    cell_after = _cell(cfg_after, "explore/task/m/2/arm64", replicate_index=2)

    observed_pending: dict[str, str] = {}

    async def fake_run_trial(config: TrialConfig) -> TrialResult:
        # The pending entry for this cell must be persisted BEFORE its runner
        # is invoked.
        on_disk = json.loads(index_path.read_text())
        for entry in on_disk:
            observed_pending.setdefault(entry["cell_id"], entry["trial_status"])

        if config is cfg_boom:
            raise RuntimeError("runner blew up")

        trial_dir = config.trials_dir / "trial-name"
        _write_artifacts(
            trial_dir,
            trajectory=True,
            strace="openat(...)",
            model_patch="diff --git a b",
            result=True,
        )
        now = datetime.now(timezone.utc)
        return _trial_result(
            config,
            model_info=ModelInfo(name="claude-sonnet-4-5", provider="anthropic"),
            started_at=now,
            finished_at=now + timedelta(seconds=5),
        )

    entries = asyncio.run(
        run_sweep(
            [cell_ok, cell_boom, cell_after],
            index_path,
            run_trial=fake_run_trial,
        )
    )

    # All three cells were seen as pending before their runner ran.
    assert observed_pending.get(cell_ok.cell_id) == "pending"
    assert observed_pending.get(cell_boom.cell_id) == "pending"
    assert observed_pending.get(cell_after.cell_id) == "pending"

    by_id = {e["cell_id"]: e for e in entries}
    assert by_id[cell_ok.cell_id]["trial_status"] == "completed"
    # A runner exception becomes a classified terminal entry, not a crash.
    assert by_id[cell_boom.cell_id]["trial_status"] in {"other", "env_error"}
    assert by_id[cell_boom.cell_id]["trial_status"] != "pending"
    # The third cell still ran despite the second cell failing.
    assert by_id[cell_after.cell_id]["trial_status"] == "completed"

    # Final on-disk index matches the returned terminal entries.
    on_disk = {e["cell_id"]: e for e in json.loads(index_path.read_text())}
    assert on_disk[cell_ok.cell_id]["trial_status"] == "completed"
    assert on_disk[cell_after.cell_id]["trial_status"] == "completed"


def test_run_sweep_resumes_by_cell_id(tmp_path):
    index_path = tmp_path / "capture_index.json"

    cfg_done = _trial_config(tmp_path / "done")
    cfg_new = _trial_config(tmp_path / "new")
    cell_done = _cell(cfg_done, "explore/task/m/0/arm64")
    cell_new = _cell(cfg_new, "explore/task/m/1/arm64", replicate_index=1)

    # Pre-existing index: cell_done already completed in a prior run.
    index_path.write_text(
        json.dumps(
            [
                {
                    "cell_id": cell_done.cell_id,
                    "task": "task",
                    "task_commit": "deadbeef",
                    "repo_root": "/repo",
                    "condition": "explore",
                    "arch": "arm64",
                    "harness": "claude-code",
                    "model_provider": "anthropic",
                    "model_name": "claude-sonnet-4-5",
                    "sampling_config": "api_default",
                    "replicate_index": 0,
                    "trial_status": "completed",
                    "has_trajectory": True,
                    "has_strace": True,
                    "has_result": True,
                    "timed_out": False,
                    "started_at": "2026-06-26T00:00:00+00:00",
                }
            ]
        )
    )

    ran: list[str] = []

    async def fake_run_trial(config: TrialConfig) -> TrialResult:
        ran.append(str(config.trials_dir))
        trial_dir = config.trials_dir / "trial-name"
        _write_artifacts(trial_dir, trajectory=True, strace="openat(...)", result=True)
        return _trial_result(
            config,
            model_info=ModelInfo(name="claude-sonnet-4-5", provider="anthropic"),
        )

    entries = asyncio.run(
        run_sweep(
            [cell_done, cell_new],
            index_path,
            run_trial=fake_run_trial,
            skip_completed=True,
        )
    )

    # The completed cell was skipped (its runner never ran).
    assert str(cfg_done.trials_dir) not in ran
    assert str(cfg_new.trials_dir) in ran

    by_id = {e["cell_id"]: e for e in entries}
    # The pre-existing completed entry is preserved (merge, not clobber).
    assert by_id[cell_done.cell_id]["trial_status"] == "completed"
    assert by_id[cell_new.cell_id]["trial_status"] == "completed"

    on_disk = {e["cell_id"]: e for e in json.loads(index_path.read_text())}
    assert on_disk[cell_done.cell_id]["trial_status"] == "completed"
    assert on_disk[cell_new.cell_id]["trial_status"] == "completed"


def test_capture_index_entry_has_full_schema_with_sourceable_fields(tmp_path):
    index_path = tmp_path / "capture_index.json"
    cfg = _trial_config(tmp_path / "cell")
    cell = _cell(
        cfg, "explore/task/m/0/arm64", task_commit="abc123", repo_root="/repo"
    )

    async def fake_run_trial(config: TrialConfig) -> TrialResult:
        trial_dir = config.trials_dir / "trial-name"
        _write_artifacts(
            trial_dir,
            trajectory=True,
            strace="openat(...)",
            model_patch="diff --git a b",
            result=True,
        )
        now = datetime.now(timezone.utc)
        return _trial_result(
            config,
            model_info=ModelInfo(name="claude-sonnet-4-5", provider="anthropic"),
            started_at=now,
            finished_at=now + timedelta(seconds=3),
        )

    entries = asyncio.run(
        run_sweep([cell], index_path, run_trial=fake_run_trial)
    )

    entry = entries[0]
    assert entry["cell_id"] == cell.cell_id
    # Join keys.
    assert entry["task"] == "task"
    assert entry["condition"] == "explore"
    assert entry["arch"] == "arm64"
    assert entry["replicate_index"] == 0
    # Manifest-sourced metadata.
    assert entry["task_commit"] == "abc123"
    assert entry["repo_root"] == "/repo"
    # AgentInfo-sourced metadata.
    assert entry["model_provider"] == "anthropic"
    assert entry["model_name"] == "claude-sonnet-4-5"
    # Constant harness/sampling fields.
    assert entry["harness"] == "claude-code"
    assert entry["sampling_config"] == "api_default"
    # Artifact booleans.
    assert entry["has_trajectory"] is True
    assert entry["has_strace"] is True
    assert entry["has_result"] is True
    assert entry["model_patch_state"] == "present_nonempty"
    assert entry["timed_out"] is False
    # Wall time derived from agent_execution timing.
    assert entry["wall_seconds"] >= 0


# --- model_patch_state -----------------------------------------------------


def test_model_patch_state_present_empty_absent(tmp_path):
    index_path = tmp_path / "capture_index.json"

    cfg_nonempty = _trial_config(tmp_path / "nonempty")
    cfg_empty = _trial_config(tmp_path / "empty")
    cfg_absent = _trial_config(tmp_path / "absent")

    cell_nonempty = _cell(cfg_nonempty, "explore/task/m/0/arm64")
    cell_empty = _cell(cfg_empty, "explore/task/m/1/arm64", replicate_index=1)
    cell_absent = _cell(cfg_absent, "explore/task/m/2/arm64", replicate_index=2)

    async def fake_run_trial(config: TrialConfig) -> TrialResult:
        trial_dir = config.trials_dir / "trial-name"
        if config is cfg_nonempty:
            _write_artifacts(
                trial_dir,
                trajectory=True,
                strace="openat(...)",
                model_patch="diff --git a b",
                result=True,
            )
        elif config is cfg_empty:
            _write_artifacts(
                trial_dir,
                trajectory=True,
                strace="openat(...)",
                model_patch="",
                result=True,
            )
        else:
            _write_artifacts(
                trial_dir, trajectory=True, strace="openat(...)", result=True
            )
        return _trial_result(
            config,
            model_info=ModelInfo(name="claude-sonnet-4-5", provider="anthropic"),
        )

    entries = asyncio.run(
        run_sweep(
            [cell_nonempty, cell_empty, cell_absent],
            index_path,
            run_trial=fake_run_trial,
        )
    )

    by_id = {e["cell_id"]: e for e in entries}
    assert by_id[cell_nonempty.cell_id]["model_patch_state"] == "present_nonempty"
    assert by_id[cell_empty.cell_id]["model_patch_state"] == "present_empty_no_edits"
    assert by_id[cell_absent.cell_id]["model_patch_state"] == "absent"


def test_cell_id_helper_is_importable():
    # Sanity: the existing builder helper is still exported alongside the new API.
    assert cell_id("explore", "task", "m", 0, "arm64") == "explore/task/m/0/arm64"
