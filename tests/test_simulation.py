# tests/test_simulation.py
import pytest

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


# --- restart chain: the file is recorded on the step that writes it ---------

from ambermeta.simulation import (
    iter_steps, predecessors, relink_restarts, repair_dangling_refs, resolve_input_coords,
)


def _chain():
    """min -> nvt -> npt, each continuing from the previous run's restart."""
    return Simulation(
        starting_structure="cryst/wt.crd",
        phases=[Phase(id="ph_0", name="Equil", role="equilibration", steps=[
            Step(id="st_0", name="01_min",
                 input_coords=InputCoords(source="starting_structure"), rst="equil/01_min.rst"),
            Step(id="st_1", name="02_nvt",
                 input_coords=InputCoords(source="step", ref="st_0"), rst="equil/02_nvt.rst"),
            Step(id="st_2", name="03_npt",
                 input_coords=InputCoords(source="step", ref="st_1"), rst="equil/03_npt.rst"),
        ])],
    )


def test_resolve_input_coords_follows_the_producing_step():
    sim = _chain()
    steps = [s for _, s in iter_steps(sim)]
    assert resolve_input_coords(sim, steps[0]) == "cryst/wt.crd"
    assert resolve_input_coords(sim, steps[1]) == "equil/01_min.rst"
    assert resolve_input_coords(sim, steps[2]) == "equil/02_nvt.rst"


def test_resolve_input_coords_prefers_an_explicit_path_and_falls_back_to_it():
    sim = _chain()
    steps = [s for _, s in iter_steps(sim)]
    steps[1].input_coords = InputCoords(source="path", path="hand/picked.rst")
    assert resolve_input_coords(sim, steps[1]) == "hand/picked.rst"
    # A document written before restarts moved to the producer keeps working: the ref has
    # no rst behind it, so the path carried on the consumer is still honoured.
    steps[2].input_coords = InputCoords(source="step", ref="nobody", path="legacy/02_nvt.rst")
    assert resolve_input_coords(sim, steps[2]) == "legacy/02_nvt.rst"


def test_resolve_input_coords_is_none_when_the_chain_leads_nowhere():
    sim = _chain()
    steps = [s for _, s in iter_steps(sim)]
    steps[0].rst = None
    assert resolve_input_coords(sim, steps[1]) is None


def test_relink_restarts_repoints_each_chained_step_at_its_new_predecessor():
    sim = _chain()
    phase = sim.phases[0]
    before = predecessors(sim)
    phase.steps = [phase.steps[0], phase.steps[2], phase.steps[1]]   # swap 02_nvt / 03_npt
    relink_restarts(sim, before)
    assert phase.steps[0].input_coords.source == "starting_structure"
    assert phase.steps[1].input_coords.ref == "st_0"    # 03_npt now follows 01_min
    assert phase.steps[2].input_coords.ref == "st_2"    # 02_nvt now follows 03_npt


def test_relink_restarts_unchains_a_step_dragged_to_the_front():
    sim = _chain()
    phase = sim.phases[0]
    before = predecessors(sim)
    phase.steps = [phase.steps[2], phase.steps[0], phase.steps[1]]
    relink_restarts(sim, before)
    # Nothing precedes it any more, so it reads what tLEaP produced.
    assert phase.steps[0].input_coords == InputCoords(source="starting_structure")


def test_dragging_a_step_to_the_front_and_back_restores_its_link():
    """The demotion above must not be one-way, or the user's own correction loses data."""
    sim = _chain()
    phase = sim.phases[0]

    before = predecessors(sim)
    phase.steps = [phase.steps[2], phase.steps[0], phase.steps[1]]   # 03_npt to the front
    relink_restarts(sim, before)

    before = predecessors(sim)
    phase.steps = [phase.steps[1], phase.steps[2], phase.steps[0]]   # and back again
    relink_restarts(sim, before)

    assert [s.name for s in phase.steps] == ["01_min", "02_nvt", "03_npt"]
    assert phase.steps[2].input_coords.ref == "st_1"
    assert resolve_input_coords(sim, phase.steps[2]) == "equil/02_nvt.rst"


def test_relink_restarts_leaves_deliberate_choices_alone():
    sim = _chain()
    phase = sim.phases[0]
    phase.steps[1].input_coords = InputCoords(source="path", path="hand/picked.rst")
    phase.steps[2].input_coords = InputCoords(source="starting_structure")
    before = predecessors(sim)
    phase.steps = [phase.steps[0], phase.steps[2], phase.steps[1]]
    relink_restarts(sim, before)
    assert InputCoords(source="path", path="hand/picked.rst") in [s.input_coords for s in phase.steps]
    # A mid-run starting structure is a real setup (a fresh tLEaP restart), not the head
    # of the chain, so following the order must not chain it onto its new neighbour.
    npt = next(s for s in phase.steps if s.name == "03_npt")
    assert npt.input_coords.source == "starting_structure"


def test_relink_restarts_keeps_a_non_adjacent_continues_from():
    """The inspector lets a step continue from ANY other step; that is a choice, not a chain."""
    sim = _chain()
    phase = sim.phases[0]
    phase.steps.append(Step(id="st_3", name="04_rerun",
                            input_coords=InputCoords(source="step", ref="st_0")))
    before = predecessors(sim)
    phase.steps = [phase.steps[0], phase.steps[2], phase.steps[1], phase.steps[3]]
    relink_restarts(sim, before)
    assert phase.steps[3].input_coords.ref == "st_0"      # untouched by a drag elsewhere


def test_relink_restarts_keeps_a_legacy_resolved_path():
    """A manifest written before `rst` existed carries the filename on the consumer."""
    sim = _chain()
    phase = sim.phases[0]
    for s in phase.steps:
        s.rst = None
    phase.steps[1].input_coords = InputCoords(source="step", ref="st_0", path="equil/01_min.rst")
    before = predecessors(sim)
    phase.steps = [phase.steps[0], phase.steps[1], phase.steps[2]]   # no actual movement
    relink_restarts(sim, before)
    assert phase.steps[1].input_coords.path == "equil/01_min.rst"
    assert resolve_input_coords(sim, phase.steps[1]) == "equil/01_min.rst"


def test_repair_dangling_refs_rechains_orphans():
    sim = _chain()
    phase = sim.phases[0]
    del phase.steps[1]                       # 02_nvt goes; 03_npt still points at it
    repair_dangling_refs(sim)
    assert phase.steps[1].input_coords.ref == "st_0"
    # Removing the head leaves the survivor reading the starting structure, not a dead id.
    del phase.steps[0]
    repair_dangling_refs(sim)
    assert phase.steps[0].input_coords.source == "starting_structure"


def test_rst_round_trips_through_the_v2_payload():
    sim = _chain()
    payload = simulation_to_payload(sim)
    assert payload["steps"][0]["rst"] == "equil/01_min.rst"
    assert payload_to_simulation(payload) == sim


def test_a_step_with_no_restart_keeps_the_payload_it_always_had():
    sim = Simulation(phases=[Phase(id="ph_0", name="Min", role="", steps=[
        Step(id="st_0", name="min", mdin="min.in")])])
    assert "rst" not in simulation_to_payload(sim)["steps"][0]


def test_loading_a_flat_manifest_says_so_instead_of_returning_nothing(tmp_path):
    """A v1 file used to migrate silently; now it must be a clear error.

    Without this guard payload_to_simulation reads no "phases"/"steps" key and
    returns an EMPTY Simulation, so every caller reports "0 steps" for a file
    that is simply the wrong format.
    """
    from ambermeta.errors import AmberMetaError
    from ambermeta.simulation import load_simulation

    flat = tmp_path / "old.yaml"
    flat.write_text("stages:\n  - name: prod\n    mdin: prod.in\n", encoding="utf-8")

    with pytest.raises(AmberMetaError, match="not a v2 manifest"):
        load_simulation(str(flat))
