# tests/test_gui_document.py
from ambermeta.gui.api.document import DocumentStore
from ambermeta.simulation import Simulation, Phase, Step, Topology, InputCoords


def _store():
    return DocumentStore("/base")


def test_empty_document_response():
    resp = _store().to_response()
    assert resp.base_directory == "/base"
    assert resp.simulation.version == 2 and resp.simulation.phases == []
    assert resp.can_undo is False and resp.dirty is False


def test_replace_and_snapshot_round_trip():
    st = _store()
    sim = Simulation(
        topologies=[Topology(id="t0", path="wt.prmtop", kind="hmr")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="p0", name="Prod", role="production", steps=[
            Step(id="s0", name="prod", topology="t0",
                 input_coords=InputCoords(source="starting_structure"), mdin="prod.in")])],
    )
    st.replace(simulation=sim, settings=st.get().settings, manifest_path=None,
               dirty=True, reset_history=True)
    resp = st.to_response()
    assert resp.simulation.topologies[0].kind == "hmr"
    assert resp.simulation.phases[0].steps[0].name == "prod"
    got_sim, settings, mp, base = st.snapshot()
    assert got_sim.phases[0].steps[0].topology == "t0" and base == "/base"


def test_undo_redo_noop_when_empty():
    st = _store()
    st.undo(); st.redo()   # no error, no change
    assert st.to_response().can_undo is False


def test_topology_pool_mutators_and_undo():
    st = _store()
    tid = st.add_topology("wt.prmtop", "normal")
    hid = st.add_topology("wt_hmr.prmtop", "hmr")
    st.set_starting_structure("wt.inpcrd")
    sim = st.get().simulation
    assert [t.path for t in sim.topologies] == ["wt.prmtop", "wt_hmr.prmtop"]
    assert sim.starting_structure == "wt.inpcrd"

    st.update_topology(hid, {"kind": "normal"})
    assert st._find_topology(hid).kind == "normal"

    st.remove_topology(tid)
    assert [t.id for t in st.get().simulation.topologies] == [hid]

    st.undo()   # undo the remove
    assert len(st.get().simulation.topologies) == 2


def test_phase_mutators_reorder_update_delete():
    st = _store()
    p_min = st.add_phase("Min", "minimization")
    p_prod = st.add_phase("Prod", "production")

    st.reorder_phases([p_prod, p_min])
    assert [p.id for p in st.get().simulation.phases] == [p_prod, p_min]

    st.update_phase(p_min, {"name": "Minimization", "role": "minimization"})
    assert st._find_phase(p_min).name == "Minimization"

    # default delete (reassign_to=None) drops the phase and its steps
    st.delete_phase(p_min)
    assert [p.id for p in st.get().simulation.phases] == [p_prod]


def test_reorder_phases_rejects_mismatched_ids():
    st = _store()
    p = st.add_phase("A", "")
    import pytest
    with pytest.raises(ValueError):
        st.reorder_phases([p, "bogus"])


def test_step_mutators_move_reorder_clear():
    st = _store()
    pa = st.add_phase("A", "equilibration")
    pb = st.add_phase("B", "production")
    s1 = st.add_step(pa, {"name": "eq1", "mdin": "eq1.in",
                          "input_coords": {"source": "starting_structure"}})
    s2 = st.add_step(pa, {"name": "eq2", "mdin": "eq2.in"})

    st.reorder_steps(pa, [s2, s1])
    assert [s.id for s in st._find_phase(pa).steps] == [s2, s1]

    st.move_step(s1, pb, 0)
    assert [s.id for s in st._find_phase(pa).steps] == [s2]
    assert [s.id for s in st._find_phase(pb).steps] == [s1]

    st.update_step(s1, {"topology": None, "mdout": "eq1.out", "mdin": ""})
    _, step = st._find_step(s1)
    assert step.topology is None and step.mdout == "eq1.out" and step.mdin is None

    st.delete_step(s2)
    assert st._find_phase(pa).steps == []


def test_add_step_sets_input_coords_source():
    st = _store()
    p = st.add_phase("P", "production")
    sid = st.add_step(p, {"name": "prod", "input_coords": {"source": "step", "ref": "prev"}})
    _, s = st._find_step(sid)
    assert s.input_coords.source == "step" and s.input_coords.ref == "prev"


def test_remove_topology_clears_step_binding():
    st = _store()
    tid = st.add_topology("wt.prmtop", "normal")
    pid = st.add_phase("Prod", "production")
    sid = st.add_step(pid, {"name": "prod", "topology": tid})
    st.remove_topology(tid)
    _, step = st._find_step(sid)
    assert step.topology is None


def test_delete_phase_reassigns_steps_to_neighbour():
    st = _store()
    p_min = st.add_phase("Min", "minimization")
    p_prod = st.add_phase("Prod", "production")
    st.add_step(p_min, {"name": "min"})
    st.add_step(p_prod, {"name": "prod_001"})
    st.delete_phase(p_min, reassign_to=p_prod)
    assert [p.id for p in st.get().simulation.phases] == [p_prod]
    assert [s.name for s in st._find_phase(p_prod).steps] == ["prod_001", "min"]
