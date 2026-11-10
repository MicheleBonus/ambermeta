"""Paths the GUI stores are relative to the launch directory, like the ones Discover writes.

The file list hands the client absolute paths, and every route that takes a path stored it
as sent. A file assigned by dragging went into the manifest as
`C:\\Users\\<name>\\...\\run\\CH3L1_HUMAN_6NAG.crd` beside Discover's `ntp_prod_0001.mdin`:
the manifest broke as soon as the folder moved or someone else opened it, and it recorded
the local user name.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ambermeta.gui.api import routes  # noqa: E402


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "sub").mkdir()
    for rel in ("system.prmtop", "start.rst", "sub/run.mdin", "sub/run.mdout",
                "sub/run.nc", "sub/run.rst"):
        (tmp_path / rel).write_text("x\n", encoding="utf-8")
    routes.set_base_directory(str(tmp_path))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    client = TestClient(app)
    doc = client.post("/api/phases", json={"name": "Production", "role": "production"}).json()
    phase_id = doc["simulation"]["phases"][0]["id"]
    doc = client.post(f"/api/phases/{phase_id}/steps", json={"name": "run"}).json()
    step_id = doc["simulation"]["phases"][0]["steps"][0]["id"]
    return tmp_path, client, phase_id, step_id


def _step(doc):
    return doc["simulation"]["phases"][0]["steps"][0]


def test_a_file_assigned_to_a_slot_is_stored_relative(tree):
    base, c, _, step_id = tree
    r = c.post("/api/assign", json={"path": str(base / "sub" / "run.nc"),
                                    "target_type": "step_slot", "target_id": step_id,
                                    "slot": "mdcrd"})
    assert r.status_code == 200
    assert _step(r.json())["mdcrd"] == "sub/run.nc"


def test_a_slot_set_from_the_step_editor_is_stored_relative(tree):
    base, c, _, step_id = tree
    r = c.put(f"/api/steps/{step_id}", json={"files": {"mdin": str(base / "sub" / "run.mdin"),
                                                       "rst": str(base / "sub" / "run.rst")}})
    assert r.status_code == 200
    assert (_step(r.json())["mdin"], _step(r.json())["rst"]) == ("sub/run.mdin", "sub/run.rst")


def test_an_explicit_input_path_is_stored_relative(tree):
    base, c, _, step_id = tree
    r = c.put(f"/api/steps/{step_id}",
              json={"input_coords": {"source": "path", "path": str(base / "start.rst")}})
    assert r.status_code == 200
    assert _step(r.json())["input_coords"]["path"] == "start.rst"


def test_a_step_created_with_files_stores_them_relative(tree):
    base, c, phase_id, _ = tree
    r = c.post(f"/api/phases/{phase_id}/steps",
               json={"name": "run2", "mdout": str(base / "sub" / "run.mdout")})
    assert r.status_code == 200
    created = r.json()["simulation"]["phases"][0]["steps"][-1]
    assert created["mdout"] == "sub/run.mdout"


def test_a_topology_and_the_starting_structure_are_stored_relative(tree):
    base, c, _, _ = tree
    c.post("/api/topologies", json={"path": str(base / "system.prmtop"), "kind": "normal"})
    r = c.put("/api/simulation/starting-structure", json={"path": str(base / "start.rst")})
    sim = r.json()["simulation"]
    assert [t["path"] for t in sim["topologies"]] == ["system.prmtop"]
    assert sim["starting_structure"] == "start.rst"


def test_a_path_outside_the_launch_directory_is_still_refused(tree):
    base, c, _, step_id = tree
    outside = base.parent / "elsewhere.nc"
    outside.write_text("x\n", encoding="utf-8")
    r = c.post("/api/assign", json={"path": str(outside), "target_type": "step_slot",
                                    "target_id": step_id, "slot": "mdcrd"})
    assert r.status_code == 403
