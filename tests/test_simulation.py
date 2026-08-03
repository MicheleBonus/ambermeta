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
    crosses_lineage, iter_steps, predecessors, relink_restarts, repair_dangling_refs,
    resolve_input_coords, same_lineage,
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


# --- run lineages: the tag a step carries -----------------------------------

def test_lineage_round_trips_through_the_v2_payload():
    sim = _chain()
    for step, tag in zip(sim.phases[0].steps, ["rep1", "rep1", "rep2"]):
        step.lineage = tag
    payload = simulation_to_payload(sim)
    assert [s["lineage"] for s in payload["steps"]] == ["rep1", "rep1", "rep2"]
    assert payload_to_simulation(payload) == sim


def test_a_numeric_lineage_tag_loads_as_a_string():
    """`lineage: 1` is a reasonable thing to hand-write for a numerically named replica.

    YAML and JSON both hand it back as an int, and an int tag would bucket separately from
    the "1" the same document might carry elsewhere — two members where the author meant
    one — besides breaking the first caller that sorts or joins tags.
    """
    payload = simulation_to_payload(_chain())
    payload["steps"][0]["lineage"] = 1
    payload["steps"][1]["lineage"] = "1"
    steps = [s for p in payload_to_simulation(payload).phases for s in p.steps]
    assert steps[0].lineage == "1" and steps[1].lineage == "1"
    assert steps[0].lineage == steps[1].lineage, "an int tag must not split a member"


def test_an_empty_lineage_tag_loads_as_untagged():
    """"" is how the GUI clears a step slot. Kept verbatim it would round-trip as a
    nameless member, so a hand-edited manifest would grow a lineage nobody declared."""
    sim = _chain()
    sim.phases[0].steps[0].lineage = "rep1"
    payload = simulation_to_payload(sim)
    payload["steps"][1]["lineage"] = ""
    back = payload_to_simulation(payload)
    assert [s.lineage for _, s in iter_steps(back)] == ["rep1", None, None]
    assert "lineage" not in simulation_to_payload(back)["steps"][1]


def test_lineage_survives_the_legacy_restart_path_rewrite():
    """_adopt_legacy_restart_paths rebuilds InputCoords wholesale on every load, which is
    why the tag lives on the Step: anything stored on the coords is dropped here."""
    sim = _chain()
    for step in sim.phases[0].steps:
        step.lineage = "rep1"
    payload = simulation_to_payload(sim)
    # The pre-`rst` spelling: the resolved restart carried on the consuming step.
    payload["steps"][1]["input_coords"] = {
        "source": "step", "ref": "st_0", "path": "equil/01_min.rst"}
    back = payload_to_simulation(payload)
    steps = [s for _, s in iter_steps(back)]
    assert steps[1].input_coords == InputCoords(source="step", ref="st_0")   # rewritten
    assert [s.lineage for s in steps] == ["rep1", "rep1", "rep1"]


# --- the chain-maintenance invariant ----------------------------------------
# No automatic operation may create an input_coords.ref crossing a declared boundary.

def _replicas():
    """Two tagged replicas of two chunks each, in replica-major document order."""
    return Simulation(
        starting_structure="wt.crd",
        phases=[Phase(id="ph_0", name="Production", role="production", steps=[
            Step(id="a1", name="rep1/prod_0001", lineage="rep1", rst="rep1/prod_0001.rst",
                 input_coords=InputCoords(source="starting_structure")),
            Step(id="a2", name="rep1/prod_0002", lineage="rep1", rst="rep1/prod_0002.rst",
                 input_coords=InputCoords(source="step", ref="a1")),
            Step(id="b1", name="rep2/prod_0001", lineage="rep2", rst="rep2/prod_0001.rst",
                 input_coords=InputCoords(source="starting_structure")),
            Step(id="b2", name="rep2/prod_0002", lineage="rep2", rst="rep2/prod_0002.rst",
                 input_coords=InputCoords(source="step", ref="b1")),
        ])],
    )


def _producer_of(sim):
    """{step name: what it continues from}, resolving refs to names."""
    by_id = {s.id: s for _, s in iter_steps(sim)}
    out = {}
    for _, s in iter_steps(sim):
        ic = s.input_coords
        out[s.name] = (by_id[ic.ref].name if ic.source == "step" and ic.ref in by_id
                       else ic.source)
    return out


def _has_cycle(sim):
    by_id = {s.id: s for _, s in iter_steps(sim)}
    for _, start in iter_steps(sim):
        seen, cur = set(), start
        while cur and cur.input_coords.source == "step" and cur.input_coords.ref in by_id:
            if cur.id in seen:
                return True
            seen.add(cur.id)
            cur = by_id[cur.input_coords.ref]
    return False


def test_reordering_a_multi_member_document_changes_no_link():
    """Adjacency means provenance in a one-member document and nowhere else.

    Every attempt to re-derive links from order in a multi-member document fabricated
    something: while `predecessors` was document-order and the guard was member-scoped, a
    reversal left both of a member's chunks claiming its first step; making both
    member-scoped closed that but the untagged side stayed a wildcard, and one drag of a
    shared prep step then produced three false edges. The order steps appear in is a view —
    `discover` emits them phase-major, so a member's steps are not even contiguous — and
    the rule that survives is to leave declared provenance alone.
    """
    sim = _replicas()
    phase = sim.phases[0]
    was = _producer_of(sim)
    before = predecessors(sim)
    phase.steps.reverse()
    relink_restarts(sim, before)

    assert _producer_of(sim) == was
    chained = [v for v in was.values() if v != "starting_structure"]
    assert len(chained) == len(set(chained)), "two steps claim the same producer"


def test_no_reordering_can_close_a_cycle_in_a_multi_lineage_document():
    """Reversing the phase list used to close `min -> prod -> min`.

    A cycle saved to disk and validated `ok: true` is the same class of false claim this
    feature exists to remove, so it is asserted directly rather than inferred from the
    absence of cross-tag refs.

    TWO members, phase-major — the shape `discover` actually emits. One member alone
    cannot reproduce it: document order and member order agree, so the two halves of
    `relink_restarts` never disagree and the bug is invisible.
    """
    sim = Simulation(
        starting_structure="wt.crd",
        phases=[
            Phase(id="ph_m", name="Min", role="minimization", steps=[
                Step(id="m1", name="rep1/min", lineage="rep1", rst="rep1/min.rst",
                     input_coords=InputCoords(source="starting_structure")),
                Step(id="m2", name="rep2/min", lineage="rep2", rst="rep2/min.rst",
                     input_coords=InputCoords(source="starting_structure")),
            ]),
            Phase(id="ph_p", name="Prod", role="production", steps=[
                Step(id="p1", name="rep1/prod", lineage="rep1", rst="rep1/prod.rst",
                     input_coords=InputCoords(source="step", ref="m1")),
                Step(id="p2", name="rep2/prod", lineage="rep2", rst="rep2/prod.rst",
                     input_coords=InputCoords(source="step", ref="m2")),
            ]),
        ],
    )
    was = _producer_of(sim)
    before = predecessors(sim)
    sim.phases.reverse()
    relink_restarts(sim, before)

    assert not _has_cycle(sim)
    assert _producer_of(sim) == was


def test_predecessors_is_unchanged_for_an_untagged_document():
    """The member-scoping must be invisible where there is one member.

    Untagged steps are a single bucket, so the map has to stay exactly the document order
    it always was — this is what keeps every pre-lineage relink test meaningful rather
    than merely still-passing.
    """
    sim = _chain()
    ids = [s.id for _, s in iter_steps(sim)]
    assert predecessors(sim) == {sid: (ids[i - 1] if i else None)
                                 for i, sid in enumerate(ids)}


def _fan_out():
    """One shared equilibration, then three tagged replicas of two chunks each."""
    return Simulation(
        starting_structure="wt.crd",
        phases=[
            Phase(id="ph_e", name="Equil", role="equilibration", steps=[
                Step(id="eq", name="common/equil",
                     input_coords=InputCoords(source="starting_structure"),
                     rst="common/equil.rst")]),
            Phase(id="ph_p", name="Production", role="production", steps=[
                s for tag in ("rep1", "rep2", "rep3")
                for s in (
                    Step(id=f"{tag}_1", name=f"{tag}/prod_0001", lineage=tag,
                         input_coords=InputCoords(source="step", ref="eq"),
                         rst=f"{tag}/prod_0001.rst"),
                    Step(id=f"{tag}_2", name=f"{tag}/prod_0002", lineage=tag,
                         input_coords=InputCoords(source="step", ref=f"{tag}_1"),
                         rst=f"{tag}/prod_0002.rst"),
                )]),
        ],
    )


def _cross_lineage_refs(sim):
    """Every link claiming one declared member continued from another."""
    by_id = {s.id: s for _, s in iter_steps(sim)}
    out = []
    for _, step in iter_steps(sim):
        ic = step.input_coords
        producer = by_id.get(ic.ref) if ic.source == "step" else None
        if (producer is not None and producer.lineage and step.lineage
                and producer.lineage != step.lineage):
            out.append((producer.name, step.name))
    return out


def _links(sim):
    return [(s.name, s.input_coords.source, s.input_coords.ref) for _, s in iter_steps(sim)]


def test_interleaving_two_replicas_creates_no_link_between_them():
    """The first branch's failure: reorder to rep1, rep2, rep1, rep2 and each chunk used
    to be re-pointed at the OTHER replica's chunk — two fabricated continuations."""
    sim = _replicas()
    phase = sim.phases[0]
    before = predecessors(sim)
    phase.steps = [phase.steps[0], phase.steps[2], phase.steps[1], phase.steps[3]]
    relink_restarts(sim, before)
    assert _cross_lineage_refs(sim) == []
    # Neighbour refused, so each chunk follows its OWN member's order — the link it
    # already had, which the interleave did not change.
    assert _links(sim) == [
        ("rep1/prod_0001", "starting_structure", None),
        ("rep2/prod_0001", "starting_structure", None),
        ("rep1/prod_0002", "step", "a1"),
        ("rep2/prod_0002", "step", "b1"),
    ]


def test_a_replica_head_is_not_promoted_onto_the_replica_now_in_front_of_it():
    """The second branch's failure: it exists so drag-to-front is reversible, and it fires
    on the step that WAS document-first — which is rep1's head in a replica tree."""
    sim = _replicas()
    phase = sim.phases[0]
    before = predecessors(sim)
    phase.steps = [phase.steps[2], phase.steps[3], phase.steps[0], phase.steps[1]]
    relink_restarts(sim, before)
    assert _cross_lineage_refs(sim) == []
    assert phase.steps[2].input_coords == InputCoords(source="starting_structure")


def test_a_shared_equilibration_that_is_deleted_does_not_serialise_the_replicas():
    """Three members reading one restart, minus that restart, used to become one 6-step
    serial chain: rep1 -> rep2 -> rep3. The exact false edge this model exists to remove,
    manufactured by the tool while tidying up after a delete."""
    sim = _fan_out()
    del sim.phases[0].steps[0]
    repair_dangling_refs(sim)
    assert _cross_lineage_refs(sim) == []
    assert [(n, src) for n, src, _ in _links(sim)] == [
        ("rep1/prod_0001", "starting_structure"), ("rep1/prod_0002", "step"),
        ("rep2/prod_0001", "starting_structure"), ("rep2/prod_0002", "step"),
        ("rep3/prod_0001", "starting_structure"), ("rep3/prod_0002", "step"),
    ]
    # Each member keeps its own internal chain; only the link to the dead parent is gone.
    assert [s.input_coords.ref for _, s in iter_steps(sim) if s.input_coords.ref] == \
        ["rep1_1", "rep2_1", "rep3_1"]


def test_deleting_a_parent_several_members_read_is_reported_not_papered_over():
    sim = _fan_out()
    del sim.phases[0].steps[0]
    notes = repair_dangling_refs(sim)
    assert len(notes) == 1
    assert "rep1, rep2, rep3" in notes[0] and "3 runs" in notes[0]


def test_the_report_does_not_call_a_re_chained_consumer_a_head():
    """A shared parent in the MIDDLE of its consumers' members, not at the front of them.

    Every consumer here has an earlier run of its own to continue from, so none of them
    ends up a head — the warning has to describe what the repair did rather than assume
    the fan-out was rooted at the start of each member.
    """
    sim = _fan_out()
    for step_id in ("rep2_2", "rep3_2"):                 # a hand-set branch off rep1
        next(s for _, s in iter_steps(sim) if s.id == step_id).input_coords = \
            InputCoords(source="step", ref="rep1_2")
    del sim.phases[1].steps[1]                           # rep1/prod_0002 goes

    notes = repair_dangling_refs(sim)
    assert [s.input_coords.ref for _, s in iter_steps(sim)
            if s.id in ("rep2_2", "rep3_2")] == ["rep2_1", "rep3_1"]
    assert len(notes) == 1 and "rep2, rep3" in notes[0]
    assert "continues from the nearest earlier run of its own lineage" in notes[0]


def test_an_untagged_document_repairs_exactly_as_it_always_did_and_says_nothing():
    """The guarantee the whole feature is priced on: with one member, "the nearest
    preceding step of my own lineage" is simply the step before."""
    sim = _chain()
    phase = sim.phases[0]
    del phase.steps[0]                      # both survivors now reference dead ids
    assert repair_dangling_refs(sim) == []
    assert phase.steps[0].input_coords.source == "starting_structure"
    assert phase.steps[1].input_coords.ref == "st_1"
    # A fan-out inside one member is not a lineage boundary and raises nothing.
    sim = _chain()
    sim.phases[0].steps[2].input_coords = InputCoords(source="step", ref="st_0")
    del sim.phases[0].steps[0]
    assert repair_dangling_refs(sim) == []


def test_a_shared_parent_feeding_one_member_twice_is_not_reported():
    """Two consumers, one tag: the re-chain has an unambiguous answer, so there is
    nothing to warn about and a warning would fire on ordinary chunked runs."""
    sim = _fan_out()
    for _, step in iter_steps(sim):
        step.lineage = "rep1"
    del sim.phases[0].steps[0]
    assert repair_dangling_refs(sim) == []


def test_an_untagged_step_may_be_declared_to_feed_a_lineage():
    """Only two DIFFERENT declared tags are a boundary. A shared equilibration feeding
    three replicas is the commonest layout there is and every edge in it is real — so
    `crosses_lineage`, which judges links a human declared, must permit it.

    That is the *loose* rule and it is right only here. Automatic chaining uses the strict
    one (`same_lineage`), because inferring this same edge from adjacency is what let a
    drag fabricate `rep2/prod_0001 <- common/min_0001`.
    """
    sim = _fan_out()
    eq = sim.phases[0].steps[0]
    for _, step in iter_steps(sim):
        if step.lineage:
            assert not crosses_lineage(eq, step)
            assert not same_lineage(eq, step)


def test_a_swap_inside_one_member_leaves_the_shared_parent_alone():
    """The regression this replaces asserted only that rep1's NEW head still read `eq`.

    It did — and so did the old head, because the loose rule let the head branch re-derive
    a link across the untagged boundary while the member-scoped `before` map froze the
    genuine one. Both of rep1's chunks ended up reading the equilibration, which the
    assertion never looked at.
    """
    sim = _fan_out()
    phase = sim.phases[1]
    was = _producer_of(sim)
    before = predecessors(sim)
    phase.steps = [phase.steps[1], phase.steps[0]] + phase.steps[2:]   # swap rep1's chunks
    relink_restarts(sim, before)

    assert _cross_lineage_refs(sim) == []
    assert _producer_of(sim) == was
    within = [v for k, v in _producer_of(sim).items() if k.startswith("rep1")]
    assert sorted(within) == ["common/equil", "rep1/prod_0001"], (
        "rep1's own chain must survive the swap intact")


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


def test_a_v2_manifest_without_steps_is_reported_as_incomplete_not_foreign(tmp_path):
    """Keying only on "steps" told the owner of a real v2 document — version, topology
    pool, phases and all — that it "is not a v2 manifest" and to rebuild it from the
    directory, which would throw away exactly those phases."""
    from ambermeta.errors import AmberMetaError
    from ambermeta.simulation import load_simulation

    holed = tmp_path / "sim.yaml"
    holed.write_text(
        "version: 2\n"
        "simulation:\n"
        "  topologies:\n"
        "    - {id: top_wt, path: wt.prmtop, kind: normal}\n"
        "  starting_structure: wt.inpcrd\n"
        "phases:\n"
        "  - {id: ph_prod, name: Production, role: production, order: 0}\n",
        encoding="utf-8")

    with pytest.raises(AmberMetaError, match=r"missing its 'steps' list"):
        load_simulation(str(holed))
