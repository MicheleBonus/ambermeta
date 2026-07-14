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
