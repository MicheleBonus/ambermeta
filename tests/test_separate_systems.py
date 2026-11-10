"""A folder that holds several separate simulations is refused, not merged into one.

A campaign folder (`wt/`, `mut/`, each with its own runs) was scanned into ONE simulation:
one starting structure for both systems, the two systems proposed as replicas of each
other, and the only warning about it was "confirm normal vs HMR". A restart written by an
N-atom run cannot be read by an M-atom run, so runs whose mdouts report different atom
counts cannot be one simulation. That is the rule these tests pin. `--as-one-simulation`
keeps the old behaviour for a false alarm (a vacuum minimisation beside the solvated runs).
"""
import pytest

from conftest import RunSpec, md_mdin, write_run_tree


def _system(prefix, natoms, runs=2):
    out = []
    clock = 0.0
    previous = "start.rst"
    for i in range(1, runs + 1):
        stem = f"{prefix}prod_{i:04d}"
        out.append((stem, RunSpec(mdin=md_mdin("production", 5000), elapsed_ps=10.0,
                                  begin_ps=clock, inpcrd=previous, natoms=natoms)))
        clock += 10.0
        previous = f"prod_{i:04d}.restrt"
    return out


@pytest.fixture
def two_systems(tmp_path):
    return write_run_tree(tmp_path, _system("wt/", 2000) + _system("mut/", 2012))


def test_discover_refuses_runs_of_different_sizes(two_systems):
    from ambermeta.gui.api.core_bridge import discover_draft
    from ambermeta.systems import SeparateSystemsError

    with pytest.raises(SeparateSystemsError) as info:
        discover_draft(str(two_systems))
    labels = {s.label: (s.natom, len(s.runs)) for s in info.value.systems}
    assert labels == {"wt": (2000, 2), "mut": (2012, 2)}
    assert "2 separate simulations" in str(info.value)


def test_a_system_is_named_by_its_top_folder_not_by_where_its_runs_happen_to_sit(tmp_path):
    """mut's runs are all in mut/prod/, but its topology and starting structure are in
    mut/setup/: `discover mut/prod` would leave them out, so the folder to name is mut."""
    from ambermeta.gui.api.core_bridge import discover_draft
    from ambermeta.systems import SeparateSystemsError

    write_run_tree(tmp_path, _system("wt/equil/", 2000) + _system("wt/prod/", 2000)
                   + _system("mut/prod/", 2012))
    with pytest.raises(SeparateSystemsError) as info:
        discover_draft(str(tmp_path))
    assert {s.label for s in info.value.systems} == {"wt", "mut"}


def test_as_one_simulation_keeps_the_merged_draft(two_systems):
    from ambermeta.gui.api.core_bridge import discover_draft

    result = discover_draft(str(two_systems), as_one_simulation=True)
    names = sorted(s.name for p in result["simulation"].phases for s in p.steps)
    assert names == ["mut/prod_0001", "mut/prod_0002", "wt/prod_0001", "wt/prod_0002"]


def test_one_system_of_one_size_is_not_refused(tmp_path):
    from ambermeta.gui.api.core_bridge import discover_draft

    write_run_tree(tmp_path, _system("rep1/", 2000) + _system("rep2/", 2000))
    result = discover_draft(str(tmp_path))
    assert len([s for p in result["simulation"].phases for s in p.steps]) == 4


def test_runs_that_state_no_size_are_not_counted(tmp_path):
    """No `RESOURCE USE` block, no atom count: nothing to tell systems apart by."""
    from ambermeta.gui.api.core_bridge import discover_draft

    write_run_tree(tmp_path, _system("wt/", None) + _system("mut/", 2012))
    discover_draft(str(tmp_path))  # does not raise


def test_the_sample_is_one_simulation(sample_md_data_dir):
    from ambermeta.gui.api.core_bridge import discover_draft

    discover_draft(str(sample_md_data_dir))  # does not raise


def test_runs_side_by_side_in_one_folder_are_named_by_run(tmp_path):
    """No folder separates them, so each system is labelled by its first run."""
    from ambermeta.gui.api.core_bridge import discover_draft
    from ambermeta.systems import SeparateSystemsError

    write_run_tree(tmp_path, [
        ("01_min_vacuum", RunSpec(mdin=md_mdin("min", 100), elapsed_ps=0.2, natoms=500)),
        ("02_prod", RunSpec(mdin=md_mdin("production", 5000), elapsed_ps=10.0, natoms=9000)),
    ])
    with pytest.raises(SeparateSystemsError) as info:
        discover_draft(str(tmp_path))
    assert {s.label for s in info.value.systems} == {"01_min_vacuum", "02_prod"}


def test_plan_recursive_refuses_too(two_systems):
    from ambermeta.protocol import auto_discover
    from ambermeta.systems import SeparateSystemsError

    with pytest.raises(SeparateSystemsError):
        auto_discover(str(two_systems), recursive=True)
    protocol = auto_discover(str(two_systems), recursive=True, as_one_simulation=True)
    assert len(protocol.stages) == 4


def test_a_manifest_is_not_second_guessed(two_systems, tmp_path):
    """A manifest is the user's own declaration: validating one is never refused."""
    from ambermeta.gui.api.core_bridge import discover_draft, validate_simulation

    sim = discover_draft(str(two_systems), as_one_simulation=True)["simulation"]
    validate_simulation(sim, {}, str(two_systems))  # does not raise


# --- the CLI ---------------------------------------------------------------------------

def _cli(argv, capsys, monkeypatch, cwd):
    from ambermeta.cli import main

    monkeypatch.chdir(cwd)
    monkeypatch.setenv("NO_COLOR", "1")
    try:
        rc = main(argv)
    except SystemExit as exc:          # argparse leaves through SystemExit
        rc = exc.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_cli_discover_names_each_system_and_how_to_go_on(two_systems, capsys, monkeypatch):
    rc, out, err = _cli(["discover", "."], capsys, monkeypatch, two_systems)
    assert rc == 1
    assert "2 separate simulations" in err
    assert "wt/" in err and "mut/" in err
    assert "ambermeta discover wt" in err
    assert "--as-one-simulation" in err
    assert "Simulation summary" not in out


def test_cli_discover_as_one_simulation(two_systems, capsys, monkeypatch):
    rc, out, err = _cli(["discover", ".", "--as-one-simulation"], capsys, monkeypatch,
                        two_systems)
    assert rc == 0, err
    assert "wt/prod_0001" in out and "mut/prod_0001" in out


def test_cli_plan_recursive_refuses_and_can_be_overridden(two_systems, capsys, monkeypatch):
    rc, out, err = _cli(["plan", ".", "--recursive"], capsys, monkeypatch, two_systems)
    assert rc == 1
    assert "2 separate simulations" in err
    assert "ambermeta plan wt --recursive" in err
    # Scanned as one, the runs are summarised (and the lineage check then reports, as
    # an ERROR, that wt and mut do not hold the same number of atoms).
    rc, out, err = _cli(["plan", ".", "--recursive", "--as-one-simulation"], capsys,
                        monkeypatch, two_systems)
    assert "Discovered 4 stage(s)" in out
    assert "separate simulations" not in err


# --- the GUI -----------------------------------------------------------------------------

def test_gui_discover_is_a_400_that_names_the_systems(two_systems):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ambermeta.gui.api import routes

    routes.set_base_directory(str(two_systems))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    client = TestClient(app)
    r = client.post("/api/document/discover", json={"recursive": True})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "2 separate simulations" in detail
    assert "wt/" in detail and "mut/" in detail
    assert "Treat everything here as one simulation" in detail

    r = client.post("/api/document/discover",
                    json={"recursive": True, "as_one_simulation": True})
    assert r.status_code == 200
