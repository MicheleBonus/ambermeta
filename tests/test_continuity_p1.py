# tests/test_continuity_p1.py
import pytest

from ambermeta.protocol import SimulationStage, SimulationProtocol


class _D:
    def __init__(self, **kw): self.__dict__.update(kw)
class _F:
    def __init__(self, **kw): self.details = _D(**kw)


def _stage(name, *, end=None, start=None, avg_dt=None,
           lineage=None, step_id=None, parent_id=None):
    s = SimulationStage(name=name)
    if end is not None:
        s.mdcrd = _F(time_end=end, avg_dt=avg_dt)
    if start is not None:
        s.inpcrd = _F(time=start)
    s.lineage = lineage
    s.step_id = step_id
    s.parent_id = parent_id
    return s


def test_real_gap_in_long_run_is_not_snapped_to_zero():
    prev = _stage("a", end=1_000_000.0, avg_dt=0.2)
    curr = _stage("b", start=1_000_060.0)          # a real 60 ps gap at 1 us
    proto = SimulationProtocol(stages=[prev, curr])
    proto.validate()
    assert curr.observed_gap_ps == 60.0
    assert any("60" in n for n in curr.continuity)


def test_frame_interval_noise_is_still_tolerated():
    prev = _stage("a", end=100.0, avg_dt=2.0)
    curr = _stage("b", start=100.05)               # 0.05 ps < half a 2 ps frame
    proto = SimulationProtocol(stages=[prev, curr])
    proto.validate()
    assert curr.observed_gap_ps == 0.0


def test_mdout_end_time_used_when_no_trajectory_exact_match():
    prev = SimulationStage(name="a")
    prev.mdout = _F(stats=_D(count=1, time_end=100.0))
    curr = SimulationStage(name="b")
    curr.inpcrd = _F(time=100.0)
    proto = SimulationProtocol(stages=[prev, curr])
    proto.validate()
    assert curr.observed_gap_ps == 0.0
    assert not any("Cannot verify" in n for n in curr.continuity)


def test_mdout_end_time_used_when_no_trajectory_with_gap():
    prev = SimulationStage(name="a")
    prev.mdout = _F(stats=_D(count=1, time_end=100.0))
    curr = SimulationStage(name="b")
    curr.inpcrd = _F(time=120.0)
    proto = SimulationProtocol(stages=[prev, curr])
    proto.validate()
    assert curr.observed_gap_ps == 20.0
    assert any("starts 20 ps after" in n for n in curr.continuity)


def test_no_mdcrd_and_no_valid_mdout_cannot_verify():
    prev = SimulationStage(name="a")
    prev.mdout = _F(stats=_D(count=0, time_end=0.0))
    curr = SimulationStage(name="b")
    curr.inpcrd = _F(time=50.0)
    proto = SimulationProtocol(stages=[prev, curr])
    proto.validate()
    assert any("Cannot verify" in n for n in curr.continuity)
    assert curr.observed_gap_ps is None


# --- continuity is measured per lineage, and every head is measured ------------------
#
# Document order is not experiment order once a manifest holds more than one member:
# replicas interleave, and `discover` now emits them phase-major. Every assertion below
# was first run against the unpartitioned engine and observed to fail, except the two
# that pin unchanged behaviour and say so.

_FAN_OUT_TAGS = ("rep1", "rep2", "rep3")


def _fan_out(*, rep2_resumes_at=200.0, heads_read_the_starting_structure=False):
    """The canonical campaign: one shared equilibration, three two-chunk replicas.

    Every replica leaves the equilibration at 100 ps and runs to 300 ps, so *within* each
    member the times are seamless and *across* members they overlap completely — which is
    exactly what a document-order zip reports as a 200 ps overlap that never happened.

    ``heads_read_the_starting_structure`` drops the producer link the way `discover` does:
    it emits each lineage head as ``starting_structure``, so no producing step exists.
    """
    equil = _stage("common/equil", step_id="eq", end=100.0)
    stages = [equil]
    for tag in _FAN_OUT_TAGS:
        resumes_at = rep2_resumes_at if tag == "rep2" else 200.0
        stages.append(_stage(
            f"{tag}/prod_0001", lineage=tag, step_id=f"{tag}_1",
            parent_id=None if heads_read_the_starting_structure else "eq",
            start=100.0, end=200.0))
        stages.append(_stage(
            f"{tag}/prod_0002", lineage=tag, step_id=f"{tag}_2", parent_id=f"{tag}_1",
            start=resumes_at, end=300.0))
    return stages


def _validated(stages, **kwargs):
    SimulationProtocol(stages=stages).validate(**kwargs)
    return stages


def _problems(stages):
    """Continuity notes that are not INFO — everything the user is asked to act on."""
    return [(s.name, n) for s in stages
            for n in s.continuity if not n.startswith("INFO:")]


def _by_name(stages):
    return {s.name: s for s in stages}


def test_a_fan_out_reports_no_continuity_problem():
    # Before the partition this produced four: an overlap and an unexpected-gap note on
    # each of rep2's and rep3's heads, purely from following the previous replica's tail.
    assert _problems(_validated(_fan_out())) == []


def test_a_lineage_head_is_measured_against_its_producer_not_its_neighbour():
    """Ruling 13.1.2. Partitioning alone would leave all three heads at ``None``.

    ``None`` and an empty continuity list are indistinguishable from "checked and fine",
    so the equilibration that every replica genuinely continues has to be found through
    ``parent_id`` rather than through document adjacency.
    """
    stages = _by_name(_validated(_fan_out()))
    for tag in _FAN_OUT_TAGS:
        assert stages[f"{tag}/prod_0001"].observed_gap_ps == 0.0


def test_a_gap_inside_one_lineage_is_still_detected():
    stages = _validated(_fan_out(rep2_resumes_at=250.0))
    assert _problems(stages) == [
        ("rep2/prod_0002", "Gap detected without stated expectation; verify continuity.")
    ]
    assert _by_name(stages)["rep2/prod_0002"].observed_gap_ps == 50.0


def test_a_head_with_no_producer_says_it_was_not_measured():
    """`discover` gives every head ``starting_structure``, hence no producing step.

    Silence is the one outcome ruled out: an unmeasured head must not look like a
    measured one.
    """
    stages = _validated(_fan_out(heads_read_the_starting_structure=True))
    heads = [s for s in stages if s.name.endswith("prod_0001")]
    assert len(heads) == 3
    for head in heads:
        assert head.observed_gap_ps is None
        assert any("was not measured" in note for note in head.continuity)
    assert _problems(stages) == []


def test_the_untagged_bucket_is_a_member_and_its_head_is_reported_too():
    """The shared equilibration is one partition, not an unpartitioned remainder."""
    equil = _validated(_fan_out())[0]
    assert equil.observed_gap_ps is None
    assert any("was not measured" in note for note in equil.continuity)


def test_a_document_of_single_step_lineages_still_produces_continuity_output():
    """The second half of ruling 13.1.2: a bare partition leaves nothing to read at all."""
    stages = _validated([
        _stage("common/equil", step_id="eq", end=100.0),
        _stage("rep1/prod_0001", lineage="rep1", step_id="a", parent_id="eq",
               start=100.0, end=200.0),
        _stage("rep2/prod_0001", lineage="rep2", step_id="b", parent_id="eq",
               start=100.0, end=200.0),
    ])
    assert [s.observed_gap_ps for s in stages] == [None, 0.0, 0.0]
    assert _problems(stages) == []
    # The invariant that makes the output readable: no stage is left both unmeasured and
    # silent. A clean continuation is measured and says nothing (0.0 is the whole story);
    # an unmeasurable one is unmeasured and says so.
    assert all(s.observed_gap_ps is not None or s.continuity for s in stages)


def test_allow_gaps_is_not_a_substitute_for_the_partition():
    """`--allow-gaps` never touched the half of the damage that mattered.

    It downgrades "Gap detected without stated expectation" to INFO and leaves "Stage
    appears to overlap" alone, so a replica user following the old advice still read two
    fabricated overlaps. Only the partition removes them.
    """
    assert _problems(_validated(_fan_out(), allow_unexpected_gaps=True)) == []


def test_an_untagged_document_keeps_the_flat_neighbour_check():
    """Unchanged behaviour, pinned. This test passes before the partition and after it."""
    stages = _validated([
        _stage("prod_0001", step_id="s1", end=100.0),
        _stage("prod_0002", step_id="s2", parent_id="s1", start=100.0, end=200.0),
        _stage("prod_0003", step_id="s3", parent_id="s2", start=250.0, end=300.0),
    ])
    assert [s.observed_gap_ps for s in stages] == [None, 0.0, 50.0]
    assert _problems(stages) == [
        ("prod_0003", "Gap detected without stated expectation; verify continuity.")
    ]
    # One member means the flat zip already is the whole check, so the document's first
    # stage gains no head note and `summary.json` does not move.
    assert stages[0].continuity == []


def test_the_untagged_prep_chain_keeps_its_own_order_beside_the_replicas():
    """Untagged steps share one bucket, so a shared prep chain is still checked in order.

    One bucket per untagged step would leave three consecutive prep runs unchecked.
    """
    stages = _validated([
        _stage("common/min_0001", step_id="mn", end=50.0),
        _stage("common/heat_0001", step_id="ht", parent_id="mn", start=50.0, end=100.0),
        _stage("common/equil_0001", step_id="eq", parent_id="ht", start=100.0, end=150.0),
        _stage("rep1/prod_0001", lineage="rep1", step_id="a", parent_id="eq",
               start=150.0, end=250.0),
        _stage("rep2/prod_0001", lineage="rep2", step_id="b", parent_id="eq",
               start=150.0, end=250.0),
    ])
    assert [s.observed_gap_ps for s in stages] == [None, 0.0, 0.0, 0.0, 0.0]
    assert _problems(stages) == []


# --- the head check, end to end from the two things that build a document -------------
#
# Everything above hands `SimulationProtocol` stages it built itself, which pins the rule
# but not the two ways a user reaches it. The two routes disagree about the head on
# purpose and both outcomes are load-bearing, so both are pinned here:
#
#   `discover`  refuses to declare the prep -> replica edge, because a restart file lying
#               beside a replica is not evidence of which run read it. Every head it
#               produces therefore has no producer and must SAY SO — ruling 13.1.2 ruled
#               out exactly one outcome, silence, and nothing else pinned that.
#   a manifest  that declares the edge has stated the evidence, and the head is measured
#               against the stage it names rather than against the one that happens to
#               precede it in the document.
#
# Both go through `build_protocol`, which is the object `plan` and the GUI both validate.

from ambermeta.gui.api import core_bridge
from ambermeta.simulation import load_simulation

_ENGINE_SETTINGS = {"strict_validation": True, "allow_gaps": False,
                    "use_relative_paths": True}


def _analysed(sim, base_directory):
    """The `SimulationStage` list the engine validates for a v2 document."""
    return core_bridge.build_protocol(
        core_bridge._flatten_simulation(sim), dict(_ENGINE_SETTINGS),
        str(base_directory)).stages


def _partition_heads(stages):
    """First stage of each membership bucket, recomputed rather than imported.

    Two lines instead of a call to `lineages.buckets`, so a change to the grouping rule
    fails this test instead of being adopted by it.
    """
    heads = {}
    for stage in stages:
        heads.setdefault(stage.lineage or None, stage)
    return heads


def test_every_head_of_a_discovered_campaign_says_it_was_not_measured(campaign_tree):
    """Four members — three replicas plus the untagged prep chain — and four notes.

    `discover` writes each member's first run as `starting_structure`, so none of the four
    heads has a producer to be measured against. That is the intended refusal; the thing
    that must never come back is doing it without a word, which would leave a head at
    `observed_gap_ps = None` and an empty note list, indistinguishable from a head that
    was checked and found clean.
    """
    draft = core_bridge.discover_draft(str(campaign_tree))
    stages = _analysed(draft["simulation"], campaign_tree)

    heads = _partition_heads(stages)
    assert sorted(heads, key=lambda tag: tag or "") == [None, "rep1", "rep2", "rep3"]
    assert heads["rep1"].name == "rep1/prod_0001"
    for tag, head in heads.items():
        assert head.observed_gap_ps is None, tag
        assert any("was not measured" in note for note in head.continuity), (
            tag, head.name, head.continuity)

    # Stated over the whole document rather than over the heads, so a stage that stops
    # being a head cannot slip out of the guarantee: nothing is left both unmeasured and
    # silent, whatever the partition turns out to be.
    assert all(s.observed_gap_ps is not None or s.continuity for s in stages)
    assert _problems(stages) == []


# One equilibration and two replicas, one of them chunked — the smallest document in which
# a head's declared producer and its neighbour in document order are different stages.
_DECLARED_PRODUCER_MANIFEST = """\
version: 2
simulation:
  topologies: []
  starting_structure: start.rst
phases:
  - { id: ph_eq, name: Equilibration, role: equilibration, order: 0 }
  - { id: ph_prod, name: Production, role: production, order: 1 }
steps:
  - id: st_eq
    name: common/equil
    phase: ph_eq
    order: 0
    input_coords: { source: starting_structure }
    mdin: common/equil.mdin
    mdout: common/equil.mdout
    rst: common/equil.rst
  - id: st_a1
    name: rep1/prod_0001
    phase: ph_prod
    order: 0
    lineage: rep1
    input_coords: { source: step, ref: st_eq }
    mdin: rep1/prod_0001.mdin
    mdout: rep1/prod_0001.mdout
    rst: rep1/prod_0001.rst
  - id: st_a2
    name: rep1/prod_0002
    phase: ph_prod
    order: 1
    lineage: rep1
    input_coords: { source: step, ref: st_a1 }
    mdin: rep1/prod_0002.mdin
    mdout: rep1/prod_0002.mdout
    rst: rep1/prod_0002.rst
  - id: st_b1
    name: rep2/prod_0001
    phase: ph_prod
    order: 2
    lineage: rep2
    input_coords: { source: step, ref: st_eq }
    mdin: rep2/prod_0001.mdin
    mdout: rep2/prod_0001.mdout
    rst: rep2/prod_0001.rst
"""

# When each run ended, in picoseconds; its restart carries the same time. Every member
# leaves the equilibration at 100 ps, so within each member the times are seamless and
# rep2's head is 200 ps *behind* the stage that precedes it in the document.
_DECLARED_PRODUCER_END_PS = {
    "common/equil": 100.0,
    "rep1/prod_0001": 200.0,
    "rep1/prod_0002": 300.0,
    "rep2/prod_0001": 200.0,
}

# 25000 steps x 2 fs = the 50 ps every run below covers, echoed identically by the mdin and
# by the mdout: a fixture whose two files disagree collects an unrelated "Timestep differs"
# validation note and sends the next reader after the wrong thing.
_RUN_PS, _NSTLIM, _DT = 50.0, 25000, 0.002
# Two atoms is the smallest restart that still parses; the mdout echoes the same count for
# the same reason the timestep is echoed — an "Atom count mismatch" note is noise here.
_NATOM = 2

_TIMED_MDIN = ("production\n &cntrl\n  imin = 0, irest = 1, ntb = 2,\n"
               "  nstlim = %d, dt = %.3f,\n /\n" % (_NSTLIM, _DT))


def _mdout(end_ps):
    """A run ending at `end_ps`, as the two frames the mdout stats need for an end time."""
    frames = "".join(
        " NSTEP = %8d   TIME(PS) = %11.3f  TEMP(K) =   300.00  PRESS =     0.0\n"
        " Etot   =   -100.0000  EKtot   =    10.0000  EPtot      =   -110.0000\n\n"
        % (nstep, end_ps - _RUN_PS + nstep * _DT)
        for nstep in (_NSTLIM // 2, _NSTLIM))
    return ("          -------------------------------------------------------\n"
            "          Amber 22 PMEMD\n"
            "          -------------------------------------------------------\n\n"
            "| 1.  RESOURCE   USE:\n"
            " NATOM  = %7d NTYPES =       1 NRES   =       1\n\n"
            "Molecular dynamics:\n"
            "     nstlim  = %8d, dt      = %10.5f\n\n"
            % (_NATOM, _NSTLIM, _DT)) + frames


def _rst(ps):
    """An ASCII restart at `ps`: title, `natom time`, one line of six coordinates.

    Written rather than copied from `tests/data`, whose restarts are NetCDF — the time
    would then be readable only where netCDF4/scipy happens to be installed, and this test
    is about which stage the time is compared with, not about the reader.
    """
    return ("restart\n%6d %14.7f\n"
            "   1.0000000   2.0000000   3.0000000   4.0000000   5.0000000   6.0000000\n"
            % (_NATOM, ps))


@pytest.fixture
def declared_producer_run(tmp_path):
    """The manifest above with a real, time-bearing mdout and restart behind every step."""
    (tmp_path / "start.rst").write_text(_rst(0.0), encoding="utf-8")
    for stem, end_ps in _DECLARED_PRODUCER_END_PS.items():
        (tmp_path / stem).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / (stem + ".mdin")).write_text(_TIMED_MDIN, encoding="utf-8")
        (tmp_path / (stem + ".mdout")).write_text(_mdout(end_ps), encoding="utf-8")
        (tmp_path / (stem + ".rst")).write_text(_rst(end_ps), encoding="utf-8")
    (tmp_path / "sim.yaml").write_text(_DECLARED_PRODUCER_MANIFEST, encoding="utf-8")
    return tmp_path


def test_a_declared_producer_is_what_the_head_is_measured_against(declared_producer_run):
    """Ruling 13.1.2's other half, from a manifest rather than from hand-built stages.

    rep2's head declares the equilibration as its producer while *following rep1's tail*
    in the document, which is the only arrangement in which "measured against its producer"
    and "measured against its neighbour" give different numbers. Delete the head check and
    the head goes back to `None` with nothing to read; keep the head check but drop the
    partition and it reports a 200 ps overlap that never happened.
    """
    stages = _analysed(load_simulation(str(declared_producer_run / "sim.yaml")),
                       declared_producer_run)
    by_name = _by_name(stages)
    head = by_name["rep2/prod_0001"]

    # The fixture is only evidence if the two candidate producers disagree, so pin that
    # first — otherwise a later edit to the times could make this test pass by accident.
    # The head reads the equilibration's restart at 100 ps; rep1's tail, which is what
    # precedes it in the document, ended at 300 ps.
    assert [s.name for s in stages] == [
        "common/equil", "rep1/prod_0001", "rep1/prod_0002", "rep2/prod_0001"]
    assert by_name["common/equil"].mdout.details.stats.time_end == 100.0
    assert by_name["rep1/prod_0002"].mdout.details.stats.time_end == 300.0
    assert head.inpcrd.details.time == 100.0

    # Measured against the declared producer: a seamless continuation, which says nothing
    # because 0.0 is the whole story. Measured against the neighbour it would be -200.0
    # and an "appears to overlap" note.
    assert head.observed_gap_ps == 0.0
    assert head.continuity == []

    # The whole document, so the head check is pinned everywhere it fires: the two tagged
    # heads measured against the shared equilibration, rep1's second chunk against its own
    # predecessor, and the untagged head with no producer saying so.
    assert [s.observed_gap_ps for s in stages] == [None, 0.0, 0.0, 0.0]
    assert any("was not measured" in n for n in by_name["common/equil"].continuity)
    assert _problems(stages) == []


from ambermeta.lineages import UNTAGGED
from ambermeta.protocol import detect_sequence_gaps


def _replicas(chunks):
    """`{'rep1': [1, 2, 3], ...}` -> the parallel (names, lineages) the detector takes."""
    rows = [(f"{tag}/prod_{i:04d}", tag) for tag, idxs in chunks.items() for i in idxs]
    return [n for n, _ in rows], [t for _, t in rows]


def test_missing_member_is_detected():
    names = ["ntp_prod_0001.mdin", "ntp_prod_0002.mdin", "ntp_prod_0004.mdin"]
    assert detect_sequence_gaps(names) == {(UNTAGGED, "ntp_prod"): [3]}


def test_complete_sequence_has_no_gaps():
    names = ["prod_1.mdin", "prod_2.mdin", "prod_3.mdin"]
    assert detect_sequence_gaps(names) == {}


def test_single_member_is_not_a_sequence():
    assert detect_sequence_gaps(["prod_1.mdin"]) == {}


def test_runs_in_several_directories_are_one_member_until_they_are_tagged():
    # The control for the whole task: nothing about an untagged document changes, however
    # its files are laid out. Directory is not membership.
    names = ["rep1/prod_0001", "rep1/prod_0002", "rep2/prod_0001", "rep2/prod_0002"]
    assert detect_sequence_gaps(names) == {}
    assert detect_sequence_gaps(names + ["rep2/prod_0004"]) == {(UNTAGGED, "prod"): [3]}


def test_a_member_that_stopped_early_is_reported_against_its_siblings():
    names, tags = _replicas({"rep1": [1, 2, 3], "rep2": [1], "rep3": [1, 2, 3]})
    assert detect_sequence_gaps(names, tags) == {("rep2", "prod"): [2, 3]}


def test_members_numbered_on_different_scales_are_not_compared():
    names, tags = _replicas({"rep1": [1, 2], "rep2": [11, 12]})
    assert detect_sequence_gaps(names, tags) == {}


def test_a_hole_inside_one_member_is_scoped_to_that_member():
    names, tags = _replicas({"rep1": [1, 3], "rep2": [1, 2, 3]})
    assert detect_sequence_gaps(names, tags) == {("rep1", "prod"): [2]}


def test_a_complete_family_reports_nothing():
    names, tags = _replicas({"rep1": [1, 2], "rep2": [1, 2], "rep3": [1, 2]})
    assert detect_sequence_gaps(names, tags) == {}


def test_the_untagged_bucket_is_a_member_like_any_other():
    # Ruling 13.1.1: untagged steps are one member, so they take part in the family frame
    # rather than being excused from it.
    names = ["common/prod_0001", "common/prod_0002", "rep1/prod_0001"]
    tags = [None, None, "rep1"]
    assert detect_sequence_gaps(names, tags) == {("rep1", "prod"): [2]}


def test_different_bases_do_not_frame_each_other():
    names = ["rep1/heat_0001", "rep1/prod_0001", "rep1/prod_0002", "rep2/prod_0001"]
    tags = ["rep1", "rep1", "rep1", "rep2"]
    assert detect_sequence_gaps(names, tags) == {("rep2", "prod"): [2]}


def test_a_member_on_its_own_scale_does_not_excuse_the_others():
    # rep3 shares no index with anybody, so nothing relates it to rep1/rep2 — but it also
    # must not answer for them. One all-or-nothing test across the base let it: rep2's
    # crash went unreported because a third member happened to be numbered elsewhere.
    names, tags = _replicas({"rep1": [1, 2, 3], "rep2": [1], "rep3": [11, 12]})
    assert detect_sequence_gaps(names, tags) == {("rep2", "prod"): [2, 3]}


# ---------------------------------------------------------------------------
# The other detector, on the same key
# ---------------------------------------------------------------------------

from ambermeta.protocol import auto_discover, detect_numeric_sequences


def test_numeric_sequences_are_grouped_per_member():
    names, tags = _replicas({"rep1": [1, 2, 3], "rep2": [1, 2, 3]})
    # Untagged, two directories are still one member — the same control
    # `detect_sequence_gaps` keeps, and the reason the key shapes have to match.
    assert detect_numeric_sequences(names) == {(UNTAGGED, "prod"): [
        "rep1/prod_0001", "rep2/prod_0001",
        "rep1/prod_0002", "rep2/prod_0002",
        "rep1/prod_0003", "rep2/prod_0003",
    ]}
    assert detect_numeric_sequences(names, tags) == {
        ("rep1", "prod"): ["rep1/prod_0001", "rep1/prod_0002", "rep1/prod_0003"],
        ("rep2", "prod"): ["rep2/prod_0001", "rep2/prod_0002", "rep2/prod_0003"],
    }


def test_the_sequence_note_counts_only_the_member_that_ran_it(replica_tree):
    """Where the pooled grouping reached a user, and the reason it is worth fixing.

    `plan --recursive` puts this note on every stage and `to_dict()` publishes it as
    evidence, so three replicas of one chunked production run were announced as a single
    six-run sequence — and three replicas' *minimisations*, one each, as a three-run one.
    """
    protocol = auto_discover(str(replica_tree), recursive=True,
                             skip_cross_stage_validation=True)
    notes = {s.name: [n for n in s.validation if "Part of sequence" in n]
             for s in protocol.stages}
    assert notes["rep1/prod_0001"] == ["INFO: Part of sequence 'prod' (item 1 of 2)"]
    assert notes["rep3/prod_0002"] == ["INFO: Part of sequence 'prod' (item 2 of 2)"]
    # One minimisation per replica is not a sequence at all once the members are told apart.
    assert notes["rep2/min_0001"] == []

    published = {s["name"]: s["summary"]["evidence"] for s in protocol.to_dict()["stages"]}
    assert "item 1 of 2" in published["rep1/prod_0001"]
    assert "of 6" not in published["rep1/prod_0001"]


def test_a_layout_the_inference_refuses_groups_as_it_always_did(nested_sweep_tree):
    """The control for the note: a tree with no defensible member has one pooled family.

    `300K/rep1` beside `310K/rep2` varies in two segments at once, so nothing is tagged and
    the four runs stay one sequence — exactly what this path produced before members
    existed.
    """
    protocol = auto_discover(str(nested_sweep_tree), recursive=True,
                             skip_cross_stage_validation=True)
    notes = [n for s in protocol.stages for n in s.validation if "Part of sequence" in n]
    assert len(notes) == 4
    assert all("of 4" in n for n in notes)


# ---------------------------------------------------------------------------
# `plan --recursive` — the flat engine discovering its own stages
# ---------------------------------------------------------------------------
#
# `auto_discover(manifest=None)` is the second entry into the same engine and the one
# `ambermeta plan <dir> --recursive` takes. It builds its stages from stems, so until the
# layout inference reached it every replica tree was a single document-order chain: each
# member's head measured against the previous member's *tail*. The tests below were first
# run against the untagged branch and observed to fail, except the single-directory
# control, which pins unchanged behaviour and says so.

import os
from pathlib import Path


def _write_run(stem: Path, *, end_ps, restart=True):
    """One run on disk: mdin, a time-bearing mdout, and the restart it wrote."""
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".mdin").write_text(_TIMED_MDIN, encoding="utf-8")
    stem.with_suffix(".mdout").write_text(_mdout(end_ps), encoding="utf-8")
    if restart:
        stem.with_suffix(".rst").write_text(_rst(end_ps), encoding="utf-8")


# Every member runs the same 100 -> 150 -> 200 ps, so within a member the chunks meet
# exactly and across members the two chunks coincide completely — the arrangement in which
# a document-order zip has no choice but to call a member boundary an overlap.
_CHUNK_END_PS = {1: 150.0, 2: 200.0}


@pytest.fixture
def timed_replica_tree(tmp_path):
    """Three replicas of a two-chunk production run, with real times on disk.

    `conftest`'s `replica_tree` is mdin-only, which is enough to see *which* pairs the
    engine compares but not what it then says about them, and "Cannot verify continuity
    between rep1/prod_0002 and rep2/prod_0001" understates the damage: with times present
    the same pairing is published as a finding the user is asked to act on.

    `<run>.rst` is the restart that run *wrote*, which is what every chunked Amber script
    leaves behind (`-o prod_0002.mdout -r prod_0002.rst`).
    """
    for rep in ("rep1", "rep2", "rep3"):
        for chunk, end_ps in _CHUNK_END_PS.items():
            _write_run(tmp_path / rep / f"prod_{chunk:04d}", end_ps=end_ps)
    return tmp_path


def test_plan_recursive_tags_each_discovered_run_with_its_replica_directory(
        timed_replica_tree):
    """The fix itself: the discovery branch reads the same layout `discover` does.

    Everything below this test is a consequence of the tag reaching `SimulationStage`,
    so it is pinned on its own — a regression here would otherwise surface as three
    unrelated failures with no obvious common cause.
    """
    protocol = auto_discover(str(timed_replica_tree), recursive=True)
    assert [(s.name, s.lineage) for s in protocol.stages] == [
        ("rep1/prod_0001", "rep1"), ("rep1/prod_0002", "rep1"),
        ("rep2/prod_0001", "rep2"), ("rep2/prod_0002", "rep2"),
        ("rep3/prod_0001", "rep3"), ("rep3/prod_0002", "rep3"),
    ]


def test_plan_recursive_stops_measuring_one_replica_against_another(timed_replica_tree):
    """The false finding this PR exists to remove, on the CLI mode that still published it.

    Untagged, `rep2/prod_0001` was measured against `rep1/prod_0002` and reported as
    "Stage appears to overlap previous stage by 50 ps" — an assertion about two runs that
    never touched, promoted out of INFO and into the list the user is asked to act on.

    The within-member edge must survive the partition, so the +50 ps on each member's
    second chunk is asserted rather than merely allowed. That gap is itself an artifact of
    stem grouping handing a run its *own* output restart as input coordinates; it is
    pre-existing, it is identical on a single-directory tree (see the control below), and
    it is not what this test is about — it is here because "the member boundary stopped
    being compared" would be satisfied just as well by comparing nothing at all.
    """
    protocol = auto_discover(str(timed_replica_tree), recursive=True)
    by_name = _by_name(protocol.stages)

    assert [s.observed_gap_ps for s in protocol.stages] == [None, 50.0, None, 50.0, None, 50.0]
    assert [(s.name, n) for s in protocol.stages
            for n in s.continuity if "overlap" in n] == []

    # A head is not silently skipped: it has no producer in a discovered document — the
    # restart beside a replica is not evidence of which run read it — and it says so.
    for head in ("rep1/prod_0001", "rep2/prod_0001", "rep3/prod_0001"):
        assert by_name[head].continuity == [
            f"INFO: Continuity for {head} was not measured (no producing stage resolved)."]

    assert _problems(protocol.stages) == [
        (f"{rep}/prod_0002", "Gap detected without stated expectation; verify continuity.")
        for rep in ("rep1", "rep2", "rep3")]


def test_a_single_directory_tree_is_untagged_and_measured_exactly_as_before(tmp_path):
    """The control: one directory has nothing to differ from, so nothing changes.

    Not just "no tags" — the *untagged fast path* has to stay taken. Were the partition to
    run on a single-member document it would add a "was not measured" note to the first
    stage, which lands in `summary.json`; the empty note list below is what says it did not.
    """
    for chunk, end_ps in _CHUNK_END_PS.items():
        _write_run(tmp_path / f"prod_{chunk:04d}", end_ps=end_ps)

    protocol = auto_discover(str(tmp_path), recursive=True)
    assert [s.lineage for s in protocol.stages] == [None, None]
    assert [s.observed_gap_ps for s in protocol.stages] == [None, 50.0]
    assert protocol.stages[0].continuity == []


@pytest.fixture
def half_restarted_replica_tree(tmp_path):
    """Three replicas whose second chunk's restart was not kept.

    Deleting the terminal restart of a finished chunk is ordinary housekeeping, and it is
    what leaves `prod_0002` with no input coordinates of its own — the only state in which
    `--auto-detect-restarts` has anything to do. Each replica's `prod_0001.rst` is then a
    candidate for all three `prod_0002`s, and they are indistinguishable to every check
    that predates lineages: same atom count, same name, same numeric predecessor.
    """
    for rep in ("rep1", "rep2", "rep3"):
        for chunk, end_ps in _CHUNK_END_PS.items():
            _write_run(tmp_path / rep / f"prod_{chunk:04d}",
                       end_ps=end_ps, restart=(chunk == 1))
    return tmp_path


def test_plan_recursive_restart_detection_stops_crossing_replicas(
        half_restarted_replica_tree):
    """`auto_detect_restart_chain`'s guard was documented as inert here. It no longer is.

    Untagged, the three `prod_0001.rst` files scored identically and the first one walked
    over won every time, so all three replicas were recorded as resuming from rep1 — a
    provenance claim, written into `summary.json` as the file each run read.
    """
    protocol = auto_discover(str(half_restarted_replica_tree), recursive=True,
                             auto_detect_restarts=True, skip_cross_stage_validation=True)
    by_name = _by_name(protocol.stages)

    for rep in ("rep1", "rep2", "rep3"):
        stage = by_name[f"{rep}/prod_0002"]
        assert stage.restart_path is not None, rep
        assert os.path.relpath(stage.restart_path, half_restarted_replica_tree) == \
            os.path.join(rep, "prod_0001.rst")
