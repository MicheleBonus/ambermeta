"""A drafted manifest a person can read and edit.

From the workflow walk-through (`.claude/ux-audit/reports/2026-11-10-workflow.md`):

D1 Discover minted every step and phase id from `uuid4().hex[:8]`, so the manifest linked
   steps by `ref: 54a5d00b`, and changing which run a step continues from meant matching
   hex strings by hand. The ids are now the names, made safe for a URL, and the same
   directory gives the same manifest every time.
D2 `discover` printed what it had guessed and what needed checking, and `--write` kept
   none of it: the manifest beside that list carried no trace of it. A YAML draft now
   starts with that list as comments.
"""
from __future__ import annotations

import re

import pytest

from conftest import RunSpec, md_mdin, write_run_tree

SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _run(argv, capsys, monkeypatch):
    from ambermeta.cli import main

    monkeypatch.setenv("NO_COLOR", "1")
    try:
        rc = main(argv)
    except SystemExit as exc:
        rc = exc.code
    out = capsys.readouterr()
    return rc, out.out, out.err


# --- D1: ids are names -----------------------------------------------------------------

def test_discovered_ids_are_the_run_and_phase_names(sample_md_data_dir):
    from ambermeta.gui.api.core_bridge import discover_draft

    sim = discover_draft(str(sample_md_data_dir))["simulation"]
    [phase] = sim.phases
    assert phase.id == "production"
    assert [s.id for s in phase.steps] == [f"ntp_prod_{i:04d}" for i in range(1, 6)]
    second = phase.steps[1]
    assert second.input_coords.source == "step" and second.input_coords.ref == "ntp_prod_0001"


def test_ids_from_paths_are_safe_and_unique(tmp_path):
    from ambermeta.gui.api.core_bridge import discover_draft

    runs = [("equil/01_min", RunSpec(mdin="min\n &cntrl\n  imin = 1, maxcyc = 10,\n /\n",
                                     elapsed_ps=0.0, imin=1, irest=0)),
            ("equil/02_eq", RunSpec(mdin=md_mdin("eq", 500), elapsed_ps=1.0,
                                    inpcrd="01_min.restrt")),
            ("prod/rep1/prod_0001", RunSpec(mdin=md_mdin("prod", 5000), elapsed_ps=10.0,
                                            inpcrd="../../equil/02_eq.restrt")),
            ("prod/rep2/prod_0001", RunSpec(mdin=md_mdin("prod", 5000), elapsed_ps=10.0,
                                            inpcrd="../../equil/02_eq.restrt"))]
    sim = discover_draft(str(write_run_tree(tmp_path, runs)))["simulation"]
    ids = [p.id for p in sim.phases] + [s.id for p in sim.phases for s in p.steps]
    assert len(ids) == len(set(ids))
    assert all(SAFE.match(i) for i in ids), ids
    steps = {s.name: s.id for p in sim.phases for s in p.steps}
    assert steps["equil/01_min"] == "equil_01_min"
    assert steps["prod/rep2/prod_0001"] == "prod_rep2_prod_0001"


def test_a_repeated_phase_gets_its_own_id(tmp_path):
    from conftest import alternating_runs
    from ambermeta.gui.api.core_bridge import discover_draft

    sim = discover_draft(str(write_run_tree(tmp_path, alternating_runs("", [300.0, 300.0]))))[
        "simulation"]
    assert [p.id for p in sim.phases] == ["equilibration", "production",
                                         "equilibration_2", "production_2"]


def test_a_name_that_collides_after_cleaning_is_numbered():
    from ambermeta.gui.api.core_bridge import _readable_id

    taken = set()
    assert _readable_id("a/b", taken) == "a_b"
    assert _readable_id("a_b", taken) == "a_b_2"
    assert _readable_id("///", taken) == "step"


def test_the_same_folder_drafts_the_same_manifest(sample_md_data_dir, tmp_path, capsys,
                                                  monkeypatch):
    # Same name in two folders: the header quotes the manifest's own name.
    first, second = tmp_path / "a" / "sim.yaml", tmp_path / "b" / "sim.yaml"
    for target in (first, second):
        rc, _, err = _run(["discover", str(sample_md_data_dir), "--write", str(target)],
                          capsys, monkeypatch)
        assert rc == 0, err
    assert first.read_bytes() == second.read_bytes()


# --- D2: the draft says what to check -------------------------------------------------

def _hole_tree(root):
    return write_run_tree(root, [
        (f"prod_{i:04d}", RunSpec(mdin=md_mdin("prod", 5000), elapsed_ps=10.0,
                                  begin_ps=10.0 * k))
        for k, i in enumerate((1, 2, 4))])


def test_a_yaml_draft_lists_what_to_check_as_comments(tmp_path, capsys, monkeypatch):
    pytest.importorskip("yaml")
    from ambermeta.simulation import load_simulation

    target = tmp_path / "sim.yaml"
    rc, _, err = _run(["discover", str(_hole_tree(tmp_path / "runs")), "--write",
                       str(target)], capsys, monkeypatch)
    assert rc == 0, err
    text = target.read_text(encoding="utf-8")
    header = text.split("\nversion:")[0]
    assert all(line.startswith("#") for line in header.splitlines() if line.strip())
    assert "Needs you:" in header
    needs = header.split("Needs you:")[1].split("Guessed from the files:")[0]
    assert "prod" in needs and "3" in needs   # the hole discover found
    assert "Guessed from the files:" in header
    assert "Phase roles inferred from file content/names" in header
    assert f"ambermeta validate --manifest {target.name}" in header
    # Comments are invisible to the reader: the manifest loads as before.
    assert [s.name for p in load_simulation(str(target)).phases for s in p.steps] == [
        "prod_0001", "prod_0002", "prod_0004"]


def test_a_json_draft_stays_plain_json(tmp_path, capsys, monkeypatch):
    import json

    target = tmp_path / "sim.json"
    rc, _, err = _run(["discover", str(_hole_tree(tmp_path / "runs")), "--write",
                       str(target)], capsys, monkeypatch)
    assert rc == 0, err
    assert json.loads(target.read_text(encoding="utf-8"))["steps"]
