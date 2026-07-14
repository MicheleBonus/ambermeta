import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ambermeta.gui.api import routes


def _client(base):
    routes.set_base_directory(str(base))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


def test_get_document_empty(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/document")
    assert r.status_code == 200
    body = r.json()
    assert body["simulation"]["version"] == 2 and body["simulation"]["phases"] == []


def test_open_v1_migrates_and_undo_redo(tmp_path):
    v1 = {"global_prmtop": "wt.prmtop",
          "stages": [{"name": "min", "stage_role": "minimization", "mdin": "min.in"},
                     {"name": "prod_001", "stage_role": "production", "mdin": "prod_001.in"}]}
    (tmp_path / "legacy.json").write_text(json.dumps(v1))
    c = _client(tmp_path)
    r = c.post("/api/document/open", json={"path": "legacy.json"})
    assert r.status_code == 200
    roles = [p["role"] for p in r.json()["simulation"]["phases"]]
    assert roles == ["minimization", "production"]


def test_discover_returns_result_with_suggestions(sample_md_data_dir):
    c = _client(sample_md_data_dir)
    r = c.post("/api/document/discover", json={"recursive": False})
    assert r.status_code == 200
    body = r.json()
    assert "document" in body and "suggestions" in body
    assert body["document"]["simulation"]["phases"]


def test_topology_routes(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/topologies", json={"path": "wt.prmtop", "kind": "hmr"})
    assert r.status_code == 200
    tid = r.json()["simulation"]["topologies"][0]["id"]
    assert r.json()["simulation"]["topologies"][0]["kind"] == "hmr"

    r = c.put(f"/api/topologies/{tid}", json={"kind": "normal"})
    assert r.json()["simulation"]["topologies"][0]["kind"] == "normal"

    r = c.put("/api/simulation/starting-structure", json={"path": "wt.inpcrd"})
    assert r.json()["simulation"]["starting_structure"] == "wt.inpcrd"

    r = c.delete(f"/api/topologies/{tid}")
    assert r.json()["simulation"]["topologies"] == []

    assert c.put("/api/topologies/bogus", json={"kind": "hmr"}).status_code == 404


def test_phase_routes(tmp_path):
    c = _client(tmp_path)
    a = c.post("/api/phases", json={"name": "Min", "role": "minimization"}).json()
    pa = a["simulation"]["phases"][0]["id"]
    b = c.post("/api/phases", json={"name": "Prod", "role": "production"}).json()
    pb = b["simulation"]["phases"][1]["id"]

    r = c.post("/api/phases/reorder", json={"phase_ids": [pb, pa]})
    assert [p["id"] for p in r.json()["simulation"]["phases"]] == [pb, pa]

    r = c.put(f"/api/phases/{pa}", json={"name": "Minimization"})
    names = {p["id"]: p["name"] for p in r.json()["simulation"]["phases"]}
    assert names[pa] == "Minimization"

    r = c.delete(f"/api/phases/{pa}")
    assert [p["id"] for p in r.json()["simulation"]["phases"]] == [pb]
    assert c.put("/api/phases/bogus", json={"name": "x"}).status_code == 404


def test_step_routes_and_topology_clear(tmp_path):
    c = _client(tmp_path)
    p = c.post("/api/phases", json={"name": "Prod", "role": "production"}).json()["simulation"]["phases"][0]["id"]
    r = c.post(f"/api/phases/{p}/steps", json={"name": "prod_001", "mdin": "prod_001.in"})
    sid = r.json()["simulation"]["phases"][0]["steps"][0]["id"]

    # set then clear topology (explicit null must clear)
    c.put(f"/api/steps/{sid}", json={"topology": "t0"})
    assert _step(c, sid)["topology"] == "t0"
    c.put(f"/api/steps/{sid}", json={"topology": None})
    assert _step(c, sid)["topology"] is None
    # absent topology must NOT clear
    c.put(f"/api/steps/{sid}", json={"topology": "t9"})
    c.put(f"/api/steps/{sid}", json={"name": "prod_001b"})
    assert _step(c, sid)["topology"] == "t9" and _step(c, sid)["name"] == "prod_001b"

    r = c.request("DELETE", f"/api/steps/{sid}")
    assert r.json()["simulation"]["phases"][0]["steps"] == []


def _step(c, sid):
    doc = c.get("/api/document").json()
    for ph in doc["simulation"]["phases"]:
        for s in ph["steps"]:
            if s["id"] == sid:
                return s
    raise AssertionError("step not found")
