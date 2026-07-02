"""Tests for the evidence-mode /api/data-notes endpoint (Plan 07, Task 7).

Mirrors the {run_id, notes} envelope emitted by pier-analytics (Plan 07a,
data_notes.json at the evidence run root). Follows the harness + envelope-404
pattern of test_evidence_endpoints.py: an absent / malformed / missing-key
sidecar collapses to 404 (never 500).
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from pier.viewer.server import create_app

# Copies the real emit shape from
# ~/work/driver/driver-ai/captured-trials/frontier-evidence-0702/data_notes.json
NOTES = [
    {
        "id": "L-01",
        "title": "Read-classification hygiene",
        "description": (
            "Failed reads, session-scratch re-reads (paths under "
            "/logs/agent/sessions/), and bare /app dir reads were previously "
            "counted as gathered content, inflating coverage, off-gold reads, "
            "and injected tokens. These reads are now excluded at build time by "
            "a single is_context_read predicate (resolved 2026-07-02)."
        ),
        "affects": ["coverage", "off_gold", "injected_tokens"],
    }
]


def _make_evidence_dir(root: Path) -> Path:
    (root / "data_notes.json").write_text(
        json.dumps({"run_id": "run1", "notes": NOTES})
    )
    return root


def test_get_data_notes(tmp_path):
    evidence = _make_evidence_dir(tmp_path)
    client = TestClient(create_app(evidence, mode="evidence"))

    resp = client.get("/api/data-notes")
    assert resp.status_code == 200
    data = resp.json()
    # Inner list is returned (not the envelope).
    assert len(data) == 1
    note = data[0]
    assert note["id"] == "L-01"
    assert note["title"] == "Read-classification hygiene"
    assert note["affects"] == ["coverage", "off_gold", "injected_tokens"]

    # Absent sidecar -> 404 (not 500).
    absent = tmp_path / "absent"
    absent.mkdir()
    assert (
        TestClient(create_app(absent, mode="evidence"))
        .get("/api/data-notes")
        .status_code
        == 404
    )

    # Malformed sidecar -> 404 (not 500).
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "data_notes.json").write_text("{ not valid json")
    assert (
        TestClient(create_app(malformed, mode="evidence"))
        .get("/api/data-notes")
        .status_code
        == 404
    )

    # File present but missing the inner "notes" key -> 404.
    no_key = tmp_path / "no_key"
    no_key.mkdir()
    (no_key / "data_notes.json").write_text(json.dumps({"run_id": "run1"}))
    assert (
        TestClient(create_app(no_key, mode="evidence"))
        .get("/api/data-notes")
        .status_code
        == 404
    )
