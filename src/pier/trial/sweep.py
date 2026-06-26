"""Pure builders for the Phase C explore-capture sweep.

This module turns a parsed manifest (one entry per benchmark task) into a flat
list of :class:`SweepCell` records, one per (task, model, replicate). Each cell
carries a fully-formed :class:`TrialConfig` with verification disabled
(capture-only runs).

Separation of concerns:
- :func:`load_manifest` is the ONLY function that touches the filesystem; it
  reads and parses the manifest JSON.
- :func:`build_sweep_configs` is pure: it consumes an already-parsed manifest
  and performs no Docker calls and no filesystem writes.

Capture (strace) is enabled at RUN time via the ``PIER_CAPTURE_STRACE``
environment variable, NOT via any config field. The builder does not set it.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import toml
from typing import (
    TYPE_CHECKING,
    Awaitable,
    Callable,
    Literal,
    NotRequired,
    Optional,
    TypedDict,
)

from pier.models.agent.name import AgentName
from pier.models.trial.config import (
    AgentConfig,
    TaskConfig,
    TrialConfig,
    VerifierConfig,
)

if TYPE_CHECKING:
    from pier.models.trial.result import TrialResult

CONDITION_EXPLORE = "explore"
HARNESS_CLAUDE_CODE = "claude-code"
SAMPLING_API_DEFAULT = "api_default"

# Exception-name -> non-completed status. Matched by ``exception_type`` name
# (a string) rather than ``isinstance``: classification must work on results
# loaded from disk where the live exception class is gone.
_TIMEOUT_EXC = "AgentTimeoutError"
_ENV_ERROR_EXC = frozenset({"EnvironmentStartTimeoutError", "RuntimeError"})
_AGENT_ERROR_EXC = frozenset({"AgentSetupTimeoutError"})


@dataclass(frozen=True)
class ManifestTask:
    """One benchmark task as declared in the sweep manifest."""

    task: str
    task_dir: str
    lang: str
    arch: str
    strace_image: str
    repo_root: str
    task_commit: str


def load_manifest(path: Path) -> list[ManifestTask]:
    """Read and parse the sweep manifest JSON into typed task entries.

    The manifest is a JSON object with a top-level ``tasks`` list. Any
    top-level keys beginning with ``_`` (e.g. ``_repo_root_note``) are
    treated as comments and ignored.
    """
    data = json.loads(Path(path).read_text())
    raw_tasks = data["tasks"]
    return [
        ManifestTask(
            task=entry["task"],
            task_dir=entry["task_dir"],
            lang=entry["lang"],
            arch=entry["arch"],
            strace_image=entry["strace_image"],
            repo_root=entry["repo_root"],
            task_commit=entry["task_commit"],
        )
        for entry in raw_tasks
    ]


# ---------------------------------------------------------------------------
# Manifest preflight: validate each task is well-formed before any run
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskPreflight:
    """Per-task preflight result. ``ok`` iff ``problems`` is empty."""

    task: str
    ok: bool
    problems: list[str] = field(default_factory=list)


def _check_task(entry: ManifestTask) -> list[str]:
    """Collect every preflight problem for one manifest task (pure-ish I/O)."""
    problems: list[str] = []
    task_dir = Path(entry.task_dir)

    if not task_dir.is_dir():
        problems.append(f"task_dir does not exist or is not a directory: {task_dir}")
        # Without the directory, nothing below can be checked.
        return problems

    if not (task_dir / "solution" / "solution.patch").is_file():
        problems.append("missing solution/solution.patch")

    if not (task_dir / "environment").is_dir():
        problems.append("missing environment/ directory")

    if not (task_dir / "tests").is_dir():
        problems.append("missing tests/ directory")

    problems.extend(_check_docker_image(task_dir, entry.strace_image))
    return problems


def _check_docker_image(task_dir: Path, strace_image: str) -> list[str]:
    """Validate task.toml parses and its docker_image is the strace tag."""
    toml_path = task_dir / "task.toml"
    if not toml_path.is_file():
        return ["missing task.toml"]

    try:
        doc = toml.load(toml_path)
    except toml.TomlDecodeError as exc:
        return [f"task.toml does not parse: {exc}"]

    docker_image = doc.get("environment", {}).get("docker_image")
    if not docker_image:
        return ["task.toml [environment].docker_image is missing or empty"]

    if docker_image != strace_image:
        return [
            "task.toml [environment].docker_image "
            f"{docker_image!r} != manifest strace_image {strace_image!r}"
        ]

    return []


def preflight_tasks(manifest: list[ManifestTask]) -> list[TaskPreflight]:
    """Validate every manifest task on disk before any run is attempted.

    For each task this checks that: the ``task_dir`` exists; a
    ``solution/solution.patch`` is present; ``task.toml`` exists and parses; its
    ``[environment].docker_image`` is present and equals the manifest entry's
    ``strace_image`` (a non-strace image would make the agent-env strace
    preflight RuntimeError at run time, or silently produce no trace); and the
    ``environment/`` and ``tests/`` directories exist.
    """
    return [
        TaskPreflight(task=entry.task, ok=not problems, problems=problems)
        for entry in manifest
        for problems in (_check_task(entry),)
    ]


def all_green(report: list[TaskPreflight]) -> bool:
    """Whether every task in a preflight report passed."""
    return all(p.ok for p in report)


def cell_id(
    condition: str, task: str, model: str, replicate_index: int, arch: str
) -> str:
    """Deterministic, suffix-free identifier for one sweep cell."""
    return f"{condition}/{task}/{model}/{replicate_index}/{arch}"


@dataclass(frozen=True)
class SweepCell:
    cell_id: str
    task: str
    model: str
    replicate_index: int  # NOT a seed — Pier does not plumb sampling control
    config: TrialConfig
    # Per-cell manifest provenance — each task in a sweep has its own commit /
    # repo_root, so these are carried on the cell, not passed once to run_sweep.
    task_commit: str = "unknown"
    repo_root: str = "unknown"


def _trials_dir(out_root: Path, task: str, condition: str, arch: str) -> Path:
    """Encode (task, condition, arch) into the per-cell trials directory."""
    return Path(out_root) / task / condition / arch


def build_sweep_configs(
    manifest: list[ManifestTask],
    models: list[str],
    k: int,
    *,
    condition: str = CONDITION_EXPLORE,
    arch: str,
    out_root: Path,
) -> list[SweepCell]:
    """Build one TrialConfig per (task, model, replicate).

    Pure: consumes an already-parsed manifest and returns ``len(manifest) *
    len(models) * k`` cells. Verification is disabled (capture-only). No Docker,
    no filesystem writes.

    Capture is enabled at run time via the ``PIER_CAPTURE_STRACE`` env var, not
    here.
    """
    cells: list[SweepCell] = []
    for task in manifest:
        for model in models:
            for replicate_index in range(k):
                config = TrialConfig(
                    task=TaskConfig(path=Path(task.task_dir)),
                    trials_dir=_trials_dir(out_root, task.task, condition, arch),
                    agent=AgentConfig(
                        name=AgentName.CLAUDE_CODE.value,
                        model_name=model,
                    ),
                    verifier=VerifierConfig(disable=True),
                )
                cells.append(
                    SweepCell(
                        cell_id=cell_id(
                            condition, task.task, model, replicate_index, arch
                        ),
                        task=task.task,
                        model=model,
                        replicate_index=replicate_index,
                        config=config,
                        task_commit=task.task_commit,
                        repo_root=task.repo_root,
                    )
                )
    return cells


# ---------------------------------------------------------------------------
# Run orchestration + capture-index
# ---------------------------------------------------------------------------

TrialStatus = Literal[
    "pending",
    "completed",
    "env_error",
    "agent_error",
    "capture_error",
    "missing_trace",
    "other",
]
ModelPatchState = Literal["present_nonempty", "present_empty_no_edits", "absent"]


class CaptureIndexEntry(TypedDict):
    """One row of the capture-index: the durable record for a single cell.

    The schema is sourced from exactly three places so each field has one
    honest origin:

    - the :class:`SweepCell` (``cell_id``, join keys, ``replicate_index``),
    - the manifest (``task_commit``, ``repo_root``),
    - the :class:`~pier.models.trial.result.TrialResult` and on-disk artifacts
      (model identity, statuses, timing, artifact booleans).
    """

    cell_id: str
    trial_id: NotRequired[str]
    trial_dir: NotRequired[str]
    task: str
    task_commit: str
    repo_root: str
    condition: str
    arch: str
    harness: str
    model_provider: str
    model_name: str
    model_alias: NotRequired[str]
    model_date: NotRequired[str]
    sampling_config: str
    replicate_index: int
    trial_status: TrialStatus
    failure_class: NotRequired[str]
    model_patch_state: NotRequired[ModelPatchState]
    has_trajectory: bool
    has_strace: bool
    has_result: bool
    wall_seconds: NotRequired[float]
    timed_out: bool
    started_at: str
    finished_at: NotRequired[str]


def classify_trial_status(
    result: "TrialResult",
    *,
    has_trajectory: bool,
    has_strace: bool,
) -> tuple[TrialStatus, str | None]:
    """Map a finished :class:`TrialResult` + observed artifacts to a status.

    Matching is by ``exception_info.exception_type`` (a string) so a result
    rehydrated from ``result.json`` classifies identically to a live one.

    - ``AgentTimeoutError`` with trajectory+strace present: the agent ran and
      produced a usable capture, so the cell is ``completed`` with the failure
      recorded as ``agent_timeout`` (a soft outcome, not a capture defect).
    - ``EnvironmentStartTimeoutError`` / a preflight ``RuntimeError`` (e.g. the
      strace-image is missing): ``env_error``.
    - ``AgentSetupTimeoutError``: ``agent_error``.
    - No exception, artifacts present: ``completed``.
    - No exception but capture is enabled and strace is missing/empty despite a
      finished run: ``missing_trace`` (a capture defect, not an agent outcome).
    - Anything else with an exception: ``other`` (carrying the exception name).
    """
    exc = result.exception_info
    exc_type = exc.exception_type if exc is not None else None

    if exc_type == _TIMEOUT_EXC:
        if has_trajectory and has_strace:
            return "completed", "agent_timeout"
        # A timeout with no usable capture is a missing-trace capture defect.
        return "missing_trace", _TIMEOUT_EXC

    if exc_type in _ENV_ERROR_EXC:
        return "env_error", exc_type

    if exc_type in _AGENT_ERROR_EXC:
        return "agent_error", exc_type

    if exc_type is not None:
        return "other", exc_type

    # No exception: a finished run. If capture is armed but strace is absent or
    # empty, the run completed but the trace did not survive.
    if _capture_armed() and not has_strace:
        return "missing_trace", None

    return "completed", None


def _capture_armed() -> bool:
    """Whether strace capture is requested via ``PIER_CAPTURE_STRACE``."""
    return os.environ.get("PIER_CAPTURE_STRACE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _model_patch_state(trial_dir: Path) -> ModelPatchState:
    """Classify ``agent/model.patch``: nonempty / empty / absent."""
    model_patch = trial_dir / "agent" / "model.patch"
    if not model_patch.exists():
        return "absent"
    if model_patch.read_text().strip():
        return "present_nonempty"
    return "present_empty_no_edits"


def _wall_seconds(result: "TrialResult") -> float | None:
    """Derive agent wall time from ``agent_execution`` timing (None-guarded)."""
    timing = result.agent_execution
    if timing is None or timing.started_at is None or timing.finished_at is None:
        return None
    return (timing.finished_at - timing.started_at).total_seconds()


def _model_identity(result: "TrialResult") -> tuple[str, str]:
    """Extract (provider, name) from ``agent_info.model_info`` (None-guarded)."""
    model_info = result.agent_info.model_info
    if model_info is None:
        return "unknown", "unknown"
    return (model_info.provider or "unknown"), model_info.name


def _resolve_trial_dir(cell: "SweepCell", result: "TrialResult | None") -> Path:
    """Resolve the cell's trial directory.

    The trial dir is ``config.trials_dir / trial_name``. The trial name is
    taken off the ``TrialResult`` when one was produced; otherwise the runner
    failed before a result, so only the cell's ``trials_dir`` is known.
    """
    trials_dir = Path(cell.config.trials_dir)
    if result is not None:
        return trials_dir / result.trial_name
    return trials_dir


def _read_index(path: Path) -> list[CaptureIndexEntry]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _write_index(path: Path, entries: list[CaptureIndexEntry]) -> None:
    """Atomically replace the whole capture-index JSON (temp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(entries, indent=2))
    os.replace(tmp, path)


def _pending_entry(cell: "SweepCell") -> CaptureIndexEntry:
    """The placeholder row written BEFORE a cell's runner is invoked."""
    condition, task, model, replicate_index, arch = _parse_cell_id(cell)
    return CaptureIndexEntry(
        cell_id=cell.cell_id,
        task=task,
        task_commit=cell.task_commit,
        repo_root=cell.repo_root,
        condition=condition,
        arch=arch,
        harness=HARNESS_CLAUDE_CODE,
        model_provider="unknown",
        model_name=model,
        sampling_config=SAMPLING_API_DEFAULT,
        replicate_index=replicate_index,
        trial_status="pending",
        has_trajectory=False,
        has_strace=False,
        has_result=False,
        timed_out=False,
        started_at=datetime.now(timezone.utc).isoformat(),
    )


def _parse_cell_id(cell: "SweepCell") -> tuple[str, str, str, int, str]:
    """Recover (condition, task, model, replicate_index, arch) from a cell.

    ``cell_id`` is ``condition/task/model/replicate_index/arch``; ``task`` and
    ``replicate_index`` are also carried on the cell directly, so the cell is
    the authority for those and the id supplies ``condition``/``arch``.
    """
    parts = cell.cell_id.split("/")
    condition, arch = parts[0], parts[-1]
    return condition, cell.task, cell.model, cell.replicate_index, arch


def _terminal_entry(
    cell: "SweepCell",
    result: "TrialResult",
    pending: CaptureIndexEntry,
) -> CaptureIndexEntry:
    """Build the terminal entry from a finished result + on-disk artifacts."""
    trial_dir = _resolve_trial_dir(cell, result)
    agent_dir = trial_dir / "agent"

    has_trajectory = (agent_dir / "trajectory.json").exists()
    strace_path = agent_dir / "strace.log"
    has_strace = strace_path.exists() and strace_path.stat().st_size > 0
    has_result = (trial_dir / "result.json").exists()

    status, failure_class = classify_trial_status(
        result, has_trajectory=has_trajectory, has_strace=has_strace
    )
    provider, name = _model_identity(result)

    exc = result.exception_info
    timed_out = exc is not None and exc.exception_type == _TIMEOUT_EXC

    entry: CaptureIndexEntry = dict(pending)  # type: ignore[assignment]
    entry["trial_id"] = result.trial_name
    entry["trial_dir"] = str(trial_dir)
    entry["model_provider"] = provider
    entry["model_name"] = name
    entry["trial_status"] = status
    entry["has_trajectory"] = has_trajectory
    entry["has_strace"] = has_strace
    entry["has_result"] = has_result
    entry["model_patch_state"] = _model_patch_state(trial_dir)
    entry["timed_out"] = timed_out
    if failure_class is not None:
        entry["failure_class"] = failure_class
    wall = _wall_seconds(result)
    if wall is not None:
        entry["wall_seconds"] = wall
    if result.finished_at is not None:
        entry["finished_at"] = result.finished_at.isoformat()
    return entry


def _error_entry(
    pending: CaptureIndexEntry,
    exc: BaseException,
) -> CaptureIndexEntry:
    """Build a terminal entry when the runner itself raised (no result)."""
    entry: CaptureIndexEntry = dict(pending)  # type: ignore[assignment]
    entry["trial_status"] = "other"
    entry["failure_class"] = type(exc).__name__
    return entry


async def run_sweep(
    cells: list["SweepCell"],
    capture_index_path: Path,
    *,
    run_trial: Optional[Callable[[TrialConfig], "Awaitable[TrialResult]"]] = None,
    skip_completed: bool = True,
) -> list[CaptureIndexEntry]:
    """Run each cell, persisting a pending->terminal capture-index entry.

    For every cell:

    1. A ``pending`` entry is persisted to ``capture_index_path`` ATOMICALLY
       BEFORE ``run_trial`` is called, so a crash mid-run leaves a record.
    2. ``run_trial(cell.config)`` runs the trial (default: ``Trial.create`` +
       ``await .run()``).
    3. Artifacts under ``trial_dir/agent`` are observed, the status is
       classified, model identity / timing / patch-state are extracted, and the
       entry is rewritten to its terminal status atomically.

    Per-cell failures are caught narrowly and recorded as an ``other`` terminal
    entry so one bad cell does not abort the sweep. With ``skip_completed`` a
    cell whose ``cell_id`` already has a ``completed`` entry in the index is
    skipped and its prior entry preserved (merge, not clobber).
    """
    if run_trial is None:
        run_trial = _default_run_trial

    capture_index_path = Path(capture_index_path)
    entries: dict[str, CaptureIndexEntry] = {
        entry["cell_id"]: entry for entry in _read_index(capture_index_path)
    }

    for cell in cells:
        existing = entries.get(cell.cell_id)
        if skip_completed and existing is not None and existing["trial_status"] == (
            "completed"
        ):
            continue

        pending = _pending_entry(cell)
        entries[cell.cell_id] = pending
        _write_index(capture_index_path, list(entries.values()))

        try:
            result = await run_trial(cell.config)
            entries[cell.cell_id] = _terminal_entry(cell, result, pending)
        except Exception as exc:  # noqa: BLE001 - per-cell isolation
            entries[cell.cell_id] = _error_entry(pending, exc)

        _write_index(capture_index_path, list(entries.values()))

    return list(entries.values())


async def _default_run_trial(config: TrialConfig) -> "TrialResult":
    """Default runner: create and run a real Pier trial (Docker-backed)."""
    from pier.trial.trial import Trial

    trial = await Trial.create(config)
    return await trial.run()
