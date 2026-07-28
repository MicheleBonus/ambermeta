# tests/test_migration.py
from ambermeta.simulation import migrate_v1_manifest


def test_migrate_flat_v1_to_phases_pool_and_input_chain():
    v1 = {
        "global_prmtop": "wt.prmtop",
        "hmr_prmtop": "wt_hmr.prmtop",
        "initial_coordinates": "wt.inpcrd",
        "stages": [
            {"name": "min", "stage_role": "minimization", "mdin": "min.in"},
            {"name": "heat", "stage_role": "heating", "mdin": "heat.in"},
            {"name": "prod_001", "stage_role": "production", "mdin": "prod_001.in"},
            {"name": "prod_002", "stage_role": "production", "mdin": "prod_002.in"},
        ],
    }
    sim = migrate_v1_manifest(v1)

    # topology pool: both prmtops preserved and labeled
    assert {(t.path, t.kind) for t in sim.topologies} == {
        ("wt.prmtop", "normal"), ("wt_hmr.prmtop", "hmr")}
    assert sim.starting_structure == "wt.inpcrd"

    # contiguous roles -> phases
    assert [p.role for p in sim.phases] == ["minimization", "heating", "production"]
    assert [len(p.steps) for p in sim.phases] == [1, 1, 2]

    # first step reads the starting structure; later steps chain from the previous
    first = sim.phases[0].steps[0]
    assert first.input_coords.source == "starting_structure"
    second = sim.phases[1].steps[0]
    assert second.input_coords.source == "step"
    assert second.input_coords.ref == first.id


def test_migrate_infers_role_when_absent():
    v1 = [{"name": "prod/run", "mdin": "run.in"}]   # audit divergence stem
    sim = migrate_v1_manifest(v1)
    assert sim.phases[0].role == "production"


# append to tests/test_migration.py
import json
from ambermeta.simulation import load_simulation


def test_open_a_v1_json_file_yields_a_migrated_simulation(tmp_path):
    v1 = {
        "global_prmtop": "wt.prmtop",
        "stages": [
            {"name": "min", "stage_role": "minimization", "mdin": "min.in"},
            {"name": "prod_001", "stage_role": "production", "mdin": "prod_001.in"},
        ],
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(v1))
    sim = load_simulation(str(path))
    assert sim.version == 2
    assert [p.role for p in sim.phases] == ["minimization", "production"]
    assert sim.topologies[0].path == "wt.prmtop"


def test_migration_keeps_a_v1_stage_inpcrd_as_the_previous_step_restart(tmp_path):
    """v1 recorded the coordinates each stage READ; v2 records what each step WRITES."""
    from ambermeta.simulation import load_simulation, resolve_input_coords
    manifest = tmp_path / "v1.yaml"
    manifest.write_text(
        "global_prmtop: wt.prmtop\n"
        "initial_coordinates: wt.inpcrd\n"
        "stages:\n"
        "  - { name: 01_min, mdin: 01_min.mdin }\n"
        "  - { name: 02_nvt, mdin: 02_nvt.mdin, inpcrd: 01_min.rst }\n"
        "  - { name: 03_npt, mdin: 03_npt.mdin, inpcrd: 02_nvt.rst }\n",
        encoding="utf-8",
    )
    sim = load_simulation(str(manifest))
    steps = [s for p in sim.phases for s in p.steps]
    assert steps[0].rst == "01_min.rst"     # named by the stage that read it
    assert steps[1].rst == "02_nvt.rst"
    assert steps[2].rst is None             # nothing downstream named one
    assert resolve_input_coords(sim, steps[1]) == "01_min.rst"
    assert resolve_input_coords(sim, steps[0]) == "wt.inpcrd"
