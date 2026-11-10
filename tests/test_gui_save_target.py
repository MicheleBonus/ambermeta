"""Where the GUI may write a manifest, and what it says about one it cannot read.

The Save dialog listed every file under the launch directory as a target "to overwrite",
and the server wrote wherever it was told. Picking a run's own `.mdin` replaced the input
file with YAML, and every later Save went back to the same path. Plan writes the
manifest through the same function. A manifest is a `.yaml`, `.yml` or `.json` file --
the only names `Open` reads back -- so anything else is refused before a byte is
written.

Opening a manifest with a YAML syntax error came back as HTTP 500 "Internal Server
Error": the reader let `yaml.YAMLError` escape, and only `ValueError` and its kin were
turned into a message.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ambermeta.cli import main  # noqa: E402
from ambermeta.gui.api import routes  # noqa: E402
from ambermeta.simulation import load_simulation  # noqa: E402

MDIN = "production\n &cntrl\n  imin = 0, nstlim = 500000, dt = 0.002,\n /\n"


def _client(base):
    routes.set_base_directory(str(base))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


@pytest.mark.parametrize("name", ["prod_0001.mdin", "system.prmtop", "prod_0001.rst"])
def test_save_will_not_write_over_a_run_file(tmp_path, name):
    target = tmp_path / name
    target.write_text(MDIN, encoding="utf-8")
    c = _client(tmp_path)

    r = c.post("/api/document/save", json={"path": name, "format": "yaml"})

    assert r.status_code == 400
    assert name in r.json()["detail"]
    assert target.read_text(encoding="utf-8") == MDIN


def test_save_will_not_create_a_manifest_under_a_name_open_cannot_read(tmp_path):
    c = _client(tmp_path)

    r = c.post("/api/document/save", json={"path": "notes.txt", "format": "yaml"})

    assert r.status_code == 400
    assert not (tmp_path / "notes.txt").exists()


@pytest.mark.parametrize("name", ["sim.yaml", "sim.yml", "sim.json"])
def test_save_writes_a_manifest_open_can_read_back(tmp_path, name):
    c = _client(tmp_path)

    r = c.post("/api/document/save", json={"path": name})

    assert r.status_code == 200
    assert load_simulation(str(tmp_path / name)).version == 2


def test_plan_will_not_write_the_manifest_over_a_run_file(tmp_path):
    target = tmp_path / "prod_0001.mdin"
    target.write_text(MDIN, encoding="utf-8")
    c = _client(tmp_path)

    r = c.post("/api/plan", json={"save_manifest_path": "prod_0001.mdin"})

    assert r.status_code == 400
    assert target.read_text(encoding="utf-8") == MDIN


def test_opening_a_yaml_manifest_with_a_syntax_error_names_the_file_and_line(tmp_path):
    (tmp_path / "broken.yaml").write_text("version: 2\nsteps: [ {id: a, name: x\n",
                                          encoding="utf-8")
    c = _client(tmp_path)

    r = c.post("/api/document/open", json={"path": "broken.yaml"})

    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "broken.yaml" in detail
    assert "line 2" in detail


def test_opening_a_json_manifest_with_a_syntax_error_names_the_file(tmp_path):
    (tmp_path / "broken.json").write_text('{"version": 2, "steps": [', encoding="utf-8")
    c = _client(tmp_path)

    r = c.post("/api/document/open", json={"path": "broken.json"})

    assert r.status_code == 400
    assert "broken.json" in r.json()["detail"]


def test_the_cli_reports_a_yaml_syntax_error_without_an_unexpected_error(tmp_path, capsys):
    # The CLI reads manifests through the same reader, and showed the same parser error
    # as "Unexpected error (ParserError: ...)", naming `<unicode string>` for the file.
    manifest = tmp_path / "broken.yaml"
    manifest.write_text("version: 2\nsteps: [ {id: a, name: x\n", encoding="utf-8")

    rc = main(["validate", "--manifest", str(manifest)])

    captured = capsys.readouterr()
    shown = captured.out + captured.err
    assert rc == 1
    assert "Unexpected error" not in shown
    assert "broken.yaml" in shown
