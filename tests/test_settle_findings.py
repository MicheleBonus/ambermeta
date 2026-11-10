"""Findings you can settle: an acknowledgement with a note, kept in the manifest.

From the workflow walk-through (`.claude/ux-audit/reports/2026-11-10-workflow.md`, C1):
a missing run, a replica that stopped early or an input that was not deposited could only
be dismissed in the GUI, which recorded nothing, and came straight back on the next
Validate, in `--strict` and in the methods summary. There was no way to say "I know, and
this is why".

An acknowledgement names the finding by its exact text (the `title: evidence` line that
`validate` prints) and carries a note. A finding whose text changes, because the data or
the wording did, is a new finding and shows again; an acknowledgement that matches nothing
any more is reported so it can be cleaned up. Acknowledged findings are listed apart with
their notes, do not fail `--strict`, and are carried into summary.json.
"""
from __future__ import annotations

import json

import pytest

from conftest import RunSpec, alternating_runs, md_mdin, write_run_tree

NOTE = "prod_0003 crashed on a node failure and was not deposited."


def _run(argv, capsys, monkeypatch):
    from ambermeta.cli import main

    monkeypatch.setenv("NO_COLOR", "1")
    try:
        rc = main(argv)
    except SystemExit as exc:
        rc = exc.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def _hole_tree(root):
    return write_run_tree(root, [
        (f"prod_{i:04d}", RunSpec(mdin=md_mdin("prod", 5000), elapsed_ps=10.0,
                                  begin_ps=10.0 * k))
        for k, i in enumerate((1, 2, 4))])


def _report(sim, base):
    from ambermeta.gui.api.core_bridge import validate_simulation
    return validate_simulation(sim, {}, str(base))


def _hole_finding(sim, base):
    from ambermeta.acknowledgements import finding_text

    [card] = [s for s in _report(sim, base)["suggestions"] if s["kind"] == "missing_run"]
    return finding_text(card)


@pytest.fixture
def hole(tmp_path):
    from ambermeta.gui.api.core_bridge import discover_draft

    tree = _hole_tree(tmp_path / "runs")
    sim = discover_draft(str(tree))["simulation"]
    return sim, tree


# --- the manifest ------------------------------------------------------------------------

def test_acknowledgements_round_trip_through_the_manifest(hole, tmp_path):
    pytest.importorskip("yaml")
    from ambermeta.simulation import Acknowledgement, load_simulation, write_simulation

    sim, _ = hole
    sim.acknowledged = [Acknowledgement(finding="prod run 3 is missing: x", note=NOTE)]
    path = tmp_path / "sim.yaml"
    write_simulation(sim, str(path), "yaml")
    assert load_simulation(str(path)).acknowledged == sim.acknowledged


def test_a_document_without_acknowledgements_writes_no_key(hole):
    from ambermeta.simulation import simulation_to_payload

    sim, _ = hole
    assert "acknowledged" not in simulation_to_payload(sim)


@pytest.mark.parametrize("entry, says", [
    ({"finding": "prod run 3 is missing: x"}, "needs a note"),
    ({"finding": "prod run 3 is missing: x", "note": "  "}, "needs a note"),
    ({"note": NOTE}, "names no finding"),
    ("just a string", "names no finding"),
])
def test_an_acknowledgement_without_a_finding_or_a_note_is_refused(entry, says):
    from ambermeta.errors import AmberMetaError
    from ambermeta.simulation import payload_to_simulation

    with pytest.raises(AmberMetaError, match=says):
        payload_to_simulation({"version": 2, "steps": [], "acknowledged": [entry]})


# --- validation --------------------------------------------------------------------------

def test_an_acknowledged_finding_is_marked_and_listed(hole):
    from ambermeta.simulation import Acknowledgement

    sim, tree = hole
    text = _hole_finding(sim, tree)
    sim.acknowledged = [Acknowledgement(finding=text, note=NOTE)]
    report = _report(sim, tree)
    [card] = [s for s in report["suggestions"] if s["kind"] == "missing_run"]
    assert card["acknowledged"] == NOTE
    assert report["acknowledged"] == [{"finding": text, "note": NOTE}]
    assert report["stale_acknowledgements"] == []


def test_an_acknowledgement_that_matches_nothing_is_reported_as_stale(hole):
    from ambermeta.simulation import Acknowledgement

    sim, tree = hole
    sim.acknowledged = [Acknowledgement(finding="prod run 9 is missing: gone", note=NOTE)]
    report = _report(sim, tree)
    assert report["stale_acknowledgements"] == [
        {"finding": "prod run 9 is missing: gone", "note": NOTE}]
    assert not any(s.get("acknowledged") for s in report["suggestions"])


# --- the CLI -----------------------------------------------------------------------------

def _acknowledged_manifest(hole, tmp_path, findings):
    from ambermeta.simulation import Acknowledgement, write_simulation

    sim, tree = hole
    sim.acknowledged = [Acknowledgement(finding=f, note=NOTE) for f in findings]
    # Beside the runs, so its relative paths resolve as discover wrote them.
    path = tree / "sim.json"
    write_simulation(sim, str(path), "json")
    return path


def test_validate_lists_an_acknowledged_finding_apart_and_strict_passes(
        hole, tmp_path, capsys, monkeypatch):
    sim, tree = hole
    text = _hole_finding(sim, tree)
    path = _acknowledged_manifest(hole, tmp_path, [text])

    rc, out, _ = _run(["validate", "--manifest", str(path), "--strict"], capsys, monkeypatch)
    assert rc == 0, out
    findings = out.split("Findings:")[1].split("Acknowledged:")[0] if "Findings:" in out else ""
    assert "prod run 3 is missing" not in findings
    acknowledged = out.split("Acknowledged:")[1]
    assert text in acknowledged and NOTE in acknowledged
    assert "Validation: OK, 1 acknowledged" in out


def test_strict_still_fails_on_what_is_not_acknowledged(hole, tmp_path, capsys,
                                                         monkeypatch):
    path = _acknowledged_manifest(hole, tmp_path, ["prod run 9 is missing: gone"])
    rc, out, _ = _run(["validate", "--manifest", str(path), "--strict"], capsys, monkeypatch)
    assert rc == 1
    assert "Acknowledged, no longer found:" in out
    assert "prod run 9 is missing: gone" in out


def test_plan_carries_acknowledgements_into_the_summaries(hole, tmp_path, capsys,
                                                         monkeypatch):
    sim, tree = hole
    text = _hole_finding(sim, tree)
    path = _acknowledged_manifest(hole, tmp_path, [text])
    out_dir = tmp_path / "results"
    rc, _, err = _run(["plan", "-m", str(path), "--summary-path", str(out_dir / "s.json"),
                       "--methods-summary-path", str(out_dir / "m.json")],
                      capsys, monkeypatch)
    assert rc == 0, err
    summary = json.loads((out_dir / "s.json").read_text(encoding="utf-8"))
    assert summary["acknowledged"] == [{"finding": text, "note": NOTE}]
    methods = json.loads((out_dir / "m.json").read_text(encoding="utf-8"))
    assert methods["findings"]["acknowledged"] == [{"finding": text, "note": NOTE}]


def test_a_replica_coherence_warning_can_be_acknowledged(tmp_path, capsys, monkeypatch):
    """Members that differ in temp0 on purpose: a warning `--strict` fails on."""
    from ambermeta.gui.api.core_bridge import discover_draft
    from ambermeta.simulation import Acknowledgement, write_simulation

    tree = write_run_tree(tmp_path / "runs",
                          alternating_runs("rep1/", [300.0], prod_temp=300.0)
                          + alternating_runs("rep2/", [300.0], prod_temp=310.0))
    sim = discover_draft(str(tree))["simulation"]
    [warning] = [f for f in _report(sim, tree)["coherence"] if f["severity"] == "warning"]
    sim.acknowledged = [Acknowledgement(finding=warning["message"],
                                        note="rep2 is the 310 K arm of the study.")]
    path = tree / "sim.json"
    write_simulation(sim, str(path), "json")
    rc, out, _ = _run(["validate", "--manifest", str(path), "--strict"], capsys, monkeypatch)
    assert "rep2 is the 310 K arm of the study." in out.split("Acknowledged:")[1]
    assert rc == 0 or "1 finding" not in out   # nothing left that --strict counts


# --- the GUI's API -----------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ambermeta.gui.api import routes

    tree = _hole_tree(tmp_path / "runs")
    routes.set_base_directory(str(tree))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    c = TestClient(app)
    assert c.post("/api/document/discover", json={"recursive": True}).status_code == 200
    return c


def _gui_hole_card(client):
    report = client.post("/api/validate").json()
    return next(s for s in report["suggestions"] if s["kind"] == "missing_run")


def test_the_gui_acknowledges_reopens_and_undoes(client):
    from ambermeta.acknowledgements import finding_text

    text = finding_text(_gui_hole_card(client))
    doc = client.post("/api/acknowledged", json={"finding": text, "note": NOTE}).json()
    assert doc["simulation"]["acknowledged"] == [{"finding": text, "note": NOTE}]
    assert _gui_hole_card(client)["acknowledged"] == NOTE

    # A second acknowledgement of the same finding replaces the note, not adds a row.
    doc = client.post("/api/acknowledged", json={"finding": text, "note": "better"}).json()
    assert doc["simulation"]["acknowledged"] == [{"finding": text, "note": "better"}]

    doc = client.post("/api/acknowledged/remove", json={"finding": text}).json()
    assert doc["simulation"]["acknowledged"] == []
    assert client.post("/api/undo").json()["simulation"]["acknowledged"] == [
        {"finding": text, "note": "better"}]


def test_the_gui_refuses_an_acknowledgement_without_a_note(client):
    from ambermeta.acknowledgements import finding_text

    text = finding_text(_gui_hole_card(client))
    r = client.post("/api/acknowledged", json={"finding": text, "note": "   "})
    assert r.status_code in (400, 422)


def test_rediscovering_keeps_the_acknowledgements(client):
    """Discover replaces the document; the user's notes are not the scan's to drop."""
    from ambermeta.acknowledgements import finding_text

    text = finding_text(_gui_hole_card(client))
    client.post("/api/acknowledged", json={"finding": text, "note": NOTE})
    doc = client.post("/api/document/discover", json={"recursive": True}).json()
    assert doc["document"]["simulation"]["acknowledged"] == [{"finding": text, "note": NOTE}]
    assert _gui_hole_card(client)["acknowledged"] == NOTE
