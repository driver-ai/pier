"""Tests for the evidence viewer mode: folder detection + /api/conditions."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pier.cli.view import _detect_folder_type
from pier.viewer.server import create_app

SIX_CONDITIONS = [
    {
        "id": "b0",
        "label": "No context",
        "description": "Model answers from priors alone — the floor.",
        "is_rail": True,
        "role": "floor",
        "order": 0,
    },
    {
        "id": "explore",
        "label": "Explore agent",
        "description": "General explore agent builds its own context nugget, however it sees fit.",
        "is_rail": False,
        "role": "competitor",
        "order": 1,
    },
    {
        "id": "explore_gtcflow",
        "label": "Explore, GTC-shaped",
        "description": "Explore agent prompted to imitate Driver's GTC flow (incl. proxy deep-context guidance).",
        "is_rail": False,
        "role": "competitor",
        "order": 2,
    },
    {
        "id": "driver_production",
        "label": "Driver (production)",
        "description": "Driver as deployed in production today.",
        "is_rail": False,
        "role": "competitor",
        "order": 3,
    },
    {
        "id": "gtc_native_v3g",
        "label": "Driver v3g (next)",
        "description": "Daniel's updated context substrate — non-obvious, interconnected context.",
        "is_rail": False,
        "role": "competitor",
        "order": 4,
    },
    {
        "id": "oracle_distilled",
        "label": "Oracle",
        "description": "Distilled gold context injected directly — the ceiling.",
        "is_rail": True,
        "role": "ceiling",
        "order": 5,
    },
]


def _make_evidence_dir(root: Path) -> Path:
    """Create a flat sidecar evidence layout at the root."""
    (root / "conditions.json").write_text(json.dumps(SIX_CONDITIONS))
    (root / "run_records.json").write_text(json.dumps([]))
    (root / "condition_aggregates.json").write_text(json.dumps({}))
    (root / "traces").mkdir()
    return root


def _make_jobs_dir(root: Path) -> Path:
    """Create a jobs layout (subdir with config.json)."""
    job = root / "job-001"
    job.mkdir()
    (job / "config.json").write_text(json.dumps({}))
    return root


def _make_tasks_dir(root: Path) -> Path:
    """Create a tasks layout (subdir with task.toml)."""
    task = root / "task-001"
    task.mkdir()
    (task / "task.toml").write_text("")
    return root


def test_detect_folder_type_evidence(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    _make_evidence_dir(evidence)
    assert _detect_folder_type(evidence) == "evidence"

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    _make_jobs_dir(jobs)
    assert _detect_folder_type(jobs) == "jobs"

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    _make_tasks_dir(tasks)
    assert _detect_folder_type(tasks) == "tasks"

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SystemExit):
        _detect_folder_type(empty)


def test_config_reports_evidence_mode(tmp_path):
    evidence = _make_evidence_dir(tmp_path)
    app = create_app(evidence, mode="evidence")
    client = TestClient(app)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json()["mode"] == "evidence"


def test_get_conditions_reads_config(tmp_path):
    evidence = _make_evidence_dir(tmp_path)
    app = create_app(evidence, mode="evidence")
    client = TestClient(app)

    resp = client.get("/api/conditions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 6
    assert data[0]["id"] == "b0"

    # Absent conditions.json -> 404
    absent = tmp_path / "absent"
    absent.mkdir()
    (absent / "traces").mkdir()
    app_absent = create_app(absent, mode="evidence")
    client_absent = TestClient(app_absent)
    assert client_absent.get("/api/conditions").status_code == 404

    # Malformed conditions.json -> 404 (not 500)
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "conditions.json").write_text("{ this is not valid json")
    app_malformed = create_app(malformed, mode="evidence")
    client_malformed = TestClient(app_malformed)
    assert client_malformed.get("/api/conditions").status_code == 404


def test_conditions_endpoint_shape(tmp_path):
    evidence = _make_evidence_dir(tmp_path)
    app = create_app(evidence, mode="evidence")
    client = TestClient(app)

    resp = client.get("/api/conditions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 6
    for item in data:
        assert set(item.keys()) == {
            "id",
            "label",
            "description",
            "is_rail",
            "role",
            "order",
        }
        assert isinstance(item["id"], str)
        assert isinstance(item["label"], str)
        assert isinstance(item["description"], str)
        assert isinstance(item["is_rail"], bool)
        assert isinstance(item["role"], str)
        assert isinstance(item["order"], int)
