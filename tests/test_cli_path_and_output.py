"""The path from run folders to summary files, and output a person can read.

From the workflow walk-through (`.claude/ux-audit/reports/2026-11-10-workflow.md`):

B1 The CLI never said what order to run things in: eight commands, `plan` first, and the
   command that writes the summaries was the fourth example. `plan`'s three modes listed
   their options in one block, and its help spoke of a `SimulationProtocol`.
B2 The deliverables took three path options (`--summary-path`, `--methods-summary-path`,
   `--stats-csv`); `--out DIR` writes them all under their usual names.
F1 Every step line carried its topology and its mdin/mdout paths, so the same long listing
   was printed by discover and again by plan; times were `41100.000 ps`; a replica's line
   listed `equilibration 0.000` for a role it never ran; `plan --recursive` printed every
   note twice (`evidence:` is the notes joined with "; ").
"""
from __future__ import annotations

import json
import os

import pytest

from conftest import RunSpec, md_mdin, write_run_tree


def _run(argv, capsys, monkeypatch, cwd=None):
    from ambermeta.cli import main

    monkeypatch.setenv("NO_COLOR", "1")
    if cwd is not None:
        monkeypatch.chdir(cwd)
    try:
        rc = main(argv)
    except SystemExit as exc:          # argparse leaves through SystemExit
        rc = exc.code
    out = capsys.readouterr()
    return rc, out.out, out.err


# --- B1: say the order -------------------------------------------------------------------

def test_top_level_help_gives_the_workflow_in_order(capsys, monkeypatch):
    rc, out, _ = _run(["--help"], capsys, monkeypatch)
    assert rc == 0
    assert "Typical workflow" in out
    steps = [out.index(s) for s in ("ambermeta discover", "ambermeta validate --manifest",
                                    "ambermeta plan -m sim.yaml --out")]
    assert steps == sorted(steps)


def test_top_level_help_lists_what_amber_names_restarts(capsys, monkeypatch):
    rc, out, _ = _run(["--help"], capsys, monkeypatch)
    assert ".restrt" in out
    # A .crd is typed by its content (LEaP coordinates or a trajectory), not its extension.
    assert ".crd" in out and "by content" in out


def test_plan_help_groups_options_by_mode_and_drops_class_names(capsys, monkeypatch):
    rc, out, _ = _run(["plan", "--help"], capsys, monkeypatch)
    assert rc == 0
    assert "SimulationProtocol" not in out
    for heading in ("Output files", "With -m", "With --recursive"):
        assert heading in out, heading
    # --pattern is a scan option: it is listed under the scan heading, not the manifest one.
    scan_section = out[out.index("With --recursive:"):out.index("Other options")]
    assert "--pattern PATTERN" in scan_section


# --- B2: one folder for the deliverables -------------------------------------------------

@pytest.fixture
def manifest(tmp_path, sample_md_data_dir, capsys, monkeypatch):
    path = tmp_path / "sim.yaml"
    rc, _, err = _run(["discover", str(sample_md_data_dir), "--write", str(path)], capsys,
                      monkeypatch)
    assert rc == 0, err
    return path


def test_out_writes_every_summary_under_its_usual_name(manifest, tmp_path, capsys,
                                                       monkeypatch):
    results = tmp_path / "results"
    rc, out, err = _run(["plan", "-m", str(manifest), "--out", str(results)], capsys,
                        monkeypatch)
    assert rc == 0, err
    assert sorted(os.listdir(results)) == ["methods_summary.json", "stats.csv",
                                           "summary.json"]
    assert json.loads((results / "summary.json").read_text(encoding="utf-8"))["stages"]


def test_a_named_output_overrides_its_default_in_out(manifest, tmp_path, capsys,
                                                     monkeypatch):
    results = tmp_path / "results"
    elsewhere = tmp_path / "protocol.json"
    rc, _, err = _run(["plan", "-m", str(manifest), "--out", str(results),
                       "--summary-path", str(elsewhere)], capsys, monkeypatch)
    assert rc == 0, err
    assert elsewhere.is_file()
    assert sorted(os.listdir(results)) == ["methods_summary.json", "stats.csv"]


def test_out_follows_summary_format(manifest, tmp_path, capsys, monkeypatch):
    pytest.importorskip("yaml")
    results = tmp_path / "results"
    rc, _, err = _run(["plan", "-m", str(manifest), "--out", str(results),
                       "--summary-format", "yaml"], capsys, monkeypatch)
    assert rc == 0, err
    assert "summary.yaml" in os.listdir(results)


# --- F1: a listing you can read ----------------------------------------------------------

def test_discover_lists_one_short_line_per_run(sample_md_data_dir, capsys, monkeypatch):
    rc, out, _ = _run(["discover", str(sample_md_data_dir)], capsys, monkeypatch)
    assert rc == 0
    line = next(l for l in out.splitlines() if l.strip().startswith("- ntp_prod_0002"))
    assert line.strip() == "- ntp_prod_0002  from ntp_prod_0001"
    # One topology: named once in the pool, not on every run.
    assert "topology=" not in out


def test_discover_verbose_keeps_the_full_line(sample_md_data_dir, capsys, monkeypatch):
    rc, out, _ = _run(["discover", "-v", str(sample_md_data_dir)], capsys, monkeypatch)
    assert rc == 0
    assert "(mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)" in out
    assert "topology=CH3L1_HUMAN_6NAG.top" in out


def _shared_prep_and_replicas(root):
    runs = [("prep/eq_0001", RunSpec(mdin=md_mdin("eq", 1500, temp0=300.0), elapsed_ps=3.0,
                                     inpcrd="start.rst"))]
    for rep in ("rep1", "rep2"):
        runs.append((f"{rep}/prod_0001",
                     RunSpec(mdin=md_mdin("prod", 1_000_000), elapsed_ps=2000.0,
                             begin_ps=3.0, inpcrd="../prep/eq_0001.restrt")))
    return write_run_tree(root, runs)


def test_times_are_in_ns_and_a_replica_lists_only_what_it_ran(tmp_path, capsys,
                                                              monkeypatch):
    _shared_prep_and_replicas(tmp_path)
    rc, out, _ = _run(["plan", str(tmp_path), "--recursive"], capsys, monkeypatch)
    assert "Simulated time: 4.003 ns (equilibration 3 ps; production 4 ns)" in out
    rep1 = next(l for l in out.splitlines() if l.strip().startswith("rep1 "))
    assert rep1.split() == ["rep1", "1", "run(s),", "2", "ns"]


def test_recursive_prints_each_note_once(tmp_path, capsys, monkeypatch):
    _shared_prep_and_replicas(tmp_path)
    rc, out, _ = _run(["plan", str(tmp_path), "--recursive"], capsys, monkeypatch)
    assert "evidence:" not in out
    assert "note: INFO: Part of sequence" in out or "note: INFO:" in out


def test_a_single_role_document_still_says_how_much_was_simulated(manifest, capsys,
                                                                    monkeypatch):
    """The time line was printed only when the runs held more than one role, so the
    sample's five production runs were validated without ever saying they made 100 ns."""
    rc, out, _ = _run(["validate", "--manifest", str(manifest)], capsys, monkeypatch)
    assert "Simulated time: 100 ns" in out
