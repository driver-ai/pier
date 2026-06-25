"""Converter coverage for embedded subagent trajectories (ATIF-v1.7).

These tests exercise the claude-code converter against the REAL on-disk
layout: under ``projects/<slug>/`` the parent session is the FILE
``<parent-uuid>.jsonl`` and its subagents live in the SIBLING directory
``<parent-uuid>/subagents/agent-<id>.jsonl`` (+ ``agent-<id>.meta.json``).
"""

import json
from pathlib import Path

from pier.agents.installed.claude_code import ClaudeCode

_PARENT_UUID = "11111111-1111-1111-1111-111111111111"
_TOOL_USE_ID = "toolu_explore_01"


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")


def _parent_events(*, with_dispatch: bool = True) -> list[dict]:
    """A parent session that dispatches one subagent via the Task tool."""
    content = [{"type": "text", "text": "Dispatching an explorer."}]
    if with_dispatch:
        content.append(
            {
                "type": "tool_use",
                "id": _TOOL_USE_ID,
                "name": "Task",
                "input": {"description": "explore the code", "subagent_type": "Explore"},
            }
        )
    events = [
        {
            "type": "assistant",
            "timestamp": "2026-06-24T00:00:01Z",
            "sessionId": "sess-parent",
            "version": "1.2.3",
            "message": {
                "id": "msg_parent_1",
                "role": "assistant",
                "model": "claude-opus-4-8",
                "content": content,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        }
    ]
    if with_dispatch:
        events.append(
            {
                "type": "user",
                "timestamp": "2026-06-24T00:00:09Z",
                "sessionId": "sess-parent",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": _TOOL_USE_ID,
                            "content": "Subagent finished exploring.",
                        }
                    ],
                },
            }
        )
    return events


def _subagent_events() -> list[dict]:
    """A subagent session with one assistant message that yields >=1 step."""
    return [
        {
            "type": "assistant",
            "timestamp": "2026-06-24T00:00:05Z",
            "sessionId": "sess-sub",
            "version": "1.2.3",
            "isSidechain": True,
            "message": {
                "id": "msg_sub_1",
                "role": "assistant",
                "model": "claude-opus-4-8",
                "content": [{"type": "text", "text": "I explored the module."}],
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        }
    ]


def _build_session(
    tmp_path: Path,
    *,
    subagent_events: list[dict] | None,
    meta: dict | str | None,
    with_dispatch: bool = True,
) -> Path:
    """Build a projects/<slug> session dir; return that dir.

    ``meta`` may be a dict (written as JSON), a raw string (e.g. garbled
    JSON), or None (no .meta.json file written).
    """
    session_dir = tmp_path / "projects" / "-app"
    _write_jsonl(
        session_dir / f"{_PARENT_UUID}.jsonl",
        _parent_events(with_dispatch=with_dispatch),
    )

    if subagent_events is not None:
        sub_dir = session_dir / _PARENT_UUID / "subagents"
        _write_jsonl(sub_dir / "agent-explore01.jsonl", subagent_events)
        meta_path = sub_dir / "agent-explore01.meta.json"
        if isinstance(meta, dict):
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
        elif isinstance(meta, str):
            meta_path.write_text(meta, encoding="utf-8")

    return session_dir


def test_subagent_trajectories_populated(tmp_path: Path) -> None:
    agent = ClaudeCode(logs_dir=tmp_path, model_name="claude-opus-4-8")
    session_dir = _build_session(
        tmp_path,
        subagent_events=_subagent_events(),
        meta={
            "agentType": "Explore",
            "description": "explore the code",
            "toolUseId": _TOOL_USE_ID,
            "spawnDepth": 1,
        },
    )

    trajectory = agent._convert_events_to_trajectory(session_dir)

    assert trajectory is not None
    assert trajectory.subagent_trajectories is not None
    assert len(trajectory.subagent_trajectories) == 1
    sub = trajectory.subagent_trajectories[0]
    assert sub.trajectory_id == f"{_PARENT_UUID}/agent-explore01"
    assert sub.agent.name == "Explore"
    assert sub.agent.extra is not None
    assert sub.agent.extra["toolUseId"] == _TOOL_USE_ID
    assert sub.agent.extra["spawnDepth"] == 1
    assert len(sub.steps) >= 1


def test_malformed_subagent_meta_is_skipped(tmp_path: Path) -> None:
    agent = ClaudeCode(logs_dir=tmp_path, model_name="claude-opus-4-8")
    session_dir = _build_session(
        tmp_path,
        subagent_events=_subagent_events(),
        meta="{ this is not valid json",
    )

    # Must not raise; the subagent is still embedded with a fallback name.
    trajectory = agent._convert_events_to_trajectory(session_dir)

    assert trajectory is not None
    assert trajectory.subagent_trajectories is not None
    assert len(trajectory.subagent_trajectories) == 1
    assert trajectory.subagent_trajectories[0].agent.name == "subagent"


def test_no_subagent_trajectory_unchanged(tmp_path: Path) -> None:
    agent = ClaudeCode(logs_dir=tmp_path, model_name="claude-opus-4-8")
    session_dir = _build_session(
        tmp_path,
        subagent_events=None,
        meta=None,
        with_dispatch=False,
    )

    trajectory = agent._convert_events_to_trajectory(session_dir)

    assert trajectory is not None
    # [] -> None coercion keeps the key out of the serialized form entirely.
    assert trajectory.subagent_trajectories is None
    assert "subagent_trajectories" not in trajectory.to_json_dict()


def test_subagent_with_only_attachment_events_is_dropped(tmp_path: Path) -> None:
    agent = ClaudeCode(logs_dir=tmp_path, model_name="claude-opus-4-8")
    # A subagent log of only non-step (system/compact) events -> no steps ->
    # dropped (Trajectory requires steps min_length>=1).
    session_dir = _build_session(
        tmp_path,
        subagent_events=[
            {
                "type": "system",
                "timestamp": "2026-06-24T00:00:05Z",
                "message": {"subtype": "compact_boundary"},
            }
        ],
        meta={"agentType": "Explore", "toolUseId": _TOOL_USE_ID, "spawnDepth": 1},
    )

    trajectory = agent._convert_events_to_trajectory(session_dir)

    assert trajectory is not None
    # No valid subagent steps -> the subagent is dropped (-> None), parent link no-ops.
    assert trajectory.subagent_trajectories is None


def test_same_stem_across_subtrees_does_not_collide(tmp_path: Path) -> None:
    # Resume-seeding can leave two parent-uuid subtrees each holding the same
    # agent-<id> file. The bare stem would collide on the ATIF uniqueness
    # validator and (via the converter's broad except) drop the WHOLE
    # trajectory.json. The id must be qualified by the parent-uuid subtree.
    agent = ClaudeCode(logs_dir=tmp_path, model_name="claude-opus-4-8")
    session_dir = _build_session(
        tmp_path,
        subagent_events=_subagent_events(),
        meta={"agentType": "Explore", "toolUseId": _TOOL_USE_ID, "spawnDepth": 1},
    )
    # Second subtree with an identically-named subagent file.
    other_uuid = "22222222-2222-2222-2222-222222222222"
    other_sub = session_dir / other_uuid / "subagents"
    _write_jsonl(other_sub / "agent-explore01.jsonl", _subagent_events())
    (other_sub / "agent-explore01.meta.json").write_text(
        json.dumps({"agentType": "Explore"}), encoding="utf-8"
    )

    trajectory = agent._convert_events_to_trajectory(session_dir)

    assert trajectory is not None  # not dropped
    assert trajectory.subagent_trajectories is not None
    ids = {sub.trajectory_id for sub in trajectory.subagent_trajectories}
    assert ids == {
        f"{_PARENT_UUID}/agent-explore01",
        f"{other_uuid}/agent-explore01",
    }


def _find_ref_trajectory_ids(trajectory) -> list[str]:
    """Collect every subagent_trajectory_ref.trajectory_id across all steps."""
    found: list[str] = []
    for step in trajectory.steps:
        if step.observation is None:
            continue
        for result in step.observation.results:
            for ref in result.subagent_trajectory_ref or []:
                if ref.trajectory_id is not None:
                    found.append(ref.trajectory_id)
    return found


def test_subagent_ref_links_to_parent_agent_step(tmp_path: Path) -> None:
    agent = ClaudeCode(logs_dir=tmp_path, model_name="claude-opus-4-8")
    session_dir = _build_session(
        tmp_path,
        subagent_events=_subagent_events(),
        meta={
            "agentType": "Explore",
            "toolUseId": _TOOL_USE_ID,
            "spawnDepth": 1,
        },
    )

    trajectory = agent._convert_events_to_trajectory(session_dir)

    assert trajectory is not None
    # The dispatch step (tool_call_id == meta.toolUseId) carries a ref to the
    # embedded subagent's trajectory_id.
    linked_step = next(
        step
        for step in trajectory.steps
        if step.tool_calls
        and any(tc.tool_call_id == _TOOL_USE_ID for tc in step.tool_calls)
    )
    assert linked_step.observation is not None
    matching = [
        ref
        for result in linked_step.observation.results
        if result.source_call_id == _TOOL_USE_ID
        for ref in result.subagent_trajectory_ref or []
    ]
    assert [ref.trajectory_id for ref in matching] == [f"{_PARENT_UUID}/agent-explore01"]


def test_dispatch_without_observation_link_is_skipped(tmp_path: Path) -> None:
    agent = ClaudeCode(logs_dir=tmp_path, model_name="claude-opus-4-8")
    # A dispatch step that yields NO observation (a bare tool_use with no
    # message id and no tool_result -> the converter emits a kind="tool_call"
    # step with observation=None). Linking must hit the `step.observation is
    # None` guard and silently no-op (no exception, no ref).
    session_dir = tmp_path / "projects" / "-app"
    _write_jsonl(
        session_dir / f"{_PARENT_UUID}.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": "2026-06-24T00:00:01Z",
                "sessionId": "sess-parent",
                "version": "1.2.3",
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-4-8",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": _TOOL_USE_ID,
                            "name": "Task",
                            "input": {"subagent_type": "Explore"},
                        }
                    ],
                },
            }
        ],
    )
    sub_dir = session_dir / _PARENT_UUID / "subagents"
    _write_jsonl(sub_dir / "agent-explore01.jsonl", _subagent_events())
    (sub_dir / "agent-explore01.meta.json").write_text(
        json.dumps({"agentType": "Explore", "toolUseId": _TOOL_USE_ID, "spawnDepth": 1}),
        encoding="utf-8",
    )

    trajectory = agent._convert_events_to_trajectory(session_dir)

    assert trajectory is not None
    # The dispatch step has no observation...
    dispatch_steps = [
        step
        for step in trajectory.steps
        if step.tool_calls
        and any(tc.tool_call_id == _TOOL_USE_ID for tc in step.tool_calls)
    ]
    assert dispatch_steps and all(step.observation is None for step in dispatch_steps)
    # The subagent is still embedded (discovery is independent of linking)...
    assert trajectory.subagent_trajectories is not None
    assert len(trajectory.subagent_trajectories) == 1
    # ...but the guard prevents any ref from being attached.
    assert _find_ref_trajectory_ids(trajectory) == []
