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
    _write_jsonl(session_dir / f"{_PARENT_UUID}.jsonl", _parent_events(with_dispatch=with_dispatch))

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
    assert sub.trajectory_id == "agent-explore01"
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
