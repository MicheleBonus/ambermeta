# tests/test_gui_document.py
import json

from ambermeta.gui.api.document import DocumentStore
from ambermeta.simulation import (
    Simulation, Phase, Step, Topology, InputCoords, resolve_input_coords,
)


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


def test_assign_file_all_targets():
    st = _store()
    pid = st.add_phase("Prod", "production")
    s1 = st.add_step(pid, {"name": "prod_001"})
    s2 = st.add_step(pid, {"name": "prod_002"})

    st.assign_file("wt.prmtop", "pool", kind="normal")
    assert st.get().simulation.topologies[0].path == "wt.prmtop"

    st.assign_file("wt.inpcrd", "starting_structure")
    assert st.get().simulation.starting_structure == "wt.inpcrd"

    st.assign_file("wt_hmr.prmtop", "phase_topology", target_id=pid, kind="hmr")
    tid = st._find_step(s1)[1].topology
    assert tid is not None and st._find_step(s2)[1].topology == tid   # cascaded to all steps

    st.assign_file("wt.prmtop", "step_topology", target_id=s2)
    assert st._find_step(s2)[1].topology == st.get().simulation.topologies[0].id

    st.assign_file("prod_001.in", "step_slot", target_id=s1, slot="mdin")
    assert st._find_step(s1)[1].mdin == "prod_001.in"


def test_assign_file_bad_target_raises():
    st = _store()
    import pytest
    with pytest.raises(ValueError):
        st.assign_file("x", "bogus")
    with pytest.raises(ValueError):
        st.assign_file("x", "step_slot", target_id=None, slot="mdin")


# --- deleting and clearing things --------------------------------------------

def _chained_store():
    """A store holding min -> nvt -> npt, chained through each run's restart."""
    st = _store()
    sim = Simulation(
        starting_structure="cryst/wt.crd",
        topologies=[Topology(id="t0", path="wt.prmtop", kind="normal"),
                    Topology(id="t1", path="wt_hmr.prmtop", kind="hmr")],
        phases=[Phase(id="p0", name="Equil", role="equilibration", steps=[
            Step(id="s0", name="01_min", topology="t0",
                 input_coords=InputCoords(source="starting_structure"), rst="equil/01_min.rst"),
            Step(id="s1", name="02_nvt", topology="t0",
                 input_coords=InputCoords(source="step", ref="s0"), rst="equil/02_nvt.rst"),
            Step(id="s2", name="03_npt", topology="t0",
                 input_coords=InputCoords(source="step", ref="s1"), rst="equil/03_npt.rst"),
        ])],
    )
    st.replace(simulation=sim, settings=st.get().settings, manifest_path=None,
               dirty=False, reset_history=True)
    return st


def test_deleting_a_step_rechains_whoever_continued_from_it():
    st = _chained_store()
    st.delete_step("s1")
    assert st._find_step("s2")[1].input_coords.ref == "s0"   # not a dead id
    st.undo()
    assert st._find_step("s2")[1].input_coords.ref == "s1"


def test_deleting_a_phase_rechains_steps_that_pointed_into_it():
    st = _chained_store()
    pid = st.add_phase("Prod", "production")
    sid = st.add_step(pid, {"name": "prod", "input_coords": {"source": "step", "ref": "s2"}})
    st.delete_phase("p0")
    assert st._find_step(sid)[1].input_coords.source == "starting_structure"


def test_response_carries_the_resolved_input_coordinates():
    steps = _chained_store().to_response().simulation.phases[0].steps
    assert steps[0].resolved_input_coords == "cryst/wt.crd"
    assert steps[1].resolved_input_coords == "equil/01_min.rst"
    assert steps[1].rst == "equil/02_nvt.rst"


def test_reordering_steps_relinks_the_chain():
    st = _chained_store()
    st.reorder_steps("p0", ["s0", "s2", "s1"])
    assert st._find_step("s2")[1].input_coords.ref == "s0"
    assert st._find_step("s1")[1].input_coords.ref == "s2"
    st.reorder_steps("p0", ["s2", "s0", "s1"])
    assert st._find_step("s2")[1].input_coords.source == "starting_structure"


def test_relinking_is_off_when_the_user_turns_it_off():
    st = _chained_store()
    st.patch_settings({"auto_link_restarts": False})
    st.reorder_steps("p0", ["s2", "s0", "s1"])
    assert st._find_step("s2")[1].input_coords.ref == "s1"   # untouched


def test_appending_a_step_continues_from_the_one_before_it():
    st = _chained_store()
    sid = st.add_step("p0", {"name": "04_prod"})
    assert st._find_step(sid)[1].input_coords.ref == "s2"


def test_an_explicit_starting_structure_survives_appending():
    st = _chained_store()
    sid = st.add_step("p0", {"name": "04_prod",
                             "input_coords": {"source": "starting_structure"}})
    assert st._find_step(sid)[1].input_coords.source == "starting_structure"


def test_phase_topology_can_be_set_and_cleared_in_one_control():
    st = _chained_store()
    st.update_phase("p0", {"topology": "t1"})
    assert [s.topology for s in st._find_phase("p0").steps] == ["t1", "t1", "t1"]
    st.update_phase("p0", {"topology": None})
    assert [s.topology for s in st._find_phase("p0").steps] == [None, None, None]


def test_phase_topology_rejects_an_unknown_id_without_mutating():
    import pytest
    st = _chained_store()
    with pytest.raises(KeyError):
        st.update_phase("p0", {"topology": "nope"})
    assert [s.topology for s in st._find_phase("p0").steps] == ["t0", "t0", "t0"]
    assert st.to_response().can_undo is False       # nothing was snapshotted


def test_gaps_are_cleared_by_an_explicit_null_and_zero_is_a_real_value():
    st = _chained_store()
    st.update_step("s0", {"expected_gap_ps": 20.0, "gap_tolerance_ps": 1.0})
    assert st._find_step("s0")[1].expected_gap_ps == 20.0
    st.update_step("s0", {"expected_gap_ps": 0.0})
    assert st._find_step("s0")[1].expected_gap_ps == 0.0
    st.update_step("s0", {"expected_gap_ps": None})
    assert st._find_step("s0")[1].expected_gap_ps is None
    assert st._find_step("s0")[1].gap_tolerance_ps == 1.0    # absent means leave alone


def test_the_restart_slot_is_set_and_cleared_like_any_other_file():
    st = _chained_store()
    st.assign_file("equil/other.rst", "step_slot", target_id="s0", slot="rst")
    assert st._find_step("s0")[1].rst == "equil/other.rst"
    st.update_step("s0", {"rst": ""})
    assert st._find_step("s0")[1].rst is None
    # Its consumer no longer resolves to a file, but the link itself is intact.
    assert st.to_response().simulation.phases[0].steps[1].resolved_input_coords is None


def test_removing_a_topology_clears_it_off_every_step_and_undoes():
    st = _chained_store()
    st.remove_topology("t0")
    assert [t.id for t in st.get().simulation.topologies] == ["t1"]
    assert [s.topology for s in st._find_phase("p0").steps] == [None, None, None]
    st.undo()
    assert [s.topology for s in st._find_phase("p0").steps] == ["t0", "t0", "t0"]


def test_clearing_the_starting_structure_is_one_undoable_step():
    st = _chained_store()
    st.set_starting_structure(None)
    assert st.get().simulation.starting_structure is None
    st.undo()
    assert st.get().simulation.starting_structure == "cryst/wt.crd"


# --- undo is about content, not about which file it came from ----------------

def test_undo_does_not_rewind_the_save_target():
    st = _chained_store()
    st.mark_saved("/base/a.yaml")
    st.delete_step("s2")
    st.mark_saved("/base/b.yaml")
    st.delete_step("s1")
    st.undo()
    # Undoing an edit must not redirect the next Save back to a.yaml.
    assert st.get().manifest_path == "/base/b.yaml"


def test_undo_leaves_the_document_dirty():
    st = _chained_store()
    st.delete_step("s2")
    st.mark_saved("/base/a.yaml")
    assert st.get().dirty is False
    st.undo()
    # In memory it no longer matches what was written, so the unsaved-changes guard
    # has to stay armed.
    assert st.get().dirty is True


def test_undo_and_redo_report_whether_they_did_anything():
    st = _chained_store()
    assert st.undo() is False and st.redo() is False
    st.delete_step("s2")
    assert st.undo() is True
    assert st.redo() is True


def test_history_is_capped_and_the_oldest_edits_fall_off_the_end():
    st = DocumentStore("/base", history_limit=3)
    pid = st.add_phase("P", "")
    for i in range(6):
        st.update_phase(pid, {"name": f"P{i}"})
    assert len(st._undo) == 3
    # Undoing to the bottom of the cap reaches the third-from-last name, not the first:
    # the earlier states were evicted, and undo stops rather than reporting more to give.
    for _ in range(3):
        st.undo()
    assert st._find_phase(pid).name == "P2"
    assert st.can_undo() is False
    # Everything undone is redoable, and redo walks back to where it started.
    for _ in range(3):
        st.redo()
    assert st._find_phase(pid).name == "P5"


def test_adding_a_topology_twice_yields_one_entry():
    st = _store()
    first = st.add_topology("wt.prmtop", "normal")
    again = st.add_topology("wt.prmtop", "hmr")
    assert again == first
    assert len(st.get().simulation.topologies) == 1


def test_a_phase_cannot_inherit_its_own_steps():
    import pytest
    st = _chained_store()
    with pytest.raises(ValueError):
        st.delete_phase("p0", reassign_to="p0")
    assert len(st._find_phase("p0").steps) == 3   # nothing was moved or lost


# --- regressions found by review of the restart-chain change -----------------

def _legacy_store():
    """The shape the PREVIOUS release wrote: the restart cached on the CONSUMER."""
    st = _store()
    sim = Simulation(
        starting_structure="cryst/wt.crd",
        phases=[Phase(id="p0", name="Prod", role="production", steps=[
            Step(id="a", name="prod_0001",
                 input_coords=InputCoords(source="starting_structure")),
            Step(id="b", name="prod_0002",
                 input_coords=InputCoords(source="step", ref="a", path="prod_0001.rst")),
            Step(id="c", name="prod_0003",
                 input_coords=InputCoords(source="step", ref="b", path="prod_0002.rst")),
        ])],
    )
    st.replace(simulation=sim, settings=st.get().settings, manifest_path=None,
               dirty=False, reset_history=True)
    return st


def test_a_reorder_does_not_erase_a_legacy_documents_only_coordinate_record():
    st = _legacy_store()
    resolved = lambda: [s.resolved_input_coords
                        for s in st.to_response().simulation.phases[0].steps]
    assert resolved() == ["cryst/wt.crd", "prod_0001.rst", "prod_0002.rst"]
    # A no-op drag still runs the relink over every chained step.
    st.reorder_steps("p0", ["a", "b", "c"])
    assert resolved() == ["cryst/wt.crd", "prod_0001.rst", "prod_0002.rst"]


def test_loading_a_legacy_manifest_moves_the_restart_onto_the_step_that_wrote_it(tmp_path):
    from ambermeta.simulation import load_simulation
    (tmp_path / "legacy.json").write_text(json.dumps({
        "version": 2,
        "simulation": {"topologies": [], "starting_structure": "wt.inpcrd"},
        "phases": [{"id": "p0", "name": "Prod", "role": "production", "order": 0}],
        "steps": [
            {"id": "a", "name": "prod_0001", "phase": "p0", "order": 0,
             "input_coords": {"source": "starting_structure"}},
            {"id": "b", "name": "prod_0002", "phase": "p0", "order": 1,
             "input_coords": {"source": "step", "ref": "a", "path": "prod_0001.rst"}},
        ],
    }), encoding="utf-8")
    sim = load_simulation(str(tmp_path / "legacy.json"))
    a, b = sim.phases[0].steps
    assert a.rst == "prod_0001.rst"          # now owned by the step that writes it
    assert b.input_coords.path is None       # and no longer duplicated on the consumer
    assert resolve_input_coords(sim, b) == "prod_0001.rst"


def test_a_step_added_mid_document_is_spliced_into_the_chain():
    st = _chained_store()
    other = st.add_phase("Prod", "production")
    tail = st.add_step(other, {"name": "04_prod"})
    assert st._find_step(tail)[1].input_coords.ref == "s2"

    inserted = st.add_step("p0", {"name": "03b_extra"})
    # The step that used to follow now follows the new one, instead of both claiming s2.
    assert st._find_step(inserted)[1].input_coords.ref == "s2"
    assert st._find_step(tail)[1].input_coords.ref == inserted


def test_a_deliberate_continues_from_survives_an_unrelated_drag():
    st = _chained_store()
    st.update_step("s2", {"input_coords": {"source": "step", "ref": "s0"}})
    st.reorder_steps("p0", ["s1", "s0", "s2"])
    assert st._find_step("s2")[1].input_coords.ref == "s0"   # the user's choice, untouched


def test_adding_a_pooled_path_as_hmr_applies_the_kind_it_was_asked_for():
    st = _store()
    first = st.add_topology("wt.prmtop", "normal")
    again = st.add_topology("wt.prmtop", "hmr")
    assert again == first
    assert st._find_topology(first).kind == "hmr"
    st.undo()
    assert st._find_topology(first).kind == "normal"
