"""Subagent-trajectory embedding + tree reconstruction (PR #7, ae25c7e).

Pins the delegation-tree reconstruction in the claude-code ATIF converter so it can't silently
regress as the converter evolves (jtdriver review ask). Covers the pure helpers directly and the
end-to-end `_attach_subagent_trajectories` over a fixture session dir (a `subagents/*.jsonl` child
+ a `*.meta.json` `toolUseId` link) for the three tree cases: flat (child under primary), nested
(child under another child — the `parent_for` cross-child scan), and orphan (unknown parent →
attached to primary so no child is ever dropped).
"""

from __future__ import annotations

import json
from pathlib import Path

from pier.agents.installed.claude_code import ClaudeCode
from pier.models.trajectories import (
    Agent,
    Observation,
    ObservationResult,
    Step,
    Trajectory,
    ToolCall,
)


def _agent() -> ClaudeCode:
    return ClaudeCode(logs_dir=Path("/tmp"), model_name="anthropic/claude-haiku-4-5")


def _primary_with_call(tool_use_id: str) -> Trajectory:
    """A minimal primary trajectory whose single step emits `tool_use_id` (a Task spawn)."""
    return Trajectory(
        agent=Agent(name="claude-code", version="1.0"),
        steps=[
            Step(
                step_id=1,
                source="agent",
                message="spawning a subagent",
                tool_calls=[ToolCall(tool_call_id=tool_use_id, function_name="Task", arguments={})],
            )
        ],
    )


def _write_child_session(session_dir: Path, agent_id: str, *, own_tool_id: str, tool_use_id: str,
                         agent_type: str = "Explore", description: str = "child work") -> None:
    """Write a `subagents/agent-<id>.jsonl` (one assistant tool_use) + its `.meta.json` link."""
    sub = session_dir / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    event = {
        "type": "assistant",
        "timestamp": "2026-07-01T00:00:00Z",
        "sessionId": f"sess-{agent_id}",
        "version": "1.0",
        "message": {
            "id": f"msg-{agent_id}",
            "model": "claude-haiku-4-5",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "doing child work"},
                {"type": "tool_use", "id": own_tool_id, "name": "Read", "input": {"file_path": "/app/x.py"}},
            ],
        },
    }
    (sub / f"agent-{agent_id}.jsonl").write_text(json.dumps(event) + "\n")
    (sub / f"agent-{agent_id}.meta.json").write_text(
        json.dumps({"toolUseId": tool_use_id, "agentType": agent_type, "description": description})
    )


# --- pure helpers ----------------------------------------------------------- #

def test_discover_subagent_files_finds_all_excludes_meta(tmp_path: Path):
    (tmp_path / "subagents").mkdir()
    (tmp_path / "subagents" / "agent-a.jsonl").write_text("{}\n")
    (tmp_path / "subagents" / "agent-a.meta.json").write_text("{}")
    (tmp_path / "nested" / "subagents").mkdir(parents=True)
    (tmp_path / "nested" / "subagents" / "agent-b.jsonl").write_text("{}\n")
    found = ClaudeCode._discover_subagent_files(tmp_path)
    names = [f.name for f in found]
    # Finds the whole transitive set (flat + nested subagents/ dirs); excludes the .meta.json sidecar.
    assert set(names) == {"agent-a.jsonl", "agent-b.jsonl"}
    assert "agent-a.meta.json" not in names


def test_read_subagent_meta_parses_and_tolerates_missing(tmp_path: Path):
    f = tmp_path / "agent-a.jsonl"
    f.write_text("{}\n")
    (tmp_path / "agent-a.meta.json").write_text(
        json.dumps({"toolUseId": "toolu_X", "agentType": "Explore", "description": "d"})
    )
    meta = ClaudeCode._read_subagent_meta(f)
    assert meta["toolUseId"] == "toolu_X" and meta["agentType"] == "Explore"
    # Missing/malformed meta → empty dict (never raises).
    assert ClaudeCode._read_subagent_meta(tmp_path / "agent-none.jsonl") == {}


def test_tool_call_ids_in_trajectory_collects_ids():
    traj = _primary_with_call("toolu_PARENT")
    assert ClaudeCode._tool_call_ids_in_trajectory(traj) == {"toolu_PARENT"}


def test_link_subagent_ref_synthesizes_observation_when_absent():
    primary = _primary_with_call("toolu_PARENT")
    child = Trajectory(agent=Agent(name="claude-code", version="1.0"), trajectory_id="subagent-0-agent-c", steps=[Step(step_id=1, source="agent", message="child")])
    linked = ClaudeCode._link_subagent_ref(primary, "toolu_PARENT", child)
    assert linked
    obs = primary.steps[0].observation
    assert obs is not None
    ref = obs.results[0].subagent_trajectory_ref[0]
    assert ref.trajectory_id == "subagent-0-agent-c"


def test_link_subagent_ref_appends_to_existing_observation_result():
    primary = _primary_with_call("toolu_PARENT")
    primary.steps[0].observation = Observation(
        results=[ObservationResult(source_call_id="toolu_PARENT", content="tool output")]
    )
    child = Trajectory(agent=Agent(name="claude-code", version="1.0"), trajectory_id="subagent-0-agent-c", steps=[Step(step_id=1, source="agent", message="child")])
    assert ClaudeCode._link_subagent_ref(primary, "toolu_PARENT", child)
    refs = primary.steps[0].observation.results[0].subagent_trajectory_ref
    assert [r.trajectory_id for r in refs] == ["subagent-0-agent-c"]


def test_link_subagent_ref_returns_false_when_no_matching_step():
    primary = _primary_with_call("toolu_PARENT")
    child = Trajectory(agent=Agent(name="claude-code", version="1.0"), trajectory_id="c", steps=[Step(step_id=1, source="agent", message="child")])
    assert ClaudeCode._link_subagent_ref(primary, "toolu_NOT_HERE", child) is False


# --- end-to-end tree reconstruction over a fixture session dir -------------- #

def test_attach_flat_child_under_primary_with_ref(tmp_path: Path):
    primary = _primary_with_call("toolu_PARENT")
    _write_child_session(tmp_path, "child", own_tool_id="toolu_CHILD_READ", tool_use_id="toolu_PARENT")
    _agent()._attach_subagent_trajectories(primary, tmp_path)

    assert primary.subagent_trajectories and len(primary.subagent_trajectories) == 1
    child = primary.subagent_trajectories[0]
    assert child.extra["subagent_type"] == "Explore"
    # The spawning step now refs the child.
    ref = primary.steps[0].observation.results[0].subagent_trajectory_ref[0]
    assert ref.trajectory_id == child.trajectory_id


def test_attach_nested_child_under_another_child(tmp_path: Path):
    """B.meta.toolUseId points at A's own tool_call → B nests under A (parent_for cross-child scan)."""
    primary = _primary_with_call("toolu_PARENT")
    # A: spawned by primary; itself emits toolu_A_SPAWN
    _write_child_session(tmp_path, "a", own_tool_id="toolu_A_SPAWN", tool_use_id="toolu_PARENT")
    # B: spawned by A (its toolUseId is A's tool_call, not primary's)
    _write_child_session(tmp_path, "b", own_tool_id="toolu_B_READ", tool_use_id="toolu_A_SPAWN")
    _agent()._attach_subagent_trajectories(primary, tmp_path)

    # Primary has exactly ONE direct child (A); B is nested under A, not the primary.
    assert len(primary.subagent_trajectories) == 1
    a = primary.subagent_trajectories[0]
    assert a.subagent_trajectories and len(a.subagent_trajectories) == 1
    b = a.subagent_trajectories[0]
    assert "agent-b" in b.trajectory_id
    # A's spawning step refs B.
    a_ref = a.steps[0].observation.results[0].subagent_trajectory_ref[0]
    assert a_ref.trajectory_id == b.trajectory_id


def test_attach_orphan_child_falls_back_to_primary(tmp_path: Path):
    """A child whose parent tool_use can't be located is still embedded (under primary), never dropped."""
    primary = _primary_with_call("toolu_PARENT")
    _write_child_session(tmp_path, "orphan", own_tool_id="toolu_O", tool_use_id="toolu_UNKNOWN")
    _agent()._attach_subagent_trajectories(primary, tmp_path)
    assert primary.subagent_trajectories and len(primary.subagent_trajectories) == 1
    # Orphan attaches to primary; no ref is forced (the tool_use isn't in the primary's steps).
    assert primary.steps[0].observation is None


def test_attach_reference_cycle_between_children_drops_neither(tmp_path: Path):
    """Two children whose meta toolUseIds point at each other (a cycle, e.g. corrupt/crafted meta)
    resolve to each other, not the primary. Serialization walks from the root, so without a guard
    both trajectories — and all their recovered tool calls — vanish. The cycle must fall back to the
    primary so neither is dropped (the method's documented guarantee)."""
    primary = _primary_with_call("toolu_PARENT")
    # A spawned by B's tool_call (toolu_B); B spawned by A's tool_call (toolu_A) → a 2-cycle.
    _write_child_session(tmp_path, "a", own_tool_id="toolu_A", tool_use_id="toolu_B")
    _write_child_session(tmp_path, "b", own_tool_id="toolu_B", tool_use_id="toolu_A")
    _agent()._attach_subagent_trajectories(primary, tmp_path)

    # Both children survive, reachable directly from the root (cycle broken at the primary).
    assert primary.subagent_trajectories and len(primary.subagent_trajectories) == 2
    ids = {t.trajectory_id for t in primary.subagent_trajectories}
    assert any("agent-a" in i for i in ids) and any("agent-b" in i for i in ids)
    # Neither is nested under the other (that nesting is the cycle we refused to build).
    assert all(not t.subagent_trajectories for t in primary.subagent_trajectories)
    # Their recovered tool calls are preserved (the whole point of "never dropped").
    recovered = set()
    for t in primary.subagent_trajectories:
        recovered |= ClaudeCode._tool_call_ids_in_trajectory(t)
    assert {"toolu_A", "toolu_B"} <= recovered
