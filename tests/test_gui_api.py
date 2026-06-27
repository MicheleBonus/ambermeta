# tests/test_gui_api.py
import json
import pytest

from ambermeta.gui.server import create_app
from ambermeta.manifest import write_manifest


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient
    app = create_app(str(tmp_path))
    return TestClient(app), tmp_path


def test_get_document_initial_empty(client):
    c, base = client
    r = c.get("/api/document")
    assert r.status_code == 200
    body = r.json()
    assert body["stages"] == []
    assert body["dirty"] is False
    assert body["manifest_path"] is None


def test_open_then_get_document(client):
    c, base = client
    payload = {"global_prmtop": "sys.prmtop",
               "stages": [{"name": "prod", "stage_role": "production",
                           "mdin": "prod.in"}]}
    mpath = base / "protocol.yaml"
    write_manifest(payload, str(mpath), "yaml")
    r = c.post("/api/document/open", json={"path": str(mpath)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"]["global_prmtop"] == "sys.prmtop"
    assert [s["name"] for s in body["stages"]] == ["prod"]
    assert body["manifest_path"] == __import__("os").path.realpath(str(mpath))


def test_open_bad_path_is_4xx_not_500(client):
    c, base = client
    r = c.post("/api/document/open", json={"path": str(base / "missing.yaml")})
    assert r.status_code in (400, 404)


def test_open_outside_base_is_403(client):
    c, base = client
    r = c.post("/api/document/open", json={"path": str(base.parent / "evil.yaml")})
    assert r.status_code == 403


def test_save_is_byte_identical_to_write_manifest(client):
    c, base = client
    # open a known manifest, then save it back out
    payload = {"global_prmtop": "sys.prmtop",
               "stages": [{"name": "min", "stage_role": "minimization",
                           "mdin": "min.in"},
                          {"name": "prod", "stage_role": "production",
                           "mdin": "prod.in"}]}
    src = base / "src.yaml"
    write_manifest(payload, str(src), "yaml")
    c.post("/api/document/open", json={"path": str(src)})
    out = base / "out.yaml"
    r = c.post("/api/document/save", json={"path": str(out), "format": "yaml"})
    assert r.status_code == 200, r.text
    assert r.json()["document"]["dirty"] is False
    # Independently regenerate the reference via the core writer.
    ref = base / "ref.yaml"
    write_manifest(payload, str(ref), "yaml")
    assert out.read_text(encoding="utf-8") == ref.read_text(encoding="utf-8")


def test_discover_populates_stages(client):
    c, base = client
    for i in (1, 2):
        (base / f"prod_{i:03d}.mdin").write_text("x", encoding="utf-8")
        (base / f"prod_{i:03d}.mdout").write_text("x", encoding="utf-8")
    r = c.post("/api/document/discover", json={"recursive": False})
    assert r.status_code == 200, r.text
    names = sorted(s["name"] for s in r.json()["stages"])
    assert names == ["prod_001", "prod_002"]
    assert r.json()["dirty"] is True


def test_preview_matches_core_writer(client):
    c, base = client
    payload = {"stages": [{"name": "prod", "stage_role": "production"}]}
    src = base / "src.json"
    write_manifest(payload, str(src), "json")
    c.post("/api/document/open", json={"path": str(src)})
    r = c.post("/api/document/preview", json={"format": "json"})
    assert r.status_code == 200
    ref = base / "ref.json"
    write_manifest(payload, str(ref), "json")
    assert r.json()["content"] == ref.read_text(encoding="utf-8")
