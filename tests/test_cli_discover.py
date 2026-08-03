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
