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
