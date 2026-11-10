"""A reorder keeps the links AMBER recorded, and says which ones it changed.

With `auto_link_restarts` on (the default), reordering steps re-derived every
"continues from" that pointed at the old neighbour. On the sample, moving `ntp_prod_0002`
below `ntp_prod_0003` declared that 0003 read 0001's restart, 0002 read 0003's and 0004
read 0002's -- while each mdout records the run it actually continued -- and the edit
said nothing: the only trace was three "Declared input differs" findings afterwards.

A link the run's own mdout confirms (its INPCRD names the declared input) is evidence,
not adjacency, so a reorder keeps it. A link nothing confirms still follows the new
order, as before, and the response now says which steps were re-linked.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ambermeta.gui.api import routes  # noqa: E402
from tests.conftest import write_run_tree  # noqa: E402


def _client(base):
    routes.set_base_directory(str(base))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


def _discover(c):
    return c.post("/api/document/discover", json={"recursive": True}).json()["document"]


def _chain(doc):
    steps = [s for p in doc["simulation"]["phases"] for s in p["steps"]]
    names = {s["id"]: s["name"] for s in steps}
    return {s["name"]: (names[s["input_coords"]["ref"]] if s["input_coords"]["source"] == "step"
                        else s["input_coords"]["source"]) for s in steps}


def _reorder(c, doc, order):
    phase = doc["simulation"]["phases"][0]
    ids = {s["name"]: s["id"] for s in phase["steps"]}
    return c.post(f"/api/phases/{phase['id']}/steps/reorder",
                  json={"step_ids": [ids[n] for n in order]})


def test_a_reorder_keeps_the_links_the_mdouts_record(sample_md_data_dir):
    c = _client(sample_md_data_dir)
    doc = _discover(c)
    before = _chain(doc)

    r = _reorder(c, doc, ["ntp_prod_0001", "ntp_prod_0003", "ntp_prod_0002",
                          "ntp_prod_0004", "ntp_prod_0005"])

    assert r.status_code == 200
    assert _chain(r.json()) == before
    assert r.json()["warnings"] == []
    report = c.post("/api/validate", json={}).json()
    assert [s for s in report["suggestions"] if s["kind"] == "input_mismatch"] == []


def test_moving_the_first_run_keeps_the_input_it_recorded(sample_md_data_dir):
    # The head reads the starting structure, and its mdout records exactly that; before,
    # moving it down chained it onto its new neighbour.
    c = _client(sample_md_data_dir)
    doc = _discover(c)

    r = _reorder(c, doc, ["ntp_prod_0002", "ntp_prod_0001", "ntp_prod_0003",
                          "ntp_prod_0004", "ntp_prod_0005"])

    assert _chain(r.json())["ntp_prod_0001"] == "starting_structure"
    assert _chain(r.json())["ntp_prod_0002"] == "ntp_prod_0001"


def test_unrecorded_links_still_follow_the_order_and_the_edit_says_so(tmp_path):
    # mdin only: no mdout, so nothing confirms any link and the old behaviour applies.
    write_run_tree(tmp_path, ["prod_0001", "prod_0002", "prod_0003"])
    c = _client(tmp_path)
    doc = _discover(c)
    assert _chain(doc) == {"prod_0001": "starting_structure", "prod_0002": "prod_0001",
                           "prod_0003": "prod_0002"}

    r = _reorder(c, doc, ["prod_0001", "prod_0003", "prod_0002"])

    assert _chain(r.json()) == {"prod_0001": "starting_structure", "prod_0003": "prod_0001",
                                "prod_0002": "prod_0003"}
    message, = r.json()["warnings"]
    assert "prod_0003" in message and "prod_0002" in message
