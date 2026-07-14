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


def test_assign_and_file_routes(tmp_path):
    (tmp_path / "wt.prmtop").write_text("dummy")
    (tmp_path / "min.in").write_text("&cntrl\nimin=1,\n/\n")
    c = _client(tmp_path)
    p = c.post("/api/phases", json={"name": "Min", "role": "minimization"}).json()["simulation"]["phases"][0]["id"]
    s = c.post(f"/api/phases/{p}/steps", json={"name": "min"}).json()["simulation"]["phases"][0]["steps"][0]["id"]

    r = c.post("/api/assign", json={"path": "wt.prmtop", "target_type": "step_topology", "target_id": s})
    assert r.status_code == 200
    assert c.get("/api/document").json()["simulation"]["topologies"][0]["path"] == "wt.prmtop"

    r = c.post("/api/assign", json={"path": "min.in", "target_type": "step_slot", "target_id": s, "slot": "mdin"})
    assert _step(c, s)["mdin"] == "min.in"

    r = c.get("/api/files")
    assert r.status_code == 200 and any(f["name"] == "wt.prmtop" for f in r.json())

    r = c.get("/api/files/raw", params={"path": "min.in"})
    assert r.status_code == 200 and "imin=1" in r.json()["content"]

    assert c.post("/api/assign", json={"path": "x", "target_type": "bogus"}).status_code == 400


def test_mutation_routes_reject_path_traversal(tmp_path):
    c = _client(tmp_path)
    evil = "../../secret.prmtop"
    # topology pool
    assert c.post("/api/topologies", json={"path": evil, "kind": "normal"}).status_code == 403
    # unified assign
    assert c.post("/api/assign", json={"path": evil, "target_type": "pool", "kind": "normal"}).status_code == 403
    # starting structure
    assert c.put("/api/simulation/starting-structure", json={"path": evil}).status_code == 403
    # a valid topology first (inside base), then a traversal update
    tid = c.post("/api/topologies", json={"path": "ok.prmtop", "kind": "normal"}).json()["simulation"]["topologies"][0]["id"]
    assert c.put(f"/api/topologies/{tid}", json={"path": evil}).status_code == 403
    # step create + update slot
    p = c.post("/api/phases", json={"name": "P", "role": "production"}).json()["simulation"]["phases"][0]["id"]
    assert c.post(f"/api/phases/{p}/steps", json={"name": "s", "mdin": evil}).status_code == 403
    sid = c.post(f"/api/phases/{p}/steps", json={"name": "s2"}).json()["simulation"]["phases"][0]["steps"][-1]["id"]
    assert c.put(f"/api/steps/{sid}", json={"files": {"mdin": evil}}).status_code == 403
    # a legitimate relative path inside base must still WORK (not over-blocked)
    assert c.post("/api/topologies", json={"path": "sys.prmtop", "kind": "normal"}).status_code == 200
