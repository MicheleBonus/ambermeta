# tests/test_lineages.py
"""Membership, and the directory-layout inference that proposes it.

The inference is reported to the user as `[applied]` — a claim, not a question — so every
layout it refuses is as much a part of the contract as every layout it tags. The refusals
are tested one per row of the failure-mode table in section 6 of the design doc.
"""
from ambermeta.lineages import (
    UNTAGGED, infer_lineages_from_layout, is_multi_lineage, lineages, members,
)
from ambermeta.simulation import Phase, Simulation, Step


def _sim(*named):
    """A one-phase Simulation from (name, lineage) pairs, in document order."""
    return Simulation(phases=[Phase(id="ph_0", name="Production", role="production", steps=[
        Step(id=f"st_{i}", name=name, lineage=tag)
        for i, (name, tag) in enumerate(named)
    ])])


def _tagged(names):
    """Run the inference over `names` and build the Simulation it proposes."""
    tags = infer_lineages_from_layout(names)
    return _sim(*[(n, tags.get(n)) for n in names])


# --- membership: the sentinel rule ------------------------------------------

def test_an_untagged_document_is_one_member_and_declares_none():
    sim = _sim(("prod_0001", None), ("prod_0002", None), ("prod_0003", None))
    # One shared bucket, not one per step: three untagged steps are a single chain.
    assert list(members(sim)) == [UNTAGGED]
    assert lineages(sim) == {}
    assert is_multi_lineage(sim) is False


def test_tagged_steps_group_by_tag_in_first_appearance_order():
    sim = _sim(("rep2/prod_0001", "rep2"), ("rep1/prod_0001", "rep1"),
               ("rep2/prod_0002", "rep2"), ("rep1/prod_0002", "rep1"))
    assert list(lineages(sim)) == ["rep2", "rep1"]
    assert [s.name for s in lineages(sim)["rep1"]] == ["rep1/prod_0001", "rep1/prod_0002"]
    assert is_multi_lineage(sim) is True


def test_the_untagged_bucket_counts_as_a_member_but_is_never_a_lineage():
    """Ruling 13.1.1, in one assertion pair: one tag plus untagged steps is TWO members
    and is multi-lineage, while lineage_count stays at the one the user declared."""
    sim = _sim(("common/equil", None), ("rep1/prod_0001", "rep1"))
    assert len(members(sim)) == 2
    assert is_multi_lineage(sim) is True
    assert list(lineages(sim)) == ["rep1"]           # the sentinel is not a lineage
    assert UNTAGGED not in lineages(sim)


def test_an_empty_tag_joins_the_untagged_bucket_rather_than_naming_a_member():
    """payload_to_simulation coerces "" on ingest, but an in-memory edit does not pass
    through it. A member that cannot be named must not be counted as one."""
    sim = _sim(("rep1/prod_0001", "rep1"), ("stray", ""))
    assert list(lineages(sim)) == ["rep1"]
    assert members(sim)[UNTAGGED][0].name == "stray"


# --- inference: the layouts that work ---------------------------------------

def test_replica_directories_are_tagged_by_their_differing_segment():
    names = ["rep1/prod_0001", "rep1/prod_0002", "rep2/prod_0001", "rep2/prod_0002"]
    assert infer_lineages_from_layout(names) == {
        "rep1/prod_0001": "rep1", "rep1/prod_0002": "rep1",
        "rep2/prod_0001": "rep2", "rep2/prod_0002": "rep2",
    }


def test_a_shared_prep_directory_stays_untagged_and_out_of_the_count():
    """The membership predicate. `common` runs a different set of runs from the replicas,
    so it is not one of them — the literal 'tag by the differing segment' rule reported
    lineage_count 4 for this three-replica campaign and gave `common` a time_ps."""
    names = ["common/equil", "common/heat", "common/min",
             "rep1/prod_0001", "rep1/prod_0002",
             "rep2/prod_0001", "rep2/prod_0002",
             "rep3/prod_0001", "rep3/prod_0002"]
    tags = infer_lineages_from_layout(names)
    assert [tags.get(n) for n in names] == [
        None, None, None, "rep1", "rep1", "rep2", "rep2", "rep3", "rep3"]
    sim = _tagged(names)
    assert len(lineages(sim)) == 3
    assert len(members(sim)) == 4          # the prep runs still form their own partition
    assert is_multi_lineage(sim) is True


def test_replicas_under_a_shared_parent_are_tagged_by_the_one_segment_that_varies():
    """Nesting alone is not the disqualifier — varying in two places at once is."""
    names = ["sys/rep1/prod_0001", "sys/rep2/prod_0001"]
    assert infer_lineages_from_layout(names) == {
        "sys/rep1/prod_0001": "rep1", "sys/rep2/prod_0001": "rep2"}


def test_a_prep_run_at_a_different_depth_does_not_block_the_replicas():
    names = ["common/equil", "sys/rep1/prod_0001", "sys/rep2/prod_0001"]
    tags = infer_lineages_from_layout(names)
    assert [tags.get(n) for n in names] == [None, "rep1", "rep2"]


# --- inference: the layouts it refuses --------------------------------------

def test_a_flat_chunked_chain_is_never_split_into_members():
    """The repo's own fixture shape, and the one that must not move: an untagged document
    stays untagged, so its manifest and its artifacts are unchanged."""
    assert infer_lineages_from_layout(
        ["ntp_prod_0001", "ntp_prod_0002", "ntp_prod_0003"]) == {}


def test_a_replica_named_only_in_the_filename_stays_untagged():
    """Flat replica-prefix (`rep1_prod_0001`) and replica-suffix (`01_min_rep1`) layouts.
    Section 6 records the tags as 'derivable'; only directory segments are read here,
    because the token rule that would find `rep1` in `rep1_prod_0001` also finds `0001`
    in `prod_0001` and turns every chunked chain into a set of one-step members."""
    assert infer_lineages_from_layout(
        ["rep1_prod_0001", "rep1_prod_0002", "rep2_prod_0001", "rep2_prod_0002"]) == {}
    assert infer_lineages_from_layout(
        ["01_min_rep1", "02_prod_rep1", "01_min_rep2", "02_prod_rep2"]) == {}


def test_a_nested_sweep_is_ambiguous_and_stays_untagged():
    """300K/rep1 vs 310K/rep2: which segment names the member? Neither answer is
    defensible, and a wrong `[applied]` claim is worse than no claim."""
    assert infer_lineages_from_layout([
        "300K/rep1/prod_0001", "300K/rep2/prod_0001",
        "310K/rep1/prod_0001", "310K/rep2/prod_0001"]) == {}


def test_a_single_lineage_in_a_subdirectory_stays_untagged():
    assert infer_lineages_from_layout(["prod/prod_0001", "prod/prod_0002"]) == {}


def test_runs_at_the_tree_root_fail_the_predicate_and_stay_untagged():
    names = ["equil_0001", "rep1/prod_0001", "rep2/prod_0001"]
    tags = infer_lineages_from_layout(names)
    assert [tags.get(n) for n in names] == [None, "rep1", "rep2"]
    # ...and a root run beside a *single* subdirectory leaves nothing to tag at all.
    assert infer_lineages_from_layout(["equil_0001", "rep1/prod_0001"]) == {}
    # A root run whose name matches the replicas' is still not one of them: the root has
    # no segment to be tagged by, so treating it as a candidate would name it "" and
    # rebuild its key as "/prod_0001".
    assert infer_lineages_from_layout(
        ["prod_0001", "rep1/prod_0001", "rep2/prod_0001"]) == {
            "rep1/prod_0001": "rep1", "rep2/prod_0001": "rep2"}


def test_directories_that_run_different_things_are_not_members_of_each_other():
    assert infer_lineages_from_layout(["min/min_0001", "prod/prod_0001"]) == {}


def test_a_replica_that_died_early_is_still_a_member():
    """The predicate matches run *bases*, not whole run names.

    A crashed replica is the single failure mode replicas exist to expose, and it is the
    one case where the members do NOT share a run-name set. Keying the predicate on exact
    names refused to tag this tree at all — which would have silently disabled the
    sequence-hole finding that reports the crash, in the name of a rule whose purpose is
    to keep a shared prep directory from being miscounted as a member.
    """
    tags = infer_lineages_from_layout([
        "rep1/prod_0001", "rep1/prod_0002", "rep1/prod_0003",
        "rep2/prod_0001",
        "rep3/prod_0001", "rep3/prod_0002", "rep3/prod_0003"])
    assert set(tags.values()) == {"rep1", "rep2", "rep3"}
    assert tags["rep2/prod_0001"] == "rep2"


def test_offset_numbering_does_not_stop_replicas_being_members():
    """`rep2` restarting its numbering at 0011 is a naming choice, not a different run."""
    assert infer_lineages_from_layout([
        "rep1/prod_0001", "rep1/prod_0002",
        "rep2/prod_0011", "rep2/prod_0012"]) == {
            "rep1/prod_0001": "rep1", "rep1/prod_0002": "rep1",
            "rep2/prod_0011": "rep2", "rep2/prod_0012": "rep2"}


def test_matching_on_bases_still_refuses_a_shared_prep_directory():
    """The loosened predicate must not re-open the miscount it exists to prevent.

    `common/` runs min/heat/equil; the replicas run prod. Different base sets, so the prep
    directory is not a member and `lineage_count` stays 3 rather than 4.
    """
    tags = infer_lineages_from_layout([
        "common/min_0001", "common/heat_0001", "common/equil_0001",
        "rep1/prod_0001", "rep1/prod_0002",
        "rep2/prod_0001", "rep2/prod_0002",
        "rep3/prod_0001", "rep3/prod_0002"])
    assert set(tags.values()) == {"rep1", "rep2", "rep3"}
    assert not any(name.startswith("common/") for name in tags)


def test_two_rival_families_tag_neither():
    """Two sets that each pass the predicate are two experiments in one manifest, which
    'one manifest = one experiment' does not represent. Picking one would be a guess."""
    assert infer_lineages_from_layout([
        "rep1/prod_0001", "rep2/prod_0001", "ctrl1/eq_0001", "ctrl2/eq_0001"]) == {}


# --- the four in-scope topologies of design section 1.1 ----------------------

def test_topology_1_n_equilibrations_each_feeding_one_production():
    sim = _tagged(["rep1/equil", "rep1/prod", "rep2/equil", "rep2/prod",
                   "rep3/equil", "rep3/prod"])
    assert list(lineages(sim)) == ["rep1", "rep2", "rep3"]
    assert [s.name for s in lineages(sim)["rep2"]] == ["rep2/equil", "rep2/prod"]


def test_topology_2_one_equilibration_fanning_out_into_n_productions():
    sim = _tagged(["common/equil", "rep1/prod_0001", "rep2/prod_0001", "rep3/prod_0001"])
    assert list(lineages(sim)) == ["rep1", "rep2", "rep3"]
    assert [s.name for s in members(sim)[UNTAGGED]] == ["common/equil"]


def test_topology_3_one_lineage_segmented_into_chunks_is_a_single_member():
    """Already supported before lineages existed, and every path stays a no-op for it."""
    sim = _tagged(["prod_0001", "prod_0002", "prod_0003", "prod_0004", "prod_0005"])
    assert lineages(sim) == {}
    assert len(members(sim)) == 1
    assert is_multi_lineage(sim) is False


def test_topology_4_one_topology_with_different_starting_coordinates():
    sim = _tagged(["pose1/prod_0001", "pose2/prod_0001", "pose3/prod_0001"])
    assert list(lineages(sim)) == ["pose1", "pose2", "pose3"]
    assert is_multi_lineage(sim) is True
