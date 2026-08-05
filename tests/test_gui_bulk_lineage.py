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
# Applying the layout inference to an open document
# ---------------------------------------------------------------------------

def test_inference_tags_a_replica_layout_in_one_undo(client, crashed_replica_tree):
    routes.set_base_directory(str(crashed_replica_tree))
    client.post("/api/document/discover", json={"recursive": True})
    # Discover already tagged it; clear the tags so the action has something to do.
    ids = [s["id"] for s in _steps(client)]
    client.patch("/api/steps/lineage", json={"ids": ids, "lineage": None})
    assert {s["lineage"] for s in _steps(client)} == {None}

    body = client.post("/api/steps/infer-lineages").json()
    assert {s["lineage"] for s in _steps(client)} == {"rep1", "rep2", "rep3"}
    assert body["warnings"] == []
    client.post("/api/undo")
    assert {s["lineage"] for s in _steps(client)} == {None}


def test_inference_leaves_a_tag_it_did_not_produce(client, campaign_tree):
    """It applies what it inferred; it does not clear what it did not.

    The campaign layout is the case that makes the difference visible: the inference names
    the three replica directories and deliberately refuses `common/`, whose runs are a
    shared prep rather than a fourth member. Assigning the inference's answer across the
    board would delete a tag the user had put on those prep runs by hand — silently, and
    the more so on a layout where the inference names nothing at all.
    """
    routes.set_base_directory(str(campaign_tree))
    client.post("/api/document/discover", json={"recursive": True})
    all_steps = [s for p in client.get("/api/document").json()["simulation"]["phases"]
                 for s in p["steps"]]
    prep = [s["id"] for s in all_steps if s["name"].startswith("common/")]
    assert prep, "the campaign fixture should hold a shared prep directory"
    client.patch("/api/steps/lineage", json={"ids": prep, "lineage": "shared_prep"})

    client.post("/api/steps/infer-lineages")
    tags = {s["name"]: s["lineage"]
            for p in client.get("/api/document").json()["simulation"]["phases"]
            for s in p["steps"]}
    assert {t for n, t in tags.items() if n.startswith("common/")} == {"shared_prep"}
    assert {t for n, t in tags.items() if n.startswith("rep")} == {"rep1", "rep2", "rep3"}


def test_a_layout_the_inference_refuses_leaves_hand_tags_alone(client, chain):
    """The commonest case, and the one where clearing would hurt most: the inference
    names nothing, so it must change nothing."""
    client.patch("/api/steps/lineage", json={"ids": chain, "lineage": "mine"})
    body = client.post("/api/steps/infer-lineages").json()
    assert [s["lineage"] for s in _steps(client)] == ["mine"] * 4
    assert "No lineages inferred" in body["warnings"][0]


def test_a_layout_the_inference_refuses_says_so(client, chain):
    """Silence would read as broken. The inference refuses far more layouts than it
    accepts — a flat chain like this one is the commonest — and an action that appears to
    do nothing has to say why."""
    body = client.post("/api/steps/infer-lineages").json()
    assert {s["lineage"] for s in _steps(client)} == {None}
    assert "No lineages inferred" in body["warnings"][0]
