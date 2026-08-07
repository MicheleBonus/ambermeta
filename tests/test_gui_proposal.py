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
