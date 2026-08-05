"""The per-member breakdown: `totals.lineage_count` and the `lineages` map beside it.

Design section 3.1 as amended by 13.1.1. Two rules do most of the work here, and both are
about what is *not* said:

* the untagged bucket is a member — it is why a half-tagged document is multi-lineage at
  all — but it is not a lineage, so it is in neither the count nor the map. Counting it
  reported four members for the canonical three-replica campaign, which is the miscount the
  membership predicate exists to prevent, arriving through the totals instead;
* both keys are emitted only when the document holds more than one member, so an untagged
  document's `summary.json` is the file it always was.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ambermeta.cli import main
from ambermeta.gui.api import routes
from ambermeta.protocol import auto_discover


def _client(base):
    routes.set_base_directory(str(base))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


# ---------------------------------------------------------------------------
# The core arithmetic
# ---------------------------------------------------------------------------

def test_three_replicas_are_counted_and_broken_down(replica_tree):
    protocol = auto_discover(str(replica_tree), manifest=None, recursive=True)
    assert protocol.totals()["lineage_count"] == 3
    breakdown = protocol.lineage_totals()
    assert sorted(breakdown) == ["rep1", "rep2", "rep3"]
    # Every member ran the same four runs, so the split is even and sums back to the whole.
    assert {v["step_count"] for v in breakdown.values()} == {4}
    assert sum(v["steps"] for v in breakdown.values()) == protocol.totals()["steps"]


def test_a_shared_prep_directory_is_a_member_but_not_a_lineage(campaign_tree):
    """The canonical campaign: `common/{min,heat,equil}` beside `rep1..3/prod_*`.

    Four membership buckets, three declared lineages. Reporting four here would hand
    `lineage_count` the prep runs as a replica — the exact claim the inference refuses to
    make one layer down.
    """
    protocol = auto_discover(str(campaign_tree), manifest=None, recursive=True)
    assert protocol.totals()["lineage_count"] == 3
    assert sorted(protocol.lineage_totals()) == ["rep1", "rep2", "rep3"]
    assert len(protocol._members()) == 4


def test_a_member_that_stopped_early_shows_its_own_shorter_total(crashed_replica_tree):
    """The breakdown says what one flat number cannot: rep2 ran a third of what its
    siblings ran. That is the finding, in the artifact, as a quantity."""
    breakdown = auto_discover(
        str(crashed_replica_tree), manifest=None, recursive=True).lineage_totals()
    assert breakdown["rep2"]["step_count"] == 1
    assert breakdown["rep1"]["step_count"] == 3
    assert breakdown["rep2"]["time_ps"] < breakdown["rep1"]["time_ps"]


def test_an_untagged_document_gets_neither_key(sample_md_data_dir):
    protocol = auto_discover(str(sample_md_data_dir), manifest=None, recursive=True)
    assert "lineage_count" not in protocol.totals()
    assert protocol.lineage_totals() == {}
    assert "lineages" not in protocol.to_dict()


# ---------------------------------------------------------------------------
# The artifact
# ---------------------------------------------------------------------------

def test_the_summary_carries_the_breakdown(replica_tree, tmp_path):
    out = tmp_path / "summary.json"
    assert main(["plan", "--recursive", str(replica_tree),
                 "--summary-path", str(out)]) == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["totals"]["lineage_count"] == 3
    assert sorted(summary["lineages"]) == ["rep1", "rep2", "rep3"]
    assert summary["lineages"]["rep1"]["step_count"] == 4


# ---------------------------------------------------------------------------
# The wire
# ---------------------------------------------------------------------------

def _discovered(client):
    assert client.post("/api/document/discover", json={"recursive": True}).status_code == 200


def test_validate_carries_the_breakdown(replica_tree):
    c = _client(replica_tree)
    _discovered(c)
    body = c.post("/api/validate").json()
    assert body["totals"]["lineage_count"] == 3.0    # a float map coerces; see below
    assert sorted(body["lineages"]) == ["rep1", "rep2", "rep3"]
    rep2 = body["lineages"]["rep2"]
    assert sorted(rep2) == ["step_count", "steps", "time_ps"]
    assert rep2["step_count"] == 4
    # The member's own share, not the document's: three identical members, so a third.
    assert rep2["time_ps"] == pytest.approx(body["totals"]["time_ps"] / 3)


def test_plan_carries_the_breakdown_and_still_returns_200(replica_tree, tmp_path):
    """`/api/plan` assembles its response *after* the files are written, so a shape the
    model rejects is an HTTP 500 over artifacts that already landed — and the response
    names none of them. That is why the breakdown sits beside `totals` and not inside it:
    `totals` is `Dict[str, float]` and a nested dict raises."""
    c = _client(replica_tree)
    _discovered(c)
    summary = tmp_path / "s.json"
    r = c.post("/api/plan", json={"summary_path": str(summary)})
    assert r.status_code == 200, r.text
    assert summary.exists()
    assert sorted(r.json()["lineages"]) == ["rep1", "rep2", "rep3"]


def test_an_untagged_document_reports_a_null_breakdown_on_the_wire(sample_md_data_dir):
    """Null, not absent. No route sets `exclude_none`, so an Optional field always
    serialises — the design's "absent entirely" is reachable only in `summary.json`, which
    is a plain dict. Saying so here keeps the two surfaces from being read as one."""
    c = _client(sample_md_data_dir)
    _discovered(c)
    body = c.post("/api/validate").json()
    assert "lineages" in body and body["lineages"] is None
    assert "lineage_count" not in body["totals"]


# ---------------------------------------------------------------------------
# The terminal
# ---------------------------------------------------------------------------

def test_the_breakdown_is_printed_by_plan_and_validate(
        crashed_replica_tree, tmp_path, capsys):
    """One number for a three-replica campaign answers a question nobody asked: 300 ns of
    *what*? The breakdown makes the crashed replica visible as a quantity, beside the
    finding that names it."""
    manifest = crashed_replica_tree / "manifest.yaml"
    assert main(["discover", str(crashed_replica_tree), "--write", str(manifest)]) == 0
    capsys.readouterr()

    assert main(["validate", "--manifest", str(manifest)]) == 0
    out = capsys.readouterr().out
    assert "Per lineage:" in out
    assert "rep2  1 run(s)" in out
    assert "rep1  3 run(s)" in out

    assert main(["plan", "--recursive", str(crashed_replica_tree)]) == 0
    scan = capsys.readouterr().out
    assert "Declared lineages: 3" in scan
    assert "rep2  1 run(s)" in scan


def test_discover_prints_which_runs_each_member_holds(crashed_replica_tree, capsys):
    """The count alone ("Runs carry 3 declared lineage(s)") says nothing about which runs
    it covers, and docs/cli.md already claimed the card names each member. The evidence is
    printed for this card and no other — appending it everywhere would dump role_guess's
    whole phase->role mapping into the same block."""
    assert main(["discover", "--recursive", str(crashed_replica_tree)]) == 0
    out = capsys.readouterr().out
    assert "Runs carry 3 declared lineage(s)" in out
    assert "rep1: 3 run(s); rep2: 1 run(s); rep3: 3 run(s)" in out
    assert "Equilibration->" not in out


def test_an_untagged_document_prints_no_lineage_chrome(sample_md_data_dir, capsys):
    assert main(["plan", "--recursive", str(sample_md_data_dir)]) == 0
    out = capsys.readouterr().out
    assert "Per lineage:" not in out
    assert "Declared lineages:" not in out
    assert "lineage=" not in out


def test_lineage_count_is_a_float_on_the_wire_and_an_int_in_the_artifact(replica_tree, tmp_path):
    """A wart, pinned rather than hidden: `totals` is `Dict[str, float]` on both models, so
    pydantic coerces the count to 3.0. `stage_count` has always arrived the same way. The
    artifact is a plain dict and is not bound by that — but `step_count` inside
    `LineageTotals` *is* declared an int, which is why the breakdown is its own model."""
    c = _client(replica_tree)
    _discovered(c)
    assert c.post("/api/validate").json()["totals"]["lineage_count"] == 3.0

    out = tmp_path / "summary.json"
    assert main(["plan", "--recursive", str(replica_tree), "--summary-path", str(out)]) == 0
    raw = out.read_text(encoding="utf-8")
    assert '"lineage_count": 3.0' in raw
    assert '"step_count": 4' in raw
