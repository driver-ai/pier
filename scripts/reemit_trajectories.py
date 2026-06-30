#!/usr/bin/env python3
"""Offline re-emit of Claude Code ATIF trajectory.json files.

Re-runs the (fixed) ClaudeCode ATIF converter against the on-disk session
JSONL of every trial under a run root, rewriting each ``agent/trajectory.json``
so that delegated subagent sessions are recovered into ``subagent_trajectories``
(and ref-linked to their spawning Task/Agent step where resolvable).

This is purely offline: it reads the existing ``*.jsonl`` sessions and the
``claude-code.txt`` stream (for cost), instantiates the real pier ClaudeCode
adapter, and calls its conversion directly. It NEVER calls a model/API and
NEVER modifies the raw ``*.jsonl`` sessions.

Idempotency / safety:
  - Before rewriting, the existing ``trajectory.json`` is backed up to
    ``trajectory.json.orig`` (only if no ``.orig`` already exists).
  - The converter always reads from the raw sessions, never from a prior
    ``trajectory.json``, so re-running is safe and deterministic.

Usage:
    uv run python scripts/reemit_trajectories.py <run_root> [<run_root> ...]
    uv run python scripts/reemit_trajectories.py --dry-run <run_root>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pier.agents.installed.claude_code import ClaudeCode

_MODEL_SEGMENT = re.compile(r"/(claude-[a-z0-9.-]+)/")


def _model_name_for(agent_dir: Path) -> str | None:
    """Best-effort model name from the trial path (e.g. .../claude-opus-4-8/...).

    The converter derives the real model from session events; this only feeds
    the rarely-used fallback, so a miss is harmless.
    """
    match = _MODEL_SEGMENT.search(agent_dir.as_posix())
    return match.group(1) if match else None


def find_agent_dirs(run_root: Path) -> list[Path]:
    """Every ``.../agent/`` dir that has a ``trajectory.json`` under run_root."""
    return sorted({p.parent for p in run_root.rglob("agent/trajectory.json")})


def reemit_one(agent_dir: Path, *, dry_run: bool) -> dict[str, object]:
    """Re-emit a single trial's trajectory.json. Returns a per-trial summary."""
    result: dict[str, object] = {
        "agent_dir": agent_dir.as_posix(),
        "status": "ok",
        "subagents": 0,
        "child_tool_calls": 0,
        "child_read_calls": 0,
    }

    traj_path = agent_dir / "trajectory.json"
    orig_path = agent_dir / "trajectory.json.orig"

    cc = ClaudeCode(logs_dir=agent_dir, model_name=_model_name_for(agent_dir))
    session_dir = cc._get_session_dir()
    if session_dir is None:
        result["status"] = "skipped:no_session_dir"
        return result

    try:
        trajectory = cc._convert_events_to_trajectory(session_dir)
    except Exception as exc:  # noqa: BLE001 - record and move on
        result["status"] = f"error:{type(exc).__name__}:{exc}"
        return result
    if trajectory is None:
        result["status"] = "skipped:no_trajectory"
        return result

    # Recursive subagent stats for reporting.
    def walk(t) -> tuple[int, int, int]:
        n_sub = 0
        tool_calls = 0
        reads = 0
        for child in t.subagent_trajectories or []:
            n_sub += 1
            for step in child.steps:
                for call in step.tool_calls or []:
                    tool_calls += 1
                    if call.function_name == "Read":
                        reads += 1
            cn, ctc, cr = walk(child)
            n_sub += cn
            tool_calls += ctc
            reads += cr
        return n_sub, tool_calls, reads

    n_sub, child_tc, child_reads = walk(trajectory)
    result["subagents"] = n_sub
    result["child_tool_calls"] = child_tc
    result["child_read_calls"] = child_reads

    if dry_run:
        result["status"] = "dry-run"
        return result

    # Back up the existing file once (idempotent).
    if traj_path.exists() and not orig_path.exists():
        orig_path.write_bytes(traj_path.read_bytes())

    payload = trajectory.to_json_dict()
    tmp = traj_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    tmp.replace(traj_path)
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_roots", nargs="+", type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and report subagent stats without writing files.",
    )
    args = parser.parse_args(argv)

    grand = {
        "trials": 0,
        "with_subagents": 0,
        "no_subagents": 0,
        "skipped": 0,
        "errors": 0,
        "total_subagents": 0,
        "total_child_tool_calls": 0,
        "total_child_read_calls": 0,
    }
    errors: list[str] = []

    for run_root in args.run_roots:
        agent_dirs = find_agent_dirs(run_root)
        print(f"[{run_root}] {len(agent_dirs)} trials")
        for i, agent_dir in enumerate(agent_dirs, 1):
            summary = reemit_one(agent_dir, dry_run=args.dry_run)
            grand["trials"] += 1
            status = str(summary["status"])
            if status.startswith("error"):
                grand["errors"] += 1
                errors.append(f"{summary['agent_dir']}: {status}")
            elif status.startswith("skipped"):
                grand["skipped"] += 1
            n_sub = int(summary["subagents"])  # type: ignore[arg-type]
            if n_sub > 0:
                grand["with_subagents"] += 1
            else:
                grand["no_subagents"] += 1
            grand["total_subagents"] += n_sub
            grand["total_child_tool_calls"] += int(summary["child_tool_calls"])  # type: ignore[arg-type]
            grand["total_child_read_calls"] += int(summary["child_read_calls"])  # type: ignore[arg-type]
            if i % 200 == 0:
                print(f"  ...{i}/{len(agent_dirs)}")

    print("\n=== SUMMARY ===")
    for key, value in grand.items():
        print(f"{key}: {value}")
    if errors:
        print(f"\n=== {len(errors)} ERRORS ===")
        for line in errors[:50]:
            print(line)
    return 1 if grand["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
