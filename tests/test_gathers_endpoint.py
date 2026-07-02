"""Tests for the evidence-mode /api/gathers list endpoint (Trajectories browser).

`GET /api/gathers` enumerates the distinct ``gather:`` refs in
``traces/index.json`` and returns one row per distinct gather, each carrying
``{ref, model, condition, seed, mean_coverage, cost_usd}``. ``model``/
``condition``/``seed`` are parsed positionally from the ref
(``gather:{run_id}:{model}:{condition}:{seed}``); ``mean_coverage`` and
``cost_usd`` come from the sidecar's ``panels.coverage.mean_coverage`` and
``panels.channel_mix.total_cost_usd`` (null-tolerant).

The fixture is a small REAL slice: two real gather sidecars copied from
``captured-trials/frontier-evidence-0702`` plus a hand-built ``traces/index.json``
indexing their ``gather:`` refs, so the on-disk layout mirrors real output.

Empty/absent behavior returns ``[]`` (a run with no gathers is valid), NOT 404.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from pier.viewer.server import create_app

# Two real gather refs + their sidecar relative paths (under traces/).
GATHER_A_REF = "gather:frontier-0702:claude-haiku-4-5-20251001:driver_production:0"
GATHER_A_REL = "claude-haiku-4-5-20251001/gather/driver_production-0.json"
GATHER_B_REF = "gather:frontier-0702:claude-haiku-4-5-20251001:explore:0"
GATHER_B_REL = "claude-haiku-4-5-20251001/gather/explore-0.json"

# A minimal real-shaped gather sidecar envelope (Plan 05): the fields the
# endpoint reads are panels.coverage.mean_coverage + panels.channel_mix.total_cost_usd.
def _gather_envelope(ref: str, mean_coverage, total_cost_usd) -> dict:
    return {
        "ref": ref,
        "kind": "gather",
        "trajectory": {"steps": []},
        "enrichment": {},
        "panels": {
            "channel_mix": {
                "channels": {},
                "total_tokens": 0,
                "total_cost_usd": total_cost_usd,
                "total_seconds": 0.0,
            },
            "tiers": {},
            "coverage": {"mean_coverage": mean_coverage, "systematic_misses": []},
            "off_gold": [],
        },
    }


def _build_run_root(root: Path) -> Path:
    traces = root / "traces"
    (traces / "claude-haiku-4-5-20251001" / "gather").mkdir(parents=True)

    (traces / GATHER_A_REL).write_text(
        json.dumps(_gather_envelope(GATHER_A_REF, 0.15384615384615385, 0.21935095))
    )
    (traces / GATHER_B_REL).write_text(
        json.dumps(_gather_envelope(GATHER_B_REF, 0.5, 0.04))
    )

    # A non-gather ref (consumer) must be ignored by /api/gathers.
    consumer_rel = "consumer.json"
    (traces / consumer_rel).write_text(
        json.dumps({"ref": "consumer:run1:x", "kind": "consumer", "panels": None})
    )

    index = {
        "refs": {
            GATHER_A_REF: GATHER_A_REL,
            GATHER_B_REF: GATHER_B_REL,
            "consumer:run1:x": consumer_rel,
        },
        # Real emission records every gather ref as an (identity) alias.
        "aliases": {GATHER_A_REF: GATHER_A_REF, GATHER_B_REF: GATHER_B_REF},
    }
    (traces / "index.json").write_text(json.dumps(index))
    return root


def test_get_gathers_list(tmp_path):
    run_root = _build_run_root(tmp_path)
    client = TestClient(create_app(run_root, mode="evidence"))

    resp = client.get("/api/gathers")
    assert resp.status_code == 200
    rows = resp.json()

    # One row per distinct gather ref; the consumer ref is excluded.
    assert len(rows) == 2
    by_ref = {r["ref"]: r for r in rows}
    assert set(by_ref) == {GATHER_A_REF, GATHER_B_REF}

    a = by_ref[GATHER_A_REF]
    # Fields parsed positionally from gather:{run_id}:{model}:{condition}:{seed}.
    assert a["model"] == "claude-haiku-4-5-20251001"
    assert a["condition"] == "driver_production"
    assert a["seed"] == 0
    # Read from the sidecar panels.
    assert a["mean_coverage"] == 0.15384615384615385
    assert a["cost_usd"] == 0.21935095

    b = by_ref[GATHER_B_REF]
    assert b["condition"] == "explore"
    assert b["mean_coverage"] == 0.5
    assert b["cost_usd"] == 0.04


def test_get_gathers_null_tolerant(tmp_path):
    """A gather whose sidecar lacks coverage/cost yields null fields (not 500)."""
    traces = tmp_path / "traces"
    (traces / "claude-sonnet-4-6" / "gather").mkdir(parents=True)
    ref = "gather:r1:claude-sonnet-4-6:explore:2"
    rel = "claude-sonnet-4-6/gather/explore-2.json"
    # Sidecar with empty panels (no coverage/channel_mix).
    (traces / rel).write_text(
        json.dumps({"ref": ref, "kind": "gather", "panels": {}})
    )
    (traces / "index.json").write_text(
        json.dumps({"refs": {ref: rel}, "aliases": {}})
    )

    client = TestClient(create_app(tmp_path, mode="evidence"))
    resp = client.get("/api/gathers")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["ref"] == ref
    assert row["model"] == "claude-sonnet-4-6"
    assert row["condition"] == "explore"
    assert row["seed"] == 2
    assert row["mean_coverage"] is None
    assert row["cost_usd"] is None


def test_get_gathers_empty_when_no_gathers(tmp_path):
    """No traces index / no gather refs -> [] (a run with no gathers is valid)."""
    # No traces/ dir at all.
    client = TestClient(create_app(tmp_path, mode="evidence"))
    assert client.get("/api/gathers").json() == []
    assert client.get("/api/gathers").status_code == 200

    # traces/index.json present but with no gather: refs.
    traces = tmp_path / "traces"
    traces.mkdir()
    (traces / "index.json").write_text(
        json.dumps({"refs": {"consumer:r1:x": "c.json"}, "aliases": {}})
    )
    resp = client.get("/api/gathers")
    assert resp.status_code == 200
    assert resp.json() == []
