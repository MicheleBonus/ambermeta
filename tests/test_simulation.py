# tests/test_simulation.py
from ambermeta.simulation import Topology, InputCoords, Step, Phase, Simulation


def test_build_a_two_phase_simulation():
    sim = Simulation(
        topologies=[Topology(id="top_wt", path="wt.prmtop", kind="normal"),
                    Topology(id="top_hmr", path="wt_hmr.prmtop", kind="hmr")],
        starting_structure="wt.inpcrd",
        phases=[
            Phase(id="ph_0", name="Minimization", role="minimization", steps=[
                Step(id="st_0", name="min", topology="top_wt",
                     input_coords=InputCoords(source="starting_structure"), mdin="min.in")]),
            Phase(id="ph_1", name="Production", role="production", steps=[
                Step(id="st_1", name="prod_001", topology="top_hmr",
                     input_coords=InputCoords(source="step", ref="st_0"), mdin="prod_001.in")]),
        ],
    )
    assert sim.version == 2
    assert [p.role for p in sim.phases] == ["minimization", "production"]
    assert sim.phases[1].steps[0].input_coords.ref == "st_0"
    assert sim.phases[0].steps[0].input_coords.source == "starting_structure"


from ambermeta.simulation import simulation_to_payload, payload_to_simulation


def test_payload_shape_and_round_trip():
    sim = Simulation(
        topologies=[Topology(id="top_wt", path="wt.prmtop", kind="normal")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="ph_0", name="Min", role="minimization", steps=[
            Step(id="st_0", name="min", topology="top_wt",
                 input_coords=InputCoords(source="starting_structure"),
                 mdin="min.in", expected_gap_ps=5.0)])],
    )
    payload = simulation_to_payload(sim)
    assert payload["version"] == 2
    assert payload["simulation"]["topologies"][0]["kind"] == "normal"
    assert payload["simulation"]["starting_structure"] == "wt.inpcrd"
    assert payload["phases"][0]["role"] == "minimization"
    assert payload["steps"][0]["phase"] == "ph_0"
    assert payload["steps"][0]["gaps"] == {"expected": 5.0, "tolerance": None}

    back = payload_to_simulation(payload)
    assert back == sim          # dataclass equality: full round trip


from ambermeta.simulation import write_simulation, load_simulation


def test_write_then_load_v2_yaml_and_json(tmp_path):
    sim = Simulation(
        topologies=[Topology(id="top_wt", path="wt.prmtop", kind="normal")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="ph_0", name="Min", role="minimization", steps=[
            Step(id="st_0", name="min", topology="top_wt", mdin="min.in")])],
    )
    for fmt, ext in [("json", ".json"), ("yaml", ".yaml")]:
        target = tmp_path / f"sim{ext}"
        write_simulation(sim, str(target), fmt)
        loaded = load_simulation(str(target))
        assert loaded == sim
