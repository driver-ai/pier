"""Tests for the evidence-mode ref-based enriched-trajectory endpoint (Plan 06).

`GET /api/evidence/trajectory?record_id=<id>&kind=<consumer|producer>` resolves
the Plan 05 envelope sidecar BY REF through the canonical chain
(`run_records.json[record_id]` -> `traces/index.json[ref]` -> sidecar path),
NOT via pier's `{job}/{trial}/agent/trajectory.json` route.

The fixture run ROOT is built from a REAL Plan 05 emission slice
(`tests/fixtures/enriched_trajectory/evidence_slice.json`, extracted from
`captured-trials/frontier-evidence-0702`) so the on-disk layout mirrors real
output. On top of the real slice the builder injects two contract-exercising
shapes that the real sample lacks:

* a non-identity pts->sealed ``aliases`` entry (the real sample's aliases are
  all identity), plus a record whose producer ref is that alias key, and
* a record whose non-null producer ref is DANGLING (present in run_records but
  absent from ``traces/index.json`` / its sidecar), to assert the distinct
  error contract.

Contract under test (see plan 06 "Producer resolution" + "Signature-drift note"):
null producer ref -> null body (200); non-null ref with a missing sidecar ->
a DISTINCT error (HTTP 500), never a silent null and never a plain 404.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from pier.viewer.server import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "enriched_trajectory" / "evidence_slice.json"

# Record tags from the real slice.
DP = "dp"  # driver_production MCQ: non-null producer ref, consumer + producer sidecars
CL = "cl"  # b0 cloze: null producer ref, abstained
CM = "cm"  # b0 claim: null producer ref, not abstained

# Synthetic (contract-exercising) additions layered onto the real slice.
ALIAS_PTS_REF = "gather:frontier-0702:claude-haiku-4-5-20251001:pts_driver_production:0"
DANGLING_REF = "gather:frontier-0702:claude-haiku-4-5-20251001:driver_production:404"


def _build_run_root(root: Path) -> Path:
    """Materialize the evidence run root (run_records.json + traces/) from the slice.

    The slice carries {records: {tag: run_record}, sidecars: {"consumer:tag"|
    "producer:tag": envelope}, run_id}. We write each sidecar under
    traces/<model>/... and index it in traces/index.json by its own ``ref``.
    Then we inject the alias record + the dangling record.
    """
    slice_data = json.loads(FIXTURE.read_text())
    records = dict(slice_data["records"])
    sidecars = slice_data["sidecars"]
    run_id = slice_data["run_id"]

    traces = root / "traces"
    traces.mkdir(parents=True)

    refs: dict[str, str] = {}
    aliases: dict[str, str] = {}

    # Write every real sidecar keyed by its own envelope ref.
    for key, env in sidecars.items():
        ref = env["ref"]
        # Give each sidecar a stable relative path under traces/.
        rel = f"{key.replace(':', '__')}.json"
        (traces / rel).write_text(json.dumps(env))
        refs[ref] = rel
        # Real emission records every gather ref as an explicit (identity) alias.
        if env.get("kind") == "gather":
            aliases[ref] = ref

    # --- Contract injection 1: non-identity pts->sealed alias ---
    # The producer (gather) ref is exam-invariant, so a pts producer ref must
    # resolve, via an alias, to the SAME sealed gather sidecar. Point a distinct
    # pts alias key at the real driver_production gather ref.
    real_gather_ref = records[DP]["producer_trajectory_ref"]
    aliases[ALIAS_PTS_REF] = real_gather_ref
    # A record whose producer ref is the alias key (not directly in refs).
    dp_alias = dict(records[DP])
    dp_alias["record_id"] = records[DP]["record_id"] + ":ptsalias"
    dp_alias["consumer_trajectory_ref"] = dp_alias["record_id"]
    dp_alias["exam_mode"] = "pts"
    dp_alias["producer_trajectory_ref"] = ALIAS_PTS_REF
    # Its consumer sidecar reuses the dp consumer envelope path (index it).
    dp_consumer_env = sidecars["consumer:dp"]
    dp_alias_consumer_env = dict(dp_consumer_env)
    dp_alias_consumer_env["ref"] = dp_alias["consumer_trajectory_ref"]
    dp_alias_rel = "consumer__dp__ptsalias.json"
    (traces / dp_alias_rel).write_text(json.dumps(dp_alias_consumer_env))
    refs[dp_alias["consumer_trajectory_ref"]] = dp_alias_rel

    # --- Contract injection 2: dangling producer ref (non-null, no sidecar) ---
    dangling = dict(records[DP])
    dangling["record_id"] = records[DP]["record_id"] + ":dangling"
    dangling["consumer_trajectory_ref"] = dangling["record_id"]
    dangling["producer_trajectory_ref"] = DANGLING_REF  # NOT in refs / no file
    dangling_consumer_env = dict(dp_consumer_env)
    dangling_consumer_env["ref"] = dangling["consumer_trajectory_ref"]
    dangling_rel = "consumer__dp__dangling.json"
    (traces / dangling_rel).write_text(json.dumps(dangling_consumer_env))
    refs[dangling["consumer_trajectory_ref"]] = dangling_rel

    (traces / "index.json").write_text(json.dumps({"refs": refs, "aliases": aliases}))

    all_records = list(records.values()) + [dp_alias, dangling]
    (root / "run_records.json").write_text(
        json.dumps({"run_id": run_id, "records": all_records})
    )
    return root


def _rid(tag: str) -> str:
    return json.loads(FIXTURE.read_text())["records"][tag]["record_id"]


def test_get_enriched_trajectory_by_ref(tmp_path):
    run_root = _build_run_root(tmp_path)
    client = TestClient(create_app(run_root, mode="evidence"))

    # --- consumer envelope resolves by ref ---
    resp = client.get(
        "/api/evidence/trajectory", params={"record_id": _rid(DP), "kind": "consumer"}
    )
    assert resp.status_code == 200
    env = resp.json()
    assert env is not None
    # Plan 05 envelope shape: trajectory + enrichment + panels.
    assert set(["trajectory", "enrichment", "panels"]).issubset(env.keys())
    assert env["kind"] == "consumer"
    assert isinstance(env["trajectory"], dict)
    assert isinstance(env["enrichment"], dict)
    # Consumer envelope has no gather panels.
    assert env["panels"] is None

    # --- producer (gather) envelope on a driver_production record ---
    resp = client.get(
        "/api/evidence/trajectory", params={"record_id": _rid(DP), "kind": "producer"}
    )
    assert resp.status_code == 200
    penv = resp.json()
    assert penv is not None
    assert penv["kind"] == "gather"
    # Gather panels are non-null (channel_mix/tiers/coverage/off_gold).
    assert penv["panels"] is not None
    assert "channel_mix" in penv["panels"]

    # --- kind defaults to consumer ---
    resp = client.get("/api/evidence/trajectory", params={"record_id": _rid(DP)})
    assert resp.status_code == 200
    assert resp.json()["kind"] == "consumer"

    # --- pts->sealed alias is followed: pts producer ref resolves to the
    #     SAME sealed gather sidecar ---
    resp = client.get(
        "/api/evidence/trajectory",
        params={"record_id": _rid(DP) + ":ptsalias", "kind": "producer"},
    )
    assert resp.status_code == 200
    alias_env = resp.json()
    assert alias_env is not None
    # Resolves to the real sealed gather envelope (same ref as DP's producer).
    assert alias_env["ref"] == json.loads(FIXTURE.read_text())["records"][DP][
        "producer_trajectory_ref"
    ]
    assert alias_env["kind"] == "gather"

    # --- null producer ref (b0 / oracle) -> null BODY, not an error ---
    for tag in (CL, CM):
        resp = client.get(
            "/api/evidence/trajectory",
            params={"record_id": _rid(tag), "kind": "producer"},
        )
        assert resp.status_code == 200, tag
        assert resp.json() is None, tag
    # b0 consumer ref is always present and resolves.
    resp = client.get(
        "/api/evidence/trajectory", params={"record_id": _rid(CL), "kind": "consumer"}
    )
    assert resp.status_code == 200
    assert resp.json() is not None

    # --- dangling producer ref (non-null, sidecar absent) -> DISTINCT error ---
    resp = client.get(
        "/api/evidence/trajectory",
        params={"record_id": _rid(DP) + ":dangling", "kind": "producer"},
    )
    # Distinct from the null-producer case: NOT 200/null, NOT a plain 404.
    assert resp.status_code == 500
    assert resp.status_code != 200
    # The error is distinguishable (explicit sidecar/ref detail).
    assert "sidecar" in resp.json()["detail"].lower() or "ref" in resp.json()["detail"].lower()

    # --- unknown record_id -> 404 (record itself missing, distinct from dangling) ---
    resp = client.get(
        "/api/evidence/trajectory",
        params={"record_id": "does-not-exist", "kind": "consumer"},
    )
    assert resp.status_code == 404


def test_get_enriched_trajectory_by_direct_ref(tmp_path):
    """`?ref=<gather_ref>` resolves a trace ref DIRECTLY (no consumer record).

    This is the standalone-gather view: a gather can be inspected without any
    run_records join row. Aliases are honored; a dangling ref -> the same
    distinct error (500) as the record_id path.
    """
    run_root = _build_run_root(tmp_path)
    client = TestClient(create_app(run_root, mode="evidence"))

    # The real slice's driver_production producer ref is a gather.
    gather_ref = json.loads(FIXTURE.read_text())["records"][DP][
        "producer_trajectory_ref"
    ]

    # Direct ref -> that gather's envelope (no record_id needed).
    resp = client.get("/api/evidence/trajectory", params={"ref": gather_ref})
    assert resp.status_code == 200
    env = resp.json()
    assert env is not None
    assert env["ref"] == gather_ref
    assert env["kind"] == "gather"
    assert env["panels"] is not None

    # An alias key resolves through aliases to the SAME sealed sidecar.
    resp = client.get("/api/evidence/trajectory", params={"ref": ALIAS_PTS_REF})
    assert resp.status_code == 200
    assert resp.json()["ref"] == gather_ref

    # A dangling ref (non-null, no sidecar entry) -> distinct error (500).
    resp = client.get("/api/evidence/trajectory", params={"ref": DANGLING_REF})
    assert resp.status_code == 500
    assert "sidecar" in resp.json()["detail"].lower() or "ref" in resp.json()["detail"].lower()

    # Neither record_id nor ref -> bad request.
    resp = client.get("/api/evidence/trajectory")
    assert resp.status_code == 400

    # record_id path still works unchanged alongside the new ref path.
    resp = client.get(
        "/api/evidence/trajectory", params={"record_id": _rid(DP), "kind": "consumer"}
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] == "consumer"


def test_run_records_forensics_shape(tmp_path):
    """`/api/run-records` records carry typed forensics (display + payload).

    Pulls REAL examples from the emitted slice: at least one mcq (options in
    payload) and one cloze (gold + accept_set), plus an abstained example.
    """
    run_root = _build_run_root(tmp_path)
    client = TestClient(create_app(run_root, mode="evidence"))

    resp = client.get("/api/run-records")
    assert resp.status_code == 200
    records = resp.json()
    by_id = {r["record_id"]: r for r in records}

    # Every forensics-bearing record has the normalized display block.
    for r in records:
        f = r.get("forensics")
        if f is None:
            continue
        disp = f["display"]
        assert set(["question", "answer", "expected", "passed"]).issubset(disp.keys())
        assert isinstance(f["payload"], dict)

    # MCQ: typed payload carries options.
    mcq = by_id[_rid(DP)]
    assert mcq["forensics"]["exam_type"] == "mcq"
    assert "options" in mcq["forensics"]["payload"]
    assert isinstance(mcq["forensics"]["payload"]["options"], list)

    # Cloze: typed payload carries gold + accept_set.
    cloze = by_id[_rid(CL)]
    assert cloze["forensics"]["exam_type"] == "cloze"
    assert "gold" in cloze["forensics"]["payload"]
    assert "accept_set" in cloze["forensics"]["payload"]

    # Abstained example is present and flagged (real cloze b0 abstention).
    assert cloze["abstained"] is True

    # A non-abstained example with a passed verdict in display.
    claim = by_id[_rid(CM)]
    assert claim["abstained"] is False
    assert claim["forensics"]["display"]["passed"] in (True, False)
