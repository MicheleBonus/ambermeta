import json
from types import SimpleNamespace

import ambermeta.cli as cli
from ambermeta.simulation import load_simulation


def _args(directory, **over):
    base = dict(directory=directory, recursive=True, pattern=None, write=None, format=None)
    base.update(over)
    return SimpleNamespace(**base)


def test_discover_prints_pool_and_steps(sample_md_data_dir, capsys):
    rc = cli._discover_command(_args(str(sample_md_data_dir)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Simulation summary" in out
    assert "Topologies (pool):" in out
    # the production sequence became steps
    assert "ntp_prod_0001" in out
    assert "Phase:" in out


def test_discover_write_roundtrips_v2(sample_md_data_dir, tmp_path, capsys):
    dest = tmp_path / "draft.yaml"
    rc = cli._discover_command(_args(str(sample_md_data_dir), write=str(dest)))
    assert rc == 0
    assert dest.exists()
    sim = load_simulation(str(dest))          # v2 native round-trip
    assert sim.version == 2
    assert len(sim.phases) >= 1
    assert any(s.name.startswith("ntp_prod") for p in sim.phases for s in p.steps)


def test_discover_reports_the_lineage_grouping_and_writes_it(replica_tree, tmp_path, capsys):
    """Design section 8.2: no new flag. `--explain-grouping` is answered by the `[applied]`
    line and by the tag landing in the manifest, so the inference is visible as data."""
    dest = tmp_path / "draft.yaml"
    rc = cli._discover_command(_args(str(replica_tree), write=str(dest)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "[applied] Runs carry 3 declared lineage(s)" in out

    sim = load_simulation(str(dest))
    assert sorted({s.lineage for p in sim.phases for s in p.steps}) == ["rep1", "rep2", "rep3"]
    # Three phases, not nine: one per role, shared by the three members.
    assert [p.role for p in sim.phases] == ["heating", "minimization", "production"]


def test_discover_empty_directory_returns_1(tmp_path, capsys):
    rc = cli._discover_command(_args(str(tmp_path)))
    assert rc == 1
    assert "No simulation files discovered" in capsys.readouterr().out


def test_discover_missing_directory_returns_1(tmp_path):
    rc = cli._discover_command(_args(str(tmp_path / "nope")))
    assert rc == 1


# ---------------------------------------------------------------------------
# 1.3.0: a manifest written outside the scanned directory
# ---------------------------------------------------------------------------

main = cli.main


def _alternating(tmp_path):
    from tests.conftest import alternating_runs, write_run_tree
    return write_run_tree(tmp_path / "runs", alternating_runs("", [300.0, 300.0]))


def test_a_manifest_written_elsewhere_names_paths_that_resolve_from_it(tmp_path, capsys):
    from ambermeta.simulation import iter_steps, load_simulation

    tree = _alternating(tmp_path)
    manifest = tmp_path / "manifests" / "sim.yaml"
    manifest.parent.mkdir()
    assert main(["discover", str(tree), "--write", str(manifest)]) == 0
    out = capsys.readouterr().out
    assert "relative to its own directory" in out
    sim = load_simulation(str(manifest))
    for _, step in iter_steps(sim):
        assert step.mdout.startswith("../runs/")
        assert (manifest.parent / step.mdout).is_file()
        assert (manifest.parent / step.rst).is_file()

    assert main(["validate", "--manifest", str(manifest)]) == 0
    out = capsys.readouterr().out
    assert "missing" not in out


def test_plan_reads_such_a_manifest_with_either_directory(tmp_path, capsys):
    tree = _alternating(tmp_path)
    manifest = tmp_path / "manifests" / "sim.yaml"
    manifest.parent.mkdir()
    assert main(["discover", str(tree), "--write", str(manifest)]) == 0
    capsys.readouterr()
    for directory in (manifest.parent, tree):
        summary = tmp_path / "summary.json"
        assert main(["plan", str(directory), "-m", str(manifest), "--strict",
                     "--summary-path", str(summary)]) == 0
        import json
        data = json.loads(summary.read_text(encoding="utf-8"))
        assert data["totals"]["time_ps"] > 0
        assert all(not s["load_errors"] for s in data["stages"])


def test_a_manifest_in_the_scanned_directory_keeps_its_paths(tmp_path, capsys):
    from ambermeta.simulation import iter_steps, load_simulation

    tree = _alternating(tmp_path)
    assert main(["discover", str(tree), "--write", str(tree / "sim.yaml")]) == 0
    assert "relative to its own directory" not in capsys.readouterr().out
    sim = load_simulation(str(tree / "sim.yaml"))
    assert [s.mdout for _, s in iter_steps(sim)][0] == "eq_0001.mdout"


# --- PR #93 review: S2 (a manifest in a subdirectory) and M3 (--prmtop) ---------------

def test_a_manifest_in_a_subdirectory_keeps_paths_the_gui_resolves(tmp_path, capsys):
    """S2. Only a manifest OUTSIDE the scanned directory is rebased. Written into a
    subdirectory, its paths stay relative to the scanned directory, which is what the GUI
    serving that directory and `plan -m DIR` read them against. `validate --manifest`
    reads a manifest's paths from its own directory only (N2), so there they are missing,
    as in 1.2."""
    from ambermeta.gui.api import core_bridge
    from ambermeta.simulation import iter_steps, load_simulation

    tree = _alternating(tmp_path)
    manifest = tree / "sub" / "m.yaml"
    manifest.parent.mkdir()
    assert main(["discover", str(tree), "--write", str(manifest)]) == 0
    assert "relative to its own directory" not in capsys.readouterr().out
    sim = load_simulation(str(manifest))
    assert [s.mdout for _, s in iter_steps(sim)][0] == "eq_0001.mdout"

    gui_sim = core_bridge.open_simulation(str(manifest), str(tree))
    report = core_bridge.validate_simulation(gui_sim, {"strict_validation": True}, str(tree))
    assert report["ok"] and report["totals"]["time_ps"] > 0

    assert main(["plan", str(tree), "-m", str(manifest), "--strict"]) == 0
    capsys.readouterr()
    assert main(["validate", "--manifest", str(manifest)]) == 1
    assert "missing mdin" in capsys.readouterr().out


def test_validate_does_not_read_a_manifest_from_unrelated_parent_directories(tmp_path, capsys):
    """PR #93 verification, N2 (probe R4). The manifest names `prod.mdin`/`prod.mdout`,
    which are not beside it; an unrelated `prod.mdin`/`prod.mdout` sits two levels up. A
    search of the parent directories validated the manifest OK against those files."""
    from tests.conftest import RunSpec, md_mdin, write_run_tree

    write_run_tree(tmp_path, [("prod", RunSpec(mdin=md_mdin("prod", 10000), elapsed_ps=20.0,
                                                inpcrd="start.rst"))])
    manifest = tmp_path / "proj" / "manifests" / "m.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "version: 2\nsimulation:\n  topologies: []\n  starting_structure: null\nphases:\n"
        "- id: p1\n  name: Production\n  role: production\n  order: 0\nsteps:\n- id: s1\n"
        "  name: prod\n  phase: p1\n  order: 0\n  input_coords:\n"
        "    source: starting_structure\n"
        "  mdin: prod.mdin\n  mdout: prod.mdout\n  mdcrd: null\n  notes: []\n")
    assert main(["validate", "--manifest", str(manifest)]) == 1
    captured = capsys.readouterr()
    assert "missing mdin: prod.mdin" in captured.out and "missing mdout" in captured.out
    assert "NOTE" not in captured.err


def test_plan_falls_back_to_the_manifest_directory_only_when_every_file_is_there(
        tmp_path, capsys):
    """N2 for `plan -m`: one named file missing beside the manifest means it is not a
    manifest written there, and the files are reported missing from the directory given."""
    import json

    tree = _alternating(tmp_path)
    manifest = tmp_path / "manifests" / "sim.yaml"
    manifest.parent.mkdir()
    assert main(["discover", str(tree), "--write", str(manifest)]) == 0
    (tree / "prod_0002.mdin").unlink()
    elsewhere = tmp_path / "a" / "b"
    elsewhere.mkdir(parents=True)
    summary = tmp_path / "s.json"
    capsys.readouterr()
    assert main(["plan", str(elsewhere), "-m", str(manifest),
                 "--summary-path", str(summary)]) == 0
    assert "manifest's own directory" not in capsys.readouterr().err
    stages = json.loads(summary.read_text(encoding="utf-8"))["stages"]
    assert all(s["load_errors"] for s in stages)


def test_a_relative_prmtop_is_named_from_the_positional_directory(tmp_path, capsys):
    """M3. When `plan -m` reads the manifest's paths from beside the manifest, a relative
    `--prmtop` is still looked up in the directory the user named."""
    import json
    from tests.test_discover_record_chain import _prmtop

    tree = _alternating(tmp_path)
    manifest = tmp_path / "manifests" / "sim.yaml"
    manifest.parent.mkdir()
    assert main(["discover", str(tree), "--write", str(manifest)]) == 0
    positional = tmp_path / "a" / "b"
    positional.mkdir(parents=True)
    _prmtop(positional / "sys.prmtop", 2)
    summary = tmp_path / "s.json"
    capsys.readouterr()
    assert main(["plan", str(positional), "-m", str(manifest), "--prmtop", "sys.prmtop",
                 "--summary-path", str(summary)]) == 0
    err = capsys.readouterr().err
    assert "reading its paths from the manifest's own directory" in err
    assert "prmtop not found" not in err
    stages = json.loads(summary.read_text(encoding="utf-8"))["stages"]
    assert all(s["files"]["prmtop"] for s in stages)
