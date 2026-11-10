"""Verdicts that do not read as "all clear" over a finding, and findings in plain words.

From the workflow walk-through (`.claude/ux-audit/reports/2026-11-10-workflow.md`):

C3 `Validation: OK` was printed straight under a missing run, so a reader skimming for
   the verdict saw OK and stopped. It now says how many findings there are to review.
C4 Messages a scientist had to decode:
   - `rep2/prod sequence is missing member(s) 3: 'rep2/prod' has no run at index(es) 3`;
   - `2 of them state no resolved seed`;
   - `Continuity for equil/01_min was not measured (it declares no producing stage)`;
   - `Cannot verify continuity ... (missing end time from equil/01_min (no mdcrd/mdout))`
     after a minimisation, which has an mdout and no clock to end.
"""
from __future__ import annotations

import pytest

from conftest import RunSpec, md_mdin, write_run_tree


def _run(argv, capsys, monkeypatch):
    from ambermeta.cli import main

    monkeypatch.setenv("NO_COLOR", "1")
    try:
        rc = main(argv)
    except SystemExit as exc:
        rc = exc.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def _chain(prefix, indices, *, natoms=None):
    runs, clock = [], 0.0
    for i in indices:
        runs.append((f"{prefix}prod_{i:04d}",
                     RunSpec(mdin=md_mdin("prod", 5000), elapsed_ps=10.0, begin_ps=clock,
                             natoms=natoms)))
        clock += 10.0
    return runs


def _manifest(tree, tmp_path, capsys, monkeypatch):
    path = tmp_path / "sim.yaml"
    rc, _, err = _run(["discover", str(tree), "--write", str(path)], capsys, monkeypatch)
    assert rc == 0, err
    return path


# --- C3: the verdict -----------------------------------------------------------------

def test_ok_with_findings_says_how_many_to_review(tmp_path, capsys, monkeypatch):
    tree = write_run_tree(tmp_path / "tree", _chain("", [1, 2, 4]))
    rc, out, _ = _run(["validate", "--manifest",
                       str(_manifest(tree, tmp_path, capsys, monkeypatch))],
                      capsys, monkeypatch)
    assert rc == 0
    assert "Validation: OK, 1 finding to review" in out


def test_ok_without_findings_is_just_ok(tmp_path, capsys, monkeypatch):
    tree = write_run_tree(tmp_path / "tree", _chain("", [1, 2, 3]))
    rc, out, _ = _run(["validate", "--manifest",
                       str(_manifest(tree, tmp_path, capsys, monkeypatch))],
                      capsys, monkeypatch)
    assert out.rstrip().splitlines()[-1] == "Validation: OK"


# --- C4: a sequence hole -------------------------------------------------------------

def test_an_interior_hole_names_the_run_and_what_is_there():
    from ambermeta.protocol import sequence_findings

    [card] = sequence_findings(["prod_0001", "prod_0002", "prod_0004", "prod_0005"])
    assert card["title"] == "prod run 3 is missing"
    assert card["evidence"] == "The prod runs here are numbered 1-2, 4-5."


def test_a_short_replica_says_its_siblings_went_further():
    from ambermeta.protocol import sequence_findings

    names = ["rep1/prod_0001", "rep1/prod_0002", "rep1/prod_0003",
             "rep2/prod_0001",
             "rep3/prod_0001", "rep3/prod_0002", "rep3/prod_0003"]
    tags = ["rep1"] * 3 + ["rep2"] + ["rep3"] * 3
    [card] = sequence_findings([n.split("/")[1] for n in names], tags)
    assert card["title"] == "rep2/prod runs 2, 3 are missing"
    assert card["evidence"] == ("rep2 has prod run 1, and the other replicas go on to 3: "
                                "rep2 may have stopped early, or its later runs were not "
                                "deposited.")
    # The canvas matches ghosts on these, so they must not move.
    assert card["base"] == "prod" and card["missing"] == [2, 3] and card["lineage"] == "rep2"


# --- C4: replicas that branch from one restart ---------------------------------------

def test_the_seed_note_says_what_the_seed_is_for(tmp_path):
    from ambermeta.protocol import auto_discover
    from ambermeta.lineages import coherence

    runs = [("prep/eq_0001", RunSpec(mdin=md_mdin("eq", 500), elapsed_ps=1.0))]
    for rep in ("rep1", "rep2"):
        runs.append((f"{rep}/prod_0001",
                     RunSpec(mdin=md_mdin("prod", 5000), elapsed_ps=10.0, begin_ps=1.0,
                             inpcrd="../prep/eq_0001.restrt")))
    protocol = auto_discover(str(write_run_tree(tmp_path, runs)), recursive=True)
    [note] = [f for f in coherence(protocol.stages) if f.kind == "fan_out"]
    assert note.message == (
        "2 runs start from the restart written by prep/eq_0001; 2 of their mdouts do not "
        "record the random seed (ig) used, which is what sets such runs apart.")


# --- C4: continuity that was not measured --------------------------------------------

_MIN_MDIN = "minimise\n &cntrl\n  imin = 1, maxcyc = 500, ntb = 1,\n /\n"


def test_the_run_after_a_minimisation_is_told_why_it_was_not_measured(tmp_path):
    from ambermeta.protocol import auto_discover

    tree = write_run_tree(tmp_path, [
        ("01_min", RunSpec(mdin=_MIN_MDIN, elapsed_ps=0.0, imin=1, irest=0,
                           inpcrd="start.rst")),
        ("02_heat", RunSpec(mdin=md_mdin("heat", 5000, irest=0, ntp=0), elapsed_ps=10.0,
                            irest=0, inpcrd="01_min.restrt")),
    ])
    protocol = auto_discover(str(tree), recursive=True)
    heat = next(s for s in protocol.stages if s.name == "02_heat")
    notes = " ".join(heat.continuity + heat.validation)
    assert "missing end time" not in notes
    assert "01_min is a minimisation, which has no simulation clock" in notes or \
        "set its own clock" in notes


def test_a_minimisation_followed_by_a_continuation_names_the_minimisation(tmp_path):
    """irest = 1 after a minimisation: the clock is read from the coordinates, so the
    pair is measured, and the reason it cannot be is that the minimisation has no clock."""
    from ambermeta.protocol import auto_discover

    tree = write_run_tree(tmp_path, [
        ("01_min", RunSpec(mdin=_MIN_MDIN, elapsed_ps=0.0, imin=1, irest=0,
                           inpcrd="start.rst")),
        ("02_eq", RunSpec(mdin=md_mdin("eq", 5000), elapsed_ps=10.0,
                          inpcrd="01_min.restrt")),
    ])
    protocol = auto_discover(str(tree), recursive=True)
    eq = next(s for s in protocol.stages if s.name == "02_eq")
    notes = " ".join(eq.continuity)
    assert "missing end time" not in notes
    assert "01_min is a minimisation, which has no simulation clock" in notes


def test_a_first_run_is_told_plainly_why_it_was_not_measured(tmp_path):
    from ambermeta.protocol import auto_discover

    runs = [(f"{rep}/prod_0001", RunSpec(mdin=md_mdin("prod", 5000), elapsed_ps=10.0))
            for rep in ("rep1", "rep2")]
    protocol = auto_discover(str(write_run_tree(tmp_path, runs)), recursive=True)
    notes = [n for s in protocol.stages for n in s.continuity if "not measured" in n]
    assert notes
    assert all("no run is named as the one it continues from" in n for n in notes)
    assert not any("producing stage" in n for n in notes)
