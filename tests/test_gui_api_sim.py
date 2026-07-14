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
