# tests/test_gui_core_bridge_sim.py
import json

import pytest

from ambermeta.errors import AmberMetaError
from ambermeta.gui.api import core_bridge
from ambermeta.simulation import (
    Simulation, Phase, Step, Topology, iter_steps, resolve_input_coords,
)


def _sim():
    return Simulation(
        topologies=[Topology(id="t0", path="wt.prmtop", kind="normal")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="p0", name="Min", role="minimization",
                      steps=[Step(id="s0", name="min", topology="t0", mdin="min.in")])],
    )


def test_open_v1_manifest_raises_a_clear_error(tmp_path):
    """The v1 file format is gone; opening one must fail with a clear message, not a crash."""
    v1 = {"global_prmtop": "wt.prmtop",
          "stages": [{"name": "min", "stage_role": "minimization", "mdin": "min.in"},
                     {"name": "prod_001", "stage_role": "production", "mdin": "prod_001.in"}]}
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(v1))
    with pytest.raises(AmberMetaError, match="not a v2 manifest"):
        core_bridge.open_simulation(str(path), str(tmp_path))


def test_save_then_preview_round_trip(tmp_path):
    sim = _sim()
    target = tmp_path / "out.json"
    warnings = core_bridge.save_simulation(sim, str(tmp_path), str(target), "json")
    assert warnings == []
    reloaded = core_bridge.open_simulation(str(target), str(tmp_path))
    assert reloaded == sim
    out = core_bridge.preview_simulation(sim, str(tmp_path), "yaml")
    assert "phases" in out["content"] and out["warnings"] == []


def test_build_suggestions_flags_missing_run_and_hmr():
    sim = Simulation(
        topologies=[Topology(id="t0", path="wt.prmtop", kind="normal"),
                    Topology(id="t1", path="wt_hmr.prmtop", kind="hmr")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="p0", name="Production", role="production", steps=[
            Step(id="a", name="prod_0001", topology="t1"),
            Step(id="b", name="prod_0003", topology="t1")])],
    )
    sug = core_bridge.build_suggestions(sim, "/base")
    kinds = {s["kind"] for s in sug}
    assert "missing_run" in kinds        # prod_0002 absent
    assert "topology_confirm" in kinds   # two topologies, one HMR
    assert "starting_structure" in kinds and "role_guess" in kinds
    miss = next(s for s in sug if s["kind"] == "missing_run")
    assert "2" in miss["evidence"]
    assert miss["base"] == "prod"
    assert miss["missing"] == [2]
    assert miss["lineage"] is None


def _members(chunks):
    """One Production phase holding `{tag: [indices]}` as tagged, path-prefixed steps."""
    steps = [Step(id=f"{tag}_{i}", name=f"{tag}/prod_{i:04d}", lineage=tag)
             for tag, idxs in chunks.items() for i in idxs]
    return Simulation(phases=[Phase(id="p0", name="Production", role="production",
                                    steps=steps)])


def _missing_run(sim):
    return [s for s in core_bridge.build_suggestions(sim, "/base")
            if s["kind"] == "missing_run"]


def test_an_untagged_document_keeps_the_card_it_always_had():
    # The wording is the guarantee, not just the count: an untagged document must read
    # exactly as it did before members existed.
    sim = Simulation(phases=[Phase(id="p0", name="Production", role="production", steps=[
        Step(id="a", name="prod_0001"), Step(id="b", name="prod_0004")])])
    card, = _missing_run(sim)
    assert card["title"] == "prod sequence is missing member(s) 2, 3"
    assert card["evidence"] == "present members of 'prod' skip index(es) 2, 3"
    assert card["base"] == "prod"


def test_a_crashed_replica_is_reported_once_and_scoped_to_the_short_member():
    sim = _members({"rep1": [1, 2, 3], "rep2": [1], "rep3": [1, 2, 3]})
    card, = _missing_run(sim)
    assert card["lineage"] == "rep2"
    assert card["base"] == "prod"          # the bare base the canvas matches a ghost on
    assert card["missing"] == [2, 3]
    assert card["title"] == "rep2/prod sequence is missing member(s) 2, 3"
    assert "skip" not in card["evidence"]  # it stopped; it did not skip


def test_a_dot_numbered_crashed_replica_reaches_the_card(dot_numbered_crashed_tree):
    """End to end, from a directory on disk rather than a hand-built Simulation.

    The unit test on the detector proves the base is parsed; this proves the whole path
    survives — `smart_group_files` keeps the index in the stem, the layout inference tags
    the members, the detector finds rep2 short, and the card carries the bare base and the
    tag the canvas matches a ghost on. Every one of those steps already worked for
    underscores; only the detector's view of the name did not.
    """
    result = core_bridge.discover_draft(str(dot_numbered_crashed_tree), recursive=True)
    card, = [s for s in result["suggestions"] if s["kind"] == "missing_run"]
    assert card["lineage"] == "rep2"
    assert card["base"] == "prod"
    assert card["missing"] == [2, 3]


def test_members_numbered_from_different_offsets_produce_no_card():
    assert _missing_run(_members({"rep1": [1, 2], "rep2": [11, 12]})) == []


def test_a_complete_ensemble_produces_no_card():
    assert _missing_run(_members({"rep1": [1, 2], "rep2": [1, 2], "rep3": [1, 2]})) == []


def test_continuity_gap_suggestions_are_step_scoped():
    # Driven by the structured per-stage `continuity` list, not fuzzy warning text.
    flat = [{"step_id": "a"}, {"step_id": "b"}]
    stage_issues = [{"continuity": []},
                    {"continuity": ["Observed gap 20 ps exceeds expected 5 ps."]}]
    out = core_bridge._continuity_gap_suggestions(flat, stage_issues)
    assert len(out) == 1
    assert out[0]["step_id"] == "b"
    assert "20" in out[0]["evidence"]

    # A general (non-continuity) warning must NOT produce a continuity suggestion:
    # the classifier reads `continuity`, never `warnings`.
    non_continuity = [{"step_id": "a"}, {"step_id": "b"}]
    non_continuity_issues = [{"continuity": [], "warnings": []},
                             {"continuity": [],
                              "warnings": ["Atom count mismatch across topology and coordinates."]}]
    out2 = core_bridge._continuity_gap_suggestions(non_continuity, non_continuity_issues)
    assert out2 == []


def test_continuity_gap_surfaces_note_without_ps_substring():
    # Regression: the real gap warning "Gap detected without stated expectation…" has no
    # "ps" substring; the old text-matcher silently dropped it. It must now surface.
    flat = [{"step_id": "a"}, {"step_id": "b"}]
    stage_issues = [{"continuity": []},
                    {"continuity": ["Gap detected without stated expectation; verify continuity."]}]
    out = core_bridge._continuity_gap_suggestions(flat, stage_issues)
    assert len(out) == 1 and out[0]["step_id"] == "b"


def test_continuity_gap_ignores_healthy_and_info_notes():
    # A satisfied transition ("within expected window") is INFO-prefixed at the source and
    # excluded upstream; even if one slips through, the classifier drops INFO defensively.
    flat = [{"step_id": "a"}, {"step_id": "b"}]
    stage_issues = [{"continuity": []},
                    {"continuity": ["INFO: Observed gap 5 ps is within expected window (5±1 ps)."]}]
    out = core_bridge._continuity_gap_suggestions(flat, stage_issues)
    assert out == []


def test_discover_draft_on_real_fixtures(sample_md_data_dir):
    out = core_bridge.discover_draft(str(sample_md_data_dir), recursive=False)
    sim = out["simulation"]
    # the .top topology is in the pool
    assert any(t.path.endswith(".top") for t in sim.topologies)
    # ntp_prod_000X.mdin/.mdout runs became steps
    step_names = [s.name for p in sim.phases for s in p.steps]
    assert any(n.startswith("ntp_prod_000") for n in step_names)
    # the single-frame .crd is picked as the starting structure, not a run
    assert sim.starting_structure and sim.starting_structure.endswith(".crd")
    assert not any(n.endswith("6NAG") for n in step_names)
    # first step reads the starting structure; a later one chains from a step
    flat = [s for p in sim.phases for s in p.steps]
    assert flat[0].input_coords.source == "starting_structure"
    if len(flat) > 1:
        assert flat[1].input_coords.source == "step"
        assert flat[1].input_coords.ref == flat[0].id
        # The restart lives on the step that WRITES it, not copied onto its consumer,
        # and resolving the link still yields a real file for continuity to read.
        assert flat[1].input_coords.path is None
        assert flat[0].rst and flat[0].rst.endswith(".rst")
        assert resolve_input_coords(sim, flat[1]) == flat[0].rst
    assert isinstance(out["suggestions"], list)


# ---------------------------------------------------------------------------
# discover_draft on a replica tree: one chain per member, one phase per role
# ---------------------------------------------------------------------------

def _edges(sim):
    """(step name, what it reads) in document order, with refs resolved to names."""
    by_id = {s.id: s for p in sim.phases for s in p.steps}
    return [(s.name, by_id[s.input_coords.ref].name
             if s.input_coords.source == "step" else s.input_coords.source)
            for p in sim.phases for s in p.steps]


def test_discover_draft_chains_within_each_lineage_and_never_across(replica_tree):
    """The failure design section 1 opens with, in the tree that produces it.

    Before this fix `discover_draft` threaded one flat `prev_step_id` over `_ordered_stems`,
    which is replica-major, so the observed edges included `rep2/heat_0001 <- rep1/prod_0002`
    and `rep3/heat_0001 <- rep2/prod_0002`: AmberMeta asserting that replica 2 continued
    from a restart file in replica 1's directory. Note the boundary edge is heat<-prod, not
    prod<-prod — `heat` natural-sorts before `min`, so the first run of each replica in
    document order is its heating.

    Listed phase-major, which is what the grouping below makes document order: the members
    interleave, and the chain still never leaves one.
    """
    sim = core_bridge.discover_draft(str(replica_tree), recursive=True)["simulation"]

    assert _edges(sim) == [
        ("rep1/heat_0001", "starting_structure"),
        ("rep2/heat_0001", "starting_structure"),
        ("rep3/heat_0001", "starting_structure"),
        ("rep1/min_0001", "rep1/heat_0001"),
        ("rep2/min_0001", "rep2/heat_0001"),
        ("rep3/min_0001", "rep3/heat_0001"),
        ("rep1/prod_0001", "rep1/min_0001"),
        ("rep1/prod_0002", "rep1/prod_0001"),
        ("rep2/prod_0001", "rep2/min_0001"),
        ("rep2/prod_0002", "rep2/prod_0001"),
        ("rep3/prod_0001", "rep3/min_0001"),
        ("rep3/prod_0002", "rep3/prod_0001"),
    ]
    # Three heads, one per member — not one globally first step and two false edges.
    assert sum(1 for _, reads in _edges(sim) if reads == "starting_structure") == 3


def test_discover_draft_tags_every_run_with_its_replica_directory(replica_tree):
    sim = core_bridge.discover_draft(str(replica_tree), recursive=True)["simulation"]
    assert [s.lineage for p in sim.phases for s in p.steps] == (
        ["rep1", "rep2", "rep3"] * 2
        + ["rep1", "rep1", "rep2", "rep2", "rep3", "rep3"])


def test_discover_draft_groups_same_role_steps_from_every_lineage_into_one_phase(replica_tree):
    """Nine phases become three.

    `_ordered_stems` is replica-major and the contiguous-role rule opens a phase per role
    change, so this tree previously rendered nine phases — three separately named
    "Minimization", each holding one run — and the canvas had nowhere to show a member.
    """
    sim = core_bridge.discover_draft(str(replica_tree), recursive=True)["simulation"]

    assert [(p.name, p.role, [s.name for s in p.steps]) for p in sim.phases] == [
        ("Heating", "heating",
         ["rep1/heat_0001", "rep2/heat_0001", "rep3/heat_0001"]),
        ("Minimization", "minimization",
         ["rep1/min_0001", "rep2/min_0001", "rep3/min_0001"]),
        ("Production", "production",
         ["rep1/prod_0001", "rep1/prod_0002", "rep2/prod_0001",
          "rep2/prod_0002", "rep3/prod_0001", "rep3/prod_0002"]),
    ]


def test_discover_draft_opens_a_new_phase_when_a_role_recurs(recurring_role_tree):
    """Grouping across members must not reorder the steps inside one.

    Keyed on the role alone, the second minimisation of a min -> heat -> min member was
    merged into that role's FIRST phase, so the member's steps came out of the document
    as min, min, heat, prod. A recurrence that is not contiguous is a different phase of
    the protocol and opens one.
    """
    sim = core_bridge.discover_draft(str(recurring_role_tree), recursive=True)["simulation"]

    assert [(p.name, p.role, [s.name for s in p.steps]) for p in sim.phases] == [
        ("Minimization", "minimization", ["rep1/01_min", "rep2/01_min"]),
        ("Heating", "heating", ["rep1/02_heat", "rep2/02_heat"]),
        ("Minimization", "minimization", ["rep1/03_min", "rep2/03_min"]),
        ("Production", "production", ["rep1/04_prod", "rep2/04_prod"]),
    ]


def test_discover_draft_never_chains_a_step_to_a_later_one(recurring_role_tree):
    """The consequence the reordering had, stated as the property it violated.

    Every restart is written before it is read, so a chain edge must always point
    backwards in document order. Hoisting `03_min` next to `01_min` left it reading the
    `02_heat` that now followed it — and continuity compares consecutive *document*
    stages, so the pairs it checked were no longer the pairs that ran.
    """
    sim = core_bridge.discover_draft(str(recurring_role_tree), recursive=True)["simulation"]
    flat = [s for p in sim.phases for s in p.steps]
    position = {step.id: index for index, step in enumerate(flat)}

    forward_only = [(step.name, flat[position[step.input_coords.ref]].name)
                    for step in flat
                    if step.input_coords.source == "step"
                    and position[step.input_coords.ref] > position[step.id]]
    assert forward_only == []


def test_discover_draft_keeps_the_untagged_prep_chain_out_of_the_replicas(campaign_tree):
    """Shared prep beside three replicas — the layout design section 6 is written around.

    The untagged runs are one bucket with one chain of their own, and no replica head is
    chained to the prep run that happens to precede it in document order. Each head reads
    the starting structure instead: which prep run actually produced it is chain evidence
    the mdout header carries and this scan does not read, and inventing the edge is the
    class of claim this PR exists to stop.
    """
    sim = core_bridge.discover_draft(str(campaign_tree), recursive=True)["simulation"]

    assert _edges(sim) == [
        ("common/equil_0001", "starting_structure"),
        ("common/heat_0001", "common/equil_0001"),
        ("common/min_0001", "common/heat_0001"),
        ("rep1/prod_0001", "starting_structure"),
        ("rep1/prod_0002", "rep1/prod_0001"),
        ("rep2/prod_0001", "starting_structure"),
        ("rep2/prod_0002", "rep2/prod_0001"),
        ("rep3/prod_0001", "starting_structure"),
        ("rep3/prod_0002", "rep3/prod_0001"),
    ]
    assert [s.lineage for p in sim.phases for s in p.steps] == (
        [None] * 3 + ["rep1", "rep1", "rep2", "rep2", "rep3", "rep3"])


def test_discover_draft_reports_the_inferred_grouping_as_applied(replica_tree):
    """Decision 7: the inference is a claim, so it is surfaced rather than performed
    silently. `[applied]`, not `needs_you` — there is nothing for the user to accept."""
    out = core_bridge.discover_draft(str(replica_tree), recursive=True)
    sug = next(s for s in out["suggestions"] if s["kind"] == "lineage_group")
    assert sug["severity"] == "applied"
    assert "3" in sug["title"]
    assert all(tag in sug["evidence"] for tag in ("rep1", "rep2", "rep3"))


def test_the_grouping_card_accounts_for_the_runs_that_carry_no_tag(campaign_tree):
    """Three of the canonical campaign's nine runs are shared prep and stay untagged.

    The count is of *declared* members, so a card that named only those would say "3"
    about a document holding nine runs and leave the reader to assume the other six —
    there are six — were what the three lineages hold.
    """
    out = core_bridge.discover_draft(str(campaign_tree), recursive=True)
    sug = next(s for s in out["suggestions"] if s["kind"] == "lineage_group")
    assert sug["title"] == "Runs carry 3 declared lineage(s)"
    assert sug["evidence"] == ("rep1: 2 run(s); rep2: 2 run(s); rep3: 2 run(s); "
                               "no lineage: 3 run(s)")


def test_discover_reports_the_replica_that_stopped_early(crashed_replica_tree):
    """End to end: layout inference tags the runs, and the tag is what lets the detector
    see that rep2 is short. Before this keying the whole tree pooled into one `prod`
    family running 1-3, which is complete, so the crash produced no finding at all."""
    out = core_bridge.discover_draft(str(crashed_replica_tree), recursive=True)
    card, = [s for s in out["suggestions"] if s["kind"] == "missing_run"]
    assert card["lineage"] == "rep2"
    assert card["base"] == "prod" and card["missing"] == [2, 3]


# ---------------------------------------------------------------------------
# discover_draft never invents a cross-directory continuation (P1.3)
# ---------------------------------------------------------------------------

def test_discover_draft_never_chains_across_a_run_directory(sys021_tree):
    """The nine edges this removes were the whole reason a 1097-run campaign published as
    one serial 5.055 us trajectory. They self-validated, too: resolve_input_coords hands a
    source="step" consumer the PRODUCER'S OWN restart, so _check_stage_pair compared a
    run's end time against its own output and saw observed_gap_ps = 0.0 every time."""
    sim = core_bridge.discover_draft(str(sys021_tree), recursive=True)["simulation"]
    by_id = {s.id: s for _, s in iter_steps(sim)}
    for _, step in iter_steps(sim):
        if step.input_coords and step.input_coords.source == "step":
            producer = by_id[step.input_coords.ref]
            assert producer.name.rpartition("/")[0] == step.name.rpartition("/")[0], (
                f"{step.name} reads a restart written by {producer.name}")


def test_discover_draft_still_chains_within_one_directory(sys021_tree):
    """The within-directory chain is what makes a chunked run a chain, and it cannot be
    wrong about membership because it never leaves the directory. Removing it would gut the
    default output of every existing single-replica project."""
    sim = core_bridge.discover_draft(str(sys021_tree), recursive=True)["simulation"]
    by_id = {s.id: s for _, s in iter_steps(sim)}
    edges = {s.name: by_id[s.input_coords.ref].name
             for _, s in iter_steps(sim)
             if s.input_coords and s.input_coords.source == "step"}
    assert edges["prod/01/nvt_prod_0002"] == "prod/01/nvt_prod_0001"
    assert edges["prod/01/nvt_prod_0003"] == "prod/01/nvt_prod_0002"
    # The head of a directory reads the starting structure, not the previous directory.
    # Checked on prod/02, not prod/01: prod/01 also holds the stray `cpptraj.in` (see
    # sys021_tree's docstring), which natural-sorts ahead of `nvt_prod_0001` and is that
    # directory's real first stem instead -- a pre-existing, separately-tested quirk
    # (test_protocol_queued.py) this test is not about. prod/02 shows the same
    # directory-boundary property without it.
    assert "prod/02/nvt_prod_0001" not in edges


def test_discover_draft_leaves_an_ambiguous_tree_untagged_and_unchained(nested_sweep_tree):
    """A nested sweep varies in two segments at once, so nothing is tagged. Each of its four
    stems is also the only run in its own directory, and a directory boundary is the only
    boundary discovery can justify — so the tree now yields four single-run directories with
    no edges at all, tagged or not. It no longer matters that these four used to fall into
    one shared UNTAGGED bucket: the bucket stopped being what the chain is keyed on."""
    tree = nested_sweep_tree
    sim = core_bridge.discover_draft(str(tree), recursive=True)["simulation"]

    assert [s.lineage for p in sim.phases for s in p.steps] == [None] * 4
    assert len(sim.phases) == 1
    assert _edges(sim) == [
        ("300K/rep1/prod_0001", "starting_structure"),
        ("300K/rep2/prod_0001", "starting_structure"),
        ("310K/rep1/prod_0001", "starting_structure"),
        ("310K/rep2/prod_0001", "starting_structure"),
    ]
    assert not any(s["kind"] == "lineage_group"
                   for s in core_bridge.build_suggestions(sim, str(tree)))


def test_validate_simulation_reports_missing_files_and_suggestions(tmp_path):
    (tmp_path / "prod_0001.in").write_text("&cntrl\nimin=0, nstlim=1000, dt=0.002,\n/\n")
    sim = Simulation(
        topologies=[Topology(id="t0", path="wt.prmtop", kind="normal")],
        phases=[Phase(id="p0", name="Production", role="production", steps=[
            Step(id="a", name="prod_0001", topology="t0", mdin="prod_0001.in"),
            Step(id="b", name="prod_0003", topology="t0", mdin="prod_0003.in")])],
    )
    settings = {"strict_validation": True, "allow_gaps": False}
    report = core_bridge.validate_simulation(sim, settings, str(tmp_path))
    assert "stage_issues" in report and "suggestions" in report
    # prod_0003.in and the topology don't exist -> missing-file errors surface
    all_errors = [e for si in report["stage_issues"] for e in si["errors"]]
    assert any("missing" in e for e in all_errors)
    assert any(s["kind"] == "missing_run" for s in report["suggestions"])


def test_read_file_head_truncates(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("A" * 10000)
    out = core_bridge.read_file_head(str(f), max_bytes=100)
    assert out["truncated"] is True and len(out["content"]) == 100


def test_dead_flat_functions_are_gone():
    assert not hasattr(core_bridge, "discover")          # replaced by discover_draft
    assert not hasattr(core_bridge, "classify_topologies")
    assert not hasattr(core_bridge, "open_manifest")
