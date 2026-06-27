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


def test_stage_crud_and_dirty(client):
    c, base = client
    r = c.post("/api/stages", json={"name": "min", "role": "minimization"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dirty"] is True
    sid = body["stages"][0]["id"]

    r = c.put(f"/api/stages/{sid}", json={"files": {"mdin": "min.in"}})
    assert r.json()["stages"][0]["mdin"] == "min.in"

    r = c.put(f"/api/stages/{sid}", json={"files": {"mdin": ""}})  # clear
    assert r.json()["stages"][0]["mdin"] is None

    r = c.delete(f"/api/stages/{sid}")
    assert r.json()["stages"] == []

    r = c.delete(f"/api/stages/{sid}")  # already gone
    assert r.status_code == 404


def test_reorder_and_bulk(client):
    c, base = client
    a = c.post("/api/stages", json={"name": "a"}).json()["stages"][0]["id"]
    b = c.post("/api/stages", json={"name": "b"}).json()["stages"][-1]["id"]
    r = c.post("/api/stages/reorder", json={"stage_ids": [b, a]})
    assert [s["name"] for s in r.json()["stages"]] == ["b", "a"]
    r = c.put("/api/stages/bulk", json={"stage_ids": [a, b],
                                        "update": {"role": "production"}})
    assert all(s["role"] == "production" for s in r.json()["stages"])


def test_settings_patch_and_undo_redo(client):
    c, base = client
    c.post("/api/stages", json={"name": "a"})
    r = c.put("/api/settings", json={"global_prmtop": "sys.prmtop"})
    assert r.json()["settings"]["global_prmtop"] == "sys.prmtop"
    # GET settings reflects it
    assert c.get("/api/settings").json()["global_prmtop"] == "sys.prmtop"
    # undo reverts the settings patch, keeps the stage
    r = c.post("/api/undo")
    assert r.json()["settings"]["global_prmtop"] is None
    assert len(r.json()["stages"]) == 1
    # redo re-applies
    r = c.post("/api/redo")
    assert r.json()["settings"]["global_prmtop"] == "sys.prmtop"


def test_validate_flags_missing_file(client):
    c, base = client
    c.post("/api/stages", json={"name": "min", "role": "minimization",
                                "files": {"mdin": "nope.in"}})
    r = c.post("/api/validate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["stage_issues"][0]["name"] == "min"
    assert any("nope.in" in e for e in body["stage_issues"][0]["errors"])


def test_files_list_and_metadata(client):
    c, base = client
    (base / "prod.mdin").write_text(
        "prod\n&cntrl\n  imin=0, nstlim=1000, dt=0.002, ntb=2,\n/\n", encoding="utf-8")
    r = c.get("/api/files", params={"recursive": False})
    assert r.status_code == 200
    assert any(f["name"] == "prod.mdin" for f in r.json())
    r = c.get("/api/files/metadata", params={"path": str(base / "prod.mdin")})
    assert r.status_code == 200, r.text
    assert r.json()["metadata"]["details"] is not None


def test_files_metadata_outside_base_403(client):
    c, base = client
    r = c.get("/api/files/metadata", params={"path": str(base.parent / "x.prmtop")})
    assert r.status_code == 403


def test_sequences_groups_numbered_runs(client):
    c, base = client
    ids = []
    for i in (1, 2, 3):
        body = c.post("/api/stages", json={"name": f"prod_{i:03d}"}).json()
        ids.append(body["stages"][-1]["id"])
    c.post("/api/stages", json={"name": "minimize"})  # singleton, not a sequence
    r = c.get("/api/sequences")
    assert r.status_code == 200, r.text
    groups = r.json()
    # exactly one detected sequence, holding the three prod ids in order
    assert len(groups) == 1
    only = list(groups.values())[0]
    assert only == ids
