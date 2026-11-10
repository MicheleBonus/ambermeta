"""A manifest's name decides its format, so Save never writes a file Open cannot read.

The Save dialog sends a Format alongside the name, and it starts at yaml. Typing
`manifest.json` and leaving Format alone wrote YAML into the `.json` file: Save
answered 200, the unsaved-changes dot went out, and reopening the file failed with "JSON
syntax error at line 1, column 1". Open reads a manifest by its extension, so for a
manifest name the extension is the format. A Format that disagrees with it is named in a
warning instead of being obeyed.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ambermeta.gui.api import core_bridge, routes  # noqa: E402
from ambermeta.simulation import load_simulation  # noqa: E402


def _client(base):
    routes.set_base_directory(str(base))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


def test_a_json_name_is_written_as_json_whatever_format_was_sent(tmp_path):
    r = _client(tmp_path).post("/api/document/save",
                               json={"path": "manifest.json", "format": "yaml"})

    assert r.status_code == 200
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["version"] == 2
    assert load_simulation(str(tmp_path / "manifest.json")).version == 2
    assert any("JSON" in w and "manifest.json" in w for w in r.json()["warnings"])


def test_a_yaml_name_is_written_as_yaml_whatever_format_was_sent(tmp_path):
    r = _client(tmp_path).post("/api/document/save",
                               json={"path": "manifest.yml", "format": "json"})

    assert r.status_code == 200
    text = (tmp_path / "manifest.yml").read_text(encoding="utf-8")
    assert text.startswith("version: 2")
    assert any("YAML" in w for w in r.json()["warnings"])


def test_an_agreeing_format_adds_no_warning(tmp_path):
    r = _client(tmp_path).post("/api/document/save",
                               json={"path": "manifest.json", "format": "json"})

    assert r.status_code == 200
    assert r.json()["warnings"] == []


def test_resolve_format_lets_a_manifest_extension_win():
    assert core_bridge.resolve_format("x.json", "yaml") == "json"
    assert core_bridge.resolve_format("x.yaml", "json") == "yaml"
    assert core_bridge.resolve_format("x.yml", None) == "yaml"
    assert core_bridge.resolve_format(None, "json") == "json"
    assert core_bridge.resolve_format(None, None) == "yaml"
