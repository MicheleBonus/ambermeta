# tests/test_gui_proposal.py
"""Discover proposes a grouping and writes none of it -- on the path asked to withhold it.

`discover_draft` keeps applying tags by default (`apply_tags=True`, matching every
existing behaviour): the CLI has no confirmation surface of its own, so `discover
--write`'s manifest IS the user's accept, and withholding tags there would ship every
CLI-written manifest untagged with no way to accept it, silencing the crashed-replica
finding on the very path that finding exists for. Only the GUI's `POST
/document/discover` route passes `apply_tags=False`, because the GUI has a real accept
step (`PATCH /steps/lineage`, one call per member) a fresh scan of someone else's
directory tree should wait for. Every direct `discover_draft(...)` call below therefore
passes `apply_tags=False` explicitly, to test that path — not the CLI's, which
`tests/test_cli_discover.py` and `tests/test_gui_core_bridge_sim.py` already cover with
`discover_draft`'s default.

The tool already silently claimed a serial chain nobody asserted; this is the surface that
makes "declaration, not inference" literally true — on the surface that has a Confirm step
to make it true FOR. What is deliberately NOT asserted here: the arithmetic of the
inference itself (tests/test_lineages.py).
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ambermeta.gui.api import core_bridge, routes
from ambermeta.simulation import iter_steps


def test_discover_proposes_five_members_and_tags_nothing(sys021_tree):
    out = core_bridge.discover_draft(str(sys021_tree), recursive=True, apply_tags=False)
    assert [m["tag"] for m in out["proposal"]["members"]] == ["01", "02", "03", "04", "05"]
    assert all(step.lineage is None for _, step in iter_steps(out["simulation"]))


def test_the_proposal_names_the_directories_each_member_is_built_from(sys021_tree):
    out = core_bridge.discover_draft(str(sys021_tree), recursive=True, apply_tags=False)
    first = out["proposal"]["members"][0]
    assert sorted(s["directory"] for s in first["sources"]) == ["equil/01", "prod/01"]


def test_a_tree_the_inference_refuses_gets_no_proposal(nested_sweep_tree):
    out = core_bridge.discover_draft(str(nested_sweep_tree), recursive=True,
                                     apply_tags=False)
    assert out["proposal"] is None
    # `kind` is a CATEGORY, not `needs_you` — that is the card's `severity`. Every card in
    # this codebase is `kind=<category>, severity=needs_you|applied|info`.
    card, = [s for s in out["suggestions"] if s["kind"] == "lineage_needs_you"]
    assert card["severity"] == "needs_you"
    assert "could not tell" in card["evidence"]


def test_a_flat_single_directory_project_is_not_nagged(sample_md_data_dir):
    """`tags` is empty for every tree with fewer than two run sub-directories — the
    commonest shape there is. A "which runs are replicas?" card on every plain
    single-directory project would be noise on nearly every campaign in the repo and in
    the wild, so the card is gated on the tree plausibly having had a choice to refuse."""
    out = core_bridge.discover_draft(str(sample_md_data_dir), recursive=False,
                                     apply_tags=False)
    assert out["proposal"] is None
    assert [s for s in out["suggestions"] if s["kind"] == "lineage_needs_you"] == []


def test_a_crashed_replica_is_still_found_when_tags_are_only_proposed(crashed_replica_tree):
    """The headline payoff of lineages must not go silent just because tags are withheld.

    `build_suggestions` is handed the proposal (`discover_draft` passes `proposed=tags`)
    even though nothing lands on the steps, so the sequence-hole detector still sees rep2
    as its own short member rather than pooling every run into one complete `prod` family
    the moment `Step.lineage` stops carrying the tag.
    """
    out = core_bridge.discover_draft(str(crashed_replica_tree), recursive=True,
                                     apply_tags=False)
    assert all(step.lineage is None for _, step in iter_steps(out["simulation"]))
    card, = [s for s in out["suggestions"] if s["kind"] == "missing_run"]
    assert card["lineage"] == "rep2"
    assert card["base"] == "prod" and card["missing"] == [2, 3]


# ---------------------------------------------------------------------------
# The wire: DiscoverResult.proposal is a field the route has to populate itself
# (it constructs the pydantic model explicitly), so it is worth one test that never
# touches the dict `discover_draft` returns and reads only what the client receives.
# ---------------------------------------------------------------------------

def _client(base):
    routes.set_base_directory(str(base))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


def test_the_proposal_reaches_the_wire(sys021_tree):
    c = _client(sys021_tree)
    r = c.post("/api/document/discover", json={"recursive": True})
    assert r.status_code == 200
    assert r.json()["proposal"]["members"][0]["tag"] == "01"


# ---------------------------------------------------------------------------
# P2.4: handoffs proposed from AMBER's own File Assignments block, scoped to one
# proposed member -- the disambiguator a document-wide basename lookup does not have.
# ---------------------------------------------------------------------------

def test_the_handoff_proposal_reads_ambers_own_file_assignments(sys021_tree):
    """Every prod head's mdout records the restart AMBER actually read. The package has
    parsed that block since before this feature existed and had zero call sites for it.

    All five replicas record the identical bare filename (`INPCRD: 18_ntp_equi.restrt`),
    so the basename alone identifies nothing -- a document-wide lookup on it would
    propose 10 edges on this tree, 9 of them wrong (measured). The member grouping is
    what disambiguates: the match is scoped to one proposed member, so `len(pairs) == 5`
    below is not just "five entries" but "one correct edge per replica, no duplicates and
    no cross-replica leakage" -- a duplicate-emitting implementation (one edge per member
    per matching producer) would inflate this count even though `pairs` is keyed on the
    consumer and would look right by itself.
    """
    out = core_bridge.discover_draft(str(sys021_tree), recursive=True)
    pairs = {h["consumer"]: h["producer"] for h in out["proposal"]["handoffs"]}
    assert pairs["prod/01/nvt_prod_0001"] == "equil/01/18_ntp_equi"
    assert pairs["prod/05/nvt_prod_0001"] == "equil/05/18_ntp_equi"
    assert len(pairs) == 5
    assert len(out["proposal"]["handoffs"]) == 5


def test_a_clipped_assignment_proposes_nothing_rather_than_guessing(tmp_path):
    """MdoutHeader.assignment returns None when AMBER clipped the value at the field
    width -- on the real campaign every PARM line is clipped. That is no evidence, not
    no producer.

    `RunSpec(inpcrd=None)` (the plan's original fixture) omits the entire File
    Assignments block, so `assignment("INPCRD")` would return None because the tag is
    ABSENT, not because it was clipped -- that does not exercise this code path at all.
    The control half below is what stops this passing vacuously: the same tree with a
    short assignment proposes both handoffs, so an implementation that read
    `file_assignments` directly and ignored `truncated` would fail here.
    """
    from tests.conftest import RunSpec, write_run_tree, _EQUI_MDIN, _PROD_MDIN

    def tree(at, inpcrd):
        runs = []
        for n in ("01", "02"):
            runs.append((f"equil/{n}/18_ntp_equi",
                         RunSpec(mdin=_EQUI_MDIN, elapsed_ps=3200.0, begin_ps=1800.0,
                                 irest=0, inpcrd="17_ntp_equi.restrt")))
            runs.append((f"prod/{n}/nvt_prod_0001",
                         RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0, begin_ps=5000.0,
                                 inpcrd=inpcrd)))
        return write_run_tree(at, runs)

    control = core_bridge.discover_draft(
        str(tree(tmp_path / "short", "18_ntp_equi.restrt")), recursive=True)
    assert len(control["proposal"]["handoffs"]) == 2

    # 74 characters exactly fills the field `_mdout_text` pads to, so the value carries no
    # trailing whitespace and comes back as truncated -- the shape a real long path makes.
    #
    # The BASENAME still has to match, and that is what this test used to get wrong:
    # `"1" * 70 + ".rst"` is 74 characters and truncated, but its basename is
    # `111...1.rst`, which no producer in the tree ever wrote. The handoff was refused by
    # the basename lookup, not by the truncation rule, so an implementation that read
    # `file_assignments` directly and ignored `truncated` passed anyway -- verified. Here
    # the value is a long DIRECTORY prefix ending in a basename a producer really did
    # write, so truncation is the only thing left that can refuse it.
    clipped_value = "x" * 55 + "/18_ntp_equi.restrt"
    assert len(clipped_value) == 74, "the value must exactly fill the padded field"
    assert clipped_value.rpartition("/")[2] == "18_ntp_equi.restrt"
    clipped = core_bridge.discover_draft(
        str(tree(tmp_path / "clipped", clipped_value)), recursive=True)
    assert clipped["proposal"]["handoffs"] == []


# ---------------------------------------------------------------------------
# The segment picker must not throw the handoff proposal away. `ProposalStrip.pickSegment`
# replaces the shown proposal WHOLESALE with whatever `POST /steps/infer-lineages`
# returns, so a proposal built without handoffs erases every row the user was looking at.
# ---------------------------------------------------------------------------

def test_re_picking_the_same_segment_returns_the_handoffs_again(sys021_tree):
    """`Change` -> another column -> back is a reversible UI affordance. Before this,
    tapping back returned a proposal with `handoffs: []` and the five
    `equil/NN -> prod/NN` rows vanished with no message -- the entire payoff of the
    handoff work, lost to a control whose whole purpose is that it can be undone.

    Recomputed rather than remembered: the response is compared against what Discover's
    own proposal said, so a frontend that merely cached the previous rows would not satisfy
    this and neither would a server that returned a fixed list.
    """
    c = _client(sys021_tree)
    discovered = c.post("/api/document/discover", json={"recursive": True}).json()
    expected = {h["consumer"]: h["producer"] for h in discovered["proposal"]["handoffs"]}
    assert len(expected) == 5

    index = discovered["proposal"]["segment_index"]
    repicked = c.post("/api/steps/infer-lineages",
                      json={"segment_index": index}).json()["proposal"]
    assert {h["consumer"]: h["producer"] for h in repicked["handoffs"]} == expected


def test_a_different_segment_gets_that_segments_own_handoffs_not_the_last_ones(sys021_tree):
    """Handoffs are MEMBER-SCOPED, so a different segmentation genuinely has different
    ones -- which is why the fix is to re-propose rather than to have the frontend hold the
    previous column's rows over the top of this column's members.

    Index 0 groups by `equil` / `prod`, i.e. by PHASE rather than by replica. Every
    `equil/NN -> prod/NN` pair then straddles two members, and a handoff that straddles
    members is exactly what the member scoping exists to refuse: the empty list here is the
    right answer, not a failure to compute one.
    """
    c = _client(sys021_tree)
    c.post("/api/document/discover", json={"recursive": True})
    by_phase = c.post("/api/steps/infer-lineages",
                      json={"segment_index": 0}).json()["proposal"]
    assert [m["tag"] for m in by_phase["members"]] == ["equil", "prod"]
    assert by_phase["handoffs"] == []


def test_the_default_inference_carries_handoffs_too(sys021_tree):
    """The bare call -- no `segment_index` -- is what `Define replicas…` and the refusal
    retry both make. It goes through the same code path and must not be the one that
    silently returns a handoff-less proposal."""
    c = _client(sys021_tree)
    c.post("/api/document/discover", json={"recursive": True})
    inferred = c.post("/api/steps/infer-lineages", json={}).json()["proposal"]
    assert len(inferred["handoffs"]) == 5
