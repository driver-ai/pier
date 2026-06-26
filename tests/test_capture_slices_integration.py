"""Gated integration slices for the Phase C explore-capture sweep (Plan 11 Task 7).

These drive the REAL sweep harness (`build_sweep_configs` -> `run_sweep`) against
the already-built ``*-strace`` task images, capture-only (`verifier.disable=True`),
with capture armed via ``PIER_CAPTURE_STRACE=1``. They are an INFRASTRUCTURE GATE,
not evidence: they prove the harness captures the artifacts and accounts every cell
in the capture-index. They make NO claim about gathering, pass rates, or Driver
(the No-Claim Boundary).

Opt-in only — set ``PIER_RUN_CAPTURE_SLICES=1`` (and supply model credentials +
the local ``deepswe-*:arm64-strace`` images) to run the real container captures.
Absent that (or a usable Docker daemon) the whole module skips cleanly.

Scoring the captured trials through pier-analytics ``run_records`` is an
operator-gated runbook step (cross-repo; needs a local editable pier-analytics),
NOT asserted here.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pier.trial.sweep import (
    ManifestTask,
    build_sweep_configs,
    load_manifest,
    run_sweep,
)

_OPT_IN_VAR = "PIER_RUN_CAPTURE_SLICES"
_MANIFEST = Path(__file__).resolve().parents[1] / "experiments" / "phase_c_manifest.json"

# The three already-built *img tasks (span Python / Go / TypeScript).
_IMG_TASKS = (
    "httpx-streaming-json-iteration",
    "expr-try-catch-errors",
    "koota-deferred-mutation-buffer",
)
# DEC-056 model set; overridable so an operator can pin exact provider ids.
_MODELS = os.environ.get(
    "PIER_SLICE_MODELS",
    "claude-haiku-4-5,claude-sonnet-4-6,claude-opus-4-8",
).split(",")
_SLICE0_MODEL = os.environ.get("PIER_SLICE0_MODEL", "claude-sonnet-4-6")
_K = int(os.environ.get("PIER_SLICE_K", "5"))


def _docker_daemon_usable() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10, check=True
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    return True


def _skip_reason() -> str | None:
    if os.environ.get(_OPT_IN_VAR, "").strip().lower() not in {"1", "true", "yes"}:
        return (
            f"capture slices are opt-in; set {_OPT_IN_VAR}=1 (and model "
            "credentials + the local deepswe-*:arm64-strace images) to run them"
        )
    if not _docker_daemon_usable():
        return "Docker daemon not usable (docker not on PATH or `docker info` failed)"
    if not _MANIFEST.is_file():
        return f"manifest not found: {_MANIFEST}"
    return None


_SKIP_REASON = _skip_reason()
pytestmark = pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")


def _img_manifest() -> list[ManifestTask]:
    """The manifest filtered to the three already-built *img tasks."""
    tasks = [t for t in load_manifest(_MANIFEST) if t.task in _IMG_TASKS]
    assert tasks, f"none of the *img tasks {_IMG_TASKS} are in {_MANIFEST}"
    return tasks


def _is_terminal(entry: dict) -> bool:
    return entry["trial_status"] != "pending"


def test_slice0_capture_produces_artifacts(tmp_path, monkeypatch):
    """Slice 0 (1 task x 1 model): one cell captures + is accounted. NOT evidence."""
    monkeypatch.setenv("PIER_CAPTURE_STRACE", "1")
    tasks = [t for t in _img_manifest() if t.task == _IMG_TASKS[0]]
    cells = build_sweep_configs(
        tasks, models=[_SLICE0_MODEL], k=1, out_root=tmp_path
    )
    assert len(cells) == 1

    index_path = tmp_path / "capture_index.json"
    import asyncio

    entries = asyncio.run(run_sweep(cells, index_path))

    assert len(entries) == 1
    entry = entries[0]
    assert _is_terminal(entry), entry
    # On a completed cell the capture artifacts must be present.
    if entry["trial_status"] == "completed":
        trial_dir = Path(entry["trial_dir"])
        assert (trial_dir / "agent" / "trajectory.json").is_file()
        strace = trial_dir / "agent" / "strace.log"
        assert strace.is_file() and strace.stat().st_size > 0
        assert (trial_dir / "result.json").is_file()
        assert entry["has_strace"] is True


def test_slice1_45_trials_produce_accounted_index(tmp_path, monkeypatch):
    """Slice 1 (3 tasks x 3 models x K): every expected cell is accounted."""
    monkeypatch.setenv("PIER_CAPTURE_STRACE", "1")
    tasks = _img_manifest()
    cells = build_sweep_configs(
        tasks, models=_MODELS, k=_K, out_root=tmp_path
    )
    expected = len(tasks) * len(_MODELS) * _K
    assert len(cells) == expected  # 3 * 3 * 5 = 45 by default

    index_path = tmp_path / "capture_index.json"
    import asyncio

    entries = asyncio.run(run_sweep(cells, index_path))

    # No silent loss: one accounted, terminal entry per expected cell.
    assert len(entries) == expected
    by_cell = {e["cell_id"]: e for e in entries}
    for cell in cells:
        assert cell.cell_id in by_cell, f"missing cell {cell.cell_id}"
        assert _is_terminal(by_cell[cell.cell_id]), by_cell[cell.cell_id]
    # Per task/model coverage is complete.
    seen = {(e["task"], e["model_name"]) for e in entries}
    assert len(seen) >= len(tasks)  # at least one entry per task
