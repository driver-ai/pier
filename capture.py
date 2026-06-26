"""Thin entrypoint for the Phase C explore-capture sweep.

Loads the sweep manifest, builds the per-cell ``TrialConfig`` list via the pure
builders in :mod:`pier.trial.sweep`, then runs the sweep through
:func:`pier.trial.sweep.run_sweep`, which persists a pending->terminal
capture-index entry per cell and resumes by ``cell_id`` on re-run.

Capture (strace) is armed at run time via ``PIER_CAPTURE_STRACE=1``; this
script does not set it. Usage::

    PIER_CAPTURE_STRACE=1 python capture.py [MANIFEST] [OUT_ROOT]

Defaults: manifest ``experiments/phase_c_manifest.json``; output under
``~/work/driver/driver-ai/captured-trials/phase-c``.
"""

import asyncio
import sys
from pathlib import Path

from pier.trial.sweep import (
    all_green,
    build_sweep_configs,
    load_manifest,
    preflight_tasks,
    run_sweep,
)

# A small explore-condition model set for the smoke run; the full sweep matrix
# lives in the run manifest / DEC-056.
_MODELS = ["claude-sonnet-4-5"]
_K = 1
_DEFAULT_MANIFEST = Path("experiments/phase_c_manifest.json")
_DEFAULT_OUT_ROOT = Path.home() / "work/driver/driver-ai/captured-trials/phase-c"


async def main() -> None:
    manifest_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_MANIFEST
    out_root = Path(sys.argv[2]) if len(sys.argv) > 2 else _DEFAULT_OUT_ROOT

    tasks = load_manifest(manifest_path)

    # Fail fast BEFORE spending any Docker/credits: reject a task whose image
    # is not the strace tag (it would RuntimeError the in-container preflight or
    # produce an empty trace), or that is otherwise malformed.
    report = preflight_tasks(tasks)
    if not all_green(report):
        for p in report:
            if not p.ok:
                print(f"preflight FAIL {p.task}: {'; '.join(p.problems)}")
        sys.exit(1)

    # Arch is per-task (carried on each SweepCell); commit / repo_root likewise.
    cells = build_sweep_configs(
        tasks,
        models=_MODELS,
        k=_K,
        out_root=out_root,
    )

    capture_index_path = out_root / "capture_index.json"
    entries = await run_sweep(cells, capture_index_path)

    for entry in entries:
        print(entry["cell_id"], entry["trial_status"])
    print(f"capture index: {capture_index_path} ({len(entries)} cells)")


if __name__ == "__main__":
    asyncio.run(main())
