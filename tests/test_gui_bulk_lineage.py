"""Tagging many steps at once, and the links that stops being true when you do.

Two things make this more than a loop over `PUT /steps/{id}`:

* every per-step write deep-copies the whole document onto the undo stack, and
  `history_limit` is 100, so annotating a 20 x 10 campaign evicts the Discover result being
  annotated before the annotating is finished — and leaves the user 200 Ctrl+Z presses from
  where they started;
* **retagging is the one edit that can invalidate a link without touching it.** The `ref`
  does not move; the boundary does. `_check_continues_from` fires when a ref is *set*, so
  nothing in the document would ever catch it — and because `resolve_input_coords` turns a
  ref into a real path, the stale claim becomes a file from the wrong replica in the
  manifest, in `resolved_input_coords` and in the methods summary.

Assertions are on the resulting *value*, never on the status code: `PUT /steps/{id}` with
`{"lineage": "rep9"}` returned 200 and changed nothing for the whole of PR 2a.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ambermeta.gui.api import routes


@pytest.fixture
def client(tmp_path):
    routes.set_base_directory(str(tmp_path))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def chain(client):
    """Four steps in one phase, auto-chained s1 -> s2 -> s3 -> s4."""
    phase = client.post("/api/phases", json={"name": "Production", "role": "production"})
    phase_id = phase.json()["simulation"]["phases"][0]["id"]
    ids = []
    for name in ("s1", "s2", "s3", "s4"):
        body = client.post(f"/api/phases/{phase_id}/steps", json={"name": name}).json()
        ids.append(body["simulation"]["phases"][0]["steps"][-1]["id"])
    return ids


def _steps(client):
    return client.get("/api/document").json()["simulation"]["phases"][0]["steps"]


def _sources(client):
    return [(s["name"], s["lineage"], s["input_coords"]["source"]) for s in _steps(client)]


# ---------------------------------------------------------------------------
# The write path that did not exist
# ---------------------------------------------------------------------------

def test_a_single_step_can_finally_be_tagged(client, chain):
    """`StepUpdate.lineage` was declared through the whole of PR 2a and the route never
    read it, so this returned 200 and changed nothing."""
    assert client.put(f"/api/steps/{chain[0]}",
                      json={"lineage": "rep9"}).status_code == 200
    assert _steps(client)[0]["lineage"] == "rep9"


def test_a_null_clears_the_tag_and_an_omission_leaves_it(client, chain):
    """Presence semantics, inherited from `topology` rather than from the file slots'
    ""-clears rule: a lineage is a label, not a file slot."""
    client.put(f"/api/steps/{chain[0]}", json={"lineage": "rep9"})
    client.put(f"/api/steps/{chain[0]}", json={"name": "renamed"})
    assert _steps(client)[0]["lineage"] == "rep9"
    client.put(f"/api/steps/{chain[0]}", json={"lineage": None})
    assert _steps(client)[0]["lineage"] is None


def test_many_steps_are_tagged_in_one_request_and_one_undo(client, chain):
    assert client.patch("/api/steps/lineage",
                        json={"ids": chain, "lineage": "rep1"}).status_code == 200
    assert [s["lineage"] for s in _steps(client)] == ["rep1"] * 4
    client.post("/api/undo")
    assert [s["lineage"] for s in _steps(client)] == [None] * 4


def test_one_bad_id_changes_nothing(client, chain):
    """Every lookup happens before the snapshot, so a partial failure leaves neither a
    half-applied tag nor an undo frame that reverses nothing."""
    before = _sources(client)
    r = client.patch("/api/steps/lineage",
                     json={"ids": chain[:2] + ["nope"], "lineage": "rep1"})
    assert r.status_code == 404
    assert _sources(client) == before


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def test_retagging_severs_a_link_that_now_crosses_a_boundary(client, chain):
    client.patch("/api/steps/lineage", json={"ids": chain[:2], "lineage": "rep1"})
    body = client.patch("/api/steps/lineage",
                        json={"ids": chain[2:], "lineage": "rep2"}).json()

    assert _sources(client) == [
        ("s1", "rep1", "starting_structure"),
        ("s2", "rep1", "step"),          # within rep1, untouched
        ("s3", "rep2", "starting_structure"),   # was reading s2, which is now rep1
        ("s4", "rep2", "step"),          # within rep2, untouched
    ]
    warning, = body["warnings"]
    assert "s3 no longer continues s2" in warning
    assert "different lineages" in warning


def test_a_declared_branch_survives_a_lineage_write_elsewhere(client, chain):
    """A cross-lineage ref is legal — `_check_continues_from` accepts one on purpose,
    because "rep2 branches off rep1's equilibration" is a topology somebody may mean.

    The sweep therefore has to drop only what *this edit* made cross. Sweeping every
    crossing link in the document meant any lineage write anywhere — including one that
    changed nothing at all — silently deleted every branch the user had declared.
    """
    client.patch("/api/steps/lineage", json={"ids": chain[:2], "lineage": "rep1"})
    body = client.put(f"/api/steps/{chain[2]}", json={
        "lineage": "rep2",
        "input_coords": {"source": "step", "ref": chain[1]},
    }).json()
    # Accepted, and reported as a branch — judged against the tag this same request sets,
    # not against the one the step is about to stop having.
    assert _sources(client)[2] == ("s3", "rep2", "step")
    assert "is a branch, not a continuation" in body["warnings"][0]

    for payload in ({"ids": [], "lineage": "anything"},
                    {"ids": chain[:2], "lineage": "rep1"},
                    {"ids": [chain[3]], "lineage": "rep2"}):
        assert client.patch("/api/steps/lineage", json=payload).status_code == 200
        assert _sources(client)[2] == ("s3", "rep2", "step"), payload


def test_a_crossing_this_edit_created_is_still_severed(client, chain):
    """The other half: scoping the sweep must not switch it off."""
    client.patch("/api/steps/lineage", json={"ids": chain, "lineage": "rep1"})
    body = client.patch("/api/steps/lineage",
                        json={"ids": [chain[1]], "lineage": "rep2"}).json()
    assert _sources(client)[1] == ("s2", "rep2", "starting_structure")
    assert body["warnings"]


def test_an_untagged_producer_is_still_a_legal_branch_point(client, chain):
    """The loose rule, and the one topology this feature exists to support: a shared
    equilibration feeding N replicas. An untagged step is nobody's member, so a tagged run
    reading its restart claims nothing about membership."""
    client.patch("/api/steps/lineage", json={"ids": chain[1:], "lineage": "rep1"})
    assert _sources(client)[1] == ("s2", "rep1", "step")   # s2 still reads untagged s1


def test_tagging_everything_the_same_severs_nothing(client, chain):
    client.patch("/api/steps/lineage", json={"ids": chain, "lineage": "rep1"})
    assert [s[2] for s in _sources(client)] == [
        "starting_structure", "step", "step", "step"]


# ---------------------------------------------------------------------------
# Proposing a grouping for an open document — P2.2 repointed this route from
# "apply the inference" to "propose it"; nothing here writes to the document any more.
# ---------------------------------------------------------------------------

def test_infer_lineages_proposes_a_replica_layout_and_writes_nothing(
        client, crashed_replica_tree):
    routes.set_base_directory(str(crashed_replica_tree))
    client.post("/api/document/discover", json={"recursive": True})
    # Discover itself writes nothing now — the GUI route calls
    # `discover_draft(..., apply_tags=False)` — so this is the baseline, not a setup step.
    assert {s["lineage"] for s in _steps(client)} == {None}

    body = client.post("/api/steps/infer-lineages").json()
    assert {m["tag"] for m in body["proposal"]["members"]} == {"rep1", "rep2", "rep3"}
    assert body["warnings"] == []
    # Proposing is not an edit: the document is exactly what Discover left it as.
    assert {s["lineage"] for s in _steps(client)} == {None}


def test_infer_lineages_proposes_replicas_without_disturbing_a_hand_set_tag(
        client, campaign_tree):
    """It proposes what it infers; it never touches what the document already says.

    The campaign layout is the case that makes the distinction visible: the inference
    names the three replica directories and deliberately refuses `common/`, whose runs are
    a shared prep rather than a fourth member. This route writes nothing at all now, so a
    tag the user put on those prep runs by hand survives calling it — trivially true today,
    but worth pinning: the bug this test used to guard against (assigning the inference's
    answer across the board silently deleted a hand-set tag it did not also name) can only
    recur if a later change has this route start writing again.
    """
    routes.set_base_directory(str(campaign_tree))
    client.post("/api/document/discover", json={"recursive": True})
    all_steps = [s for p in client.get("/api/document").json()["simulation"]["phases"]
                 for s in p["steps"]]
    prep = [s["id"] for s in all_steps if s["name"].startswith("common/")]
    assert prep, "the campaign fixture should hold a shared prep directory"
    client.patch("/api/steps/lineage", json={"ids": prep, "lineage": "shared_prep"})

    body = client.post("/api/steps/infer-lineages").json()
    assert {m["tag"] for m in body["proposal"]["members"]} == {"rep1", "rep2", "rep3"}

    tags = {s["name"]: s["lineage"]
            for p in client.get("/api/document").json()["simulation"]["phases"]
            for s in p["steps"]}
    assert {t for n, t in tags.items() if n.startswith("common/")} == {"shared_prep"}
    # Untouched by the proposal: discover left them None, and infer-lineages writes
    # nothing, so they are still None — not the "rep1"/"rep2"/"rep3" a route that applied
    # its proposal would have written.
    assert {t for n, t in tags.items() if n.startswith("rep")} == {None}


def test_infer_lineages_honours_an_explicit_segment_index(client, sys021_tree):
    """The picker's "try this column": an explicit `segment_index` bypasses the
    cohort/nesting inference entirely and tags every step by its own segment at that index.

    Index 0 of `equil/NN/<run>` / `prod/NN/<run>` is `equil`/`prod` — the phase the
    default inference (index 1, `NN`) does NOT choose — so this also proves the parameter
    actually changes which grouping comes back, not just that it is accepted.
    """
    routes.set_base_directory(str(sys021_tree))
    client.post("/api/document/discover", json={"recursive": True})

    default = client.post("/api/steps/infer-lineages").json()
    assert default["proposal"]["segment_index"] == 1
    assert sorted(m["tag"] for m in default["proposal"]["members"]) == (
        ["01", "02", "03", "04", "05"])

    picked = client.post("/api/steps/infer-lineages", json={"segment_index": 0}).json()
    assert picked["proposal"]["segment_index"] == 0
    assert sorted(m["tag"] for m in picked["proposal"]["members"]) == ["equil", "prod"]


def test_a_layout_the_inference_refuses_leaves_hand_tags_alone(client, chain):
    """The commonest case: the inference names nothing, and this route writes nothing
    regardless, so a hand-set tag is exactly where it was before the call."""
    client.patch("/api/steps/lineage", json={"ids": chain, "lineage": "mine"})
    body = client.post("/api/steps/infer-lineages").json()
    assert [s["lineage"] for s in _steps(client)] == ["mine"] * 4
    assert body["proposal"] is None
    assert "No lineages inferred" in body["warnings"][0]


def test_a_layout_the_inference_refuses_says_so(client, chain):
    """Silence would read as broken. The inference refuses far more layouts than it
    accepts — a flat chain like this one is the commonest — and an action that appears to
    do nothing has to say why."""
    body = client.post("/api/steps/infer-lineages").json()
    assert {s["lineage"] for s in _steps(client)} == {None}
    assert body["proposal"] is None
    assert "No lineages inferred" in body["warnings"][0]
