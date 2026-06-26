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
from dataclasses import dataclass
from pathlib import Path

from pier.models.agent.name import AgentName
from pier.models.trial.config import (
    AgentConfig,
    TaskConfig,
    TrialConfig,
    VerifierConfig,
)

CONDITION_EXPLORE = "explore"


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
                    )
                )
    return cells
