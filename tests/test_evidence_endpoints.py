"""Tests for the evidence-mode data endpoints: /api/condition-aggregates + /api/run-records.

Net-new TestClient harness (pier has no existing viewer/endpoint tests). Fixtures
mirror the ACTUAL emit shapes from pier-analytics
(experiments/frontier/emit.py + summary.Stat): the {run_id, aggregates|records}
envelope, nested quality/cost `Stat` objects, and `record_id` + nested `forensics`
on records.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from pier.viewer.server import create_app


def _stat(mean: float, n: int) -> dict:
    """A pier-analytics summary.Stat dict (mean/median/std/n/min/max)."""
    return {
        "mean": mean,
        "median": mean,
        "std": 0.0,
        "n": n,
        "min": mean,
        "max": mean,
    }


AGGREGATES = [
    {
        "condition": "b0",
        "model": "sonnet",
        "exam_mode": "sealed",
        "quality": _stat(0.2, 10),
        "ci_low": 0.1,
        "ci_high": 0.3,
        "lift_vs_b0": None,
        "span_pos": None,
        "cost_gather": None,
        "cost_consumer": _stat(0.01, 10),
        "cost_total": None,
        "abstain_rate": 0.0,
        "n": 10,
    },
    {
        "condition": "driver_production",
        "model": "sonnet",
        "exam_mode": "sealed",
        "quality": _stat(0.6, 10),
        "ci_low": 0.5,
        "ci_high": 0.7,
        "lift_vs_b0": 0.4,
        "span_pos": 0.5,
        "cost_gather": _stat(0.05, 10),
        "cost_consumer": _stat(0.01, 10),
        "cost_total": _stat(0.06, 10),
        "abstain_rate": 0.1,
        "n": 10,
    },
]

RECORDS = [
    {
        "record_id": "consumer:run1:sealed:sonnet:driver_production:item1:0",
        "run_id": "run1",
        "item_id": "item1",
        "condition": "driver_production",
        "model": "sonnet",
        "exam_mode": "sealed",
        "seed": 0,
        "score": 1.0,
        "abstained": False,
        "exam_type": "mcq",
        "cost_gather_usd": 0.05,
        "cost_consumer_usd": 0.01,
        "tokens_gather": 1000,
        "tokens_consumer": 200,
        "n_required": 4,
        "n_covered": 3,
        "coverage": 0.75,
        "producer_trajectory_ref": "gather:run1:sonnet:driver_production:0",
        "consumer_trajectory_ref": "consumer:run1:sealed:sonnet:driver_production:item1:0",
        "forensics": {
            "exam_type": "mcq",
            "payload": {"options": ["a", "b"], "is_gold": [False, True]},
            "display": {
                "question": "Which one?",
                "answer": "b",
                "expected": "b",
                "passed": True,
            },
        },
    },
    {
        "record_id": "consumer:run1:sealed:sonnet:b0:item1:0",
        "run_id": "run1",
        "item_id": "item1",
        "condition": "b0",
        "model": "sonnet",
        "exam_mode": "sealed",
        "seed": None,
        "score": 0.0,
        "abstained": True,
        "exam_type": "mcq",
        "cost_gather_usd": None,
        "cost_consumer_usd": 0.01,
        "tokens_gather": None,
        "tokens_consumer": 200,
        "n_required": None,
        "n_covered": None,
        "coverage": None,
        "producer_trajectory_ref": None,
        "consumer_trajectory_ref": "consumer:run1:sealed:sonnet:b0:item1:0",
        "forensics": None,
    },
]


def _make_evidence_dir(root: Path) -> Path:
    """Write the two Plan 03 sidecars in their {run_id, aggregates|records} envelope."""
    (root / "condition_aggregates.json").write_text(
        json.dumps({"run_id": "run1", "aggregates": AGGREGATES})
    )
    (root / "run_records.json").write_text(
        json.dumps({"run_id": "run1", "records": RECORDS})
    )
    return root


def test_get_condition_aggregates(tmp_path):
    evidence = _make_evidence_dir(tmp_path)
    client = TestClient(create_app(evidence, mode="evidence"))

    resp = client.get("/api/condition-aggregates")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    b0, driver = data
    # Inner list is returned (not the envelope).
    assert b0["condition"] == "b0"
    assert driver["condition"] == "driver_production"

    # quality stays NESTED as a Stat (not flattened).
    assert driver["quality"]["mean"] == 0.6
    assert driver["quality"]["n"] == 10
    assert set(driver["quality"].keys()) == {"mean", "median", "std", "n", "min", "max"}

    # cost fields are nested Stats or null.
    assert driver["cost_total"]["mean"] == 0.06
    assert b0["cost_gather"] is None
    assert b0["quality"]["mean"] == 0.2

    # scalar fields.
    assert driver["lift_vs_b0"] == 0.4
    assert driver["span_pos"] == 0.5
    assert b0["lift_vs_b0"] is None
    assert driver["abstain_rate"] == 0.1
    assert driver["n"] == 10

    # Absent sidecar -> 404 (not 500).
    absent = tmp_path / "absent"
    absent.mkdir()
    assert (
        TestClient(create_app(absent, mode="evidence"))
        .get("/api/condition-aggregates")
        .status_code
        == 404
    )

    # Malformed sidecar -> 404 (not 500).
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "condition_aggregates.json").write_text("{ not valid json")
    assert (
        TestClient(create_app(malformed, mode="evidence"))
        .get("/api/condition-aggregates")
        .status_code
        == 404
    )

    # File present but missing the inner "aggregates" key -> 404.
    no_key = tmp_path / "no_key"
    no_key.mkdir()
    (no_key / "condition_aggregates.json").write_text(json.dumps({"run_id": "run1"}))
    assert (
        TestClient(create_app(no_key, mode="evidence"))
        .get("/api/condition-aggregates")
        .status_code
        == 404
    )


def test_get_run_records(tmp_path):
    evidence = _make_evidence_dir(tmp_path)
    client = TestClient(create_app(evidence, mode="evidence"))

    resp = client.get("/api/run-records")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    driver, b0 = data
    # Inner list is returned (not the envelope). record_id present.
    assert driver["record_id"] == "consumer:run1:sealed:sonnet:driver_production:item1:0"
    assert driver["consumer_trajectory_ref"] == driver["record_id"]
    assert driver["score"] == 1.0
    assert driver["coverage"] == 0.75

    # forensics is nested (exam_type + permissive payload + display) or null.
    assert driver["forensics"]["exam_type"] == "mcq"
    assert driver["forensics"]["payload"]["is_gold"] == [False, True]
    assert driver["forensics"]["display"]["passed"] is True

    # b0 rail: null gather fields + null forensics + null seed.
    assert b0["condition"] == "b0"
    assert b0["seed"] is None
    assert b0["producer_trajectory_ref"] is None
    assert b0["cost_gather_usd"] is None
    assert b0["forensics"] is None
    assert b0["abstained"] is True

    # Absent sidecar -> 404 (not 500).
    absent = tmp_path / "absent_rr"
    absent.mkdir()
    assert (
        TestClient(create_app(absent, mode="evidence"))
        .get("/api/run-records")
        .status_code
        == 404
    )

    # Malformed sidecar -> 404 (not 500).
    malformed = tmp_path / "malformed_rr"
    malformed.mkdir()
    (malformed / "run_records.json").write_text("{ not valid json")
    assert (
        TestClient(create_app(malformed, mode="evidence"))
        .get("/api/run-records")
        .status_code
        == 404
    )

    # File present but missing the inner "records" key -> 404.
    no_key = tmp_path / "no_key_rr"
    no_key.mkdir()
    (no_key / "run_records.json").write_text(json.dumps({"run_id": "run1"}))
    assert (
        TestClient(create_app(no_key, mode="evidence"))
        .get("/api/run-records")
        .status_code
        == 404
    )
