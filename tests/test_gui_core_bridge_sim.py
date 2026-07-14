# tests/test_gui_core_bridge_sim.py
import json
from ambermeta.gui.api import core_bridge
from ambermeta.simulation import Simulation, Phase, Step, Topology


def _sim():
    return Simulation(
        topologies=[Topology(id="t0", path="wt.prmtop", kind="normal")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="p0", name="Min", role="minimization",
                      steps=[Step(id="s0", name="min", topology="t0", mdin="min.in")])],
    )


def test_open_v1_manifest_migrates(tmp_path):
    v1 = {"global_prmtop": "wt.prmtop",
          "stages": [{"name": "min", "stage_role": "minimization", "mdin": "min.in"},
                     {"name": "prod_001", "stage_role": "production", "mdin": "prod_001.in"}]}
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(v1))
    sim = core_bridge.open_simulation(str(path), str(tmp_path))
    assert sim.version == 2
    assert [p.role for p in sim.phases] == ["minimization", "production"]


def test_save_then_preview_round_trip(tmp_path):
    sim = _sim()
    target = tmp_path / "out.json"
    warnings = core_bridge.save_simulation(sim, str(tmp_path), str(target), "json")
    assert warnings == []
    reloaded = core_bridge.open_simulation(str(target), str(tmp_path))
    assert reloaded == sim
    out = core_bridge.preview_simulation(sim, str(tmp_path), "yaml")
    assert "phases" in out["content"] and out["warnings"] == []
