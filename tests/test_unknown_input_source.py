"""A step whose `input_coords.source` is not a known kind is refused at load.

`resolve_input_coords` answers only `starting_structure`, `step` and `path`; anything else
(`starting-structure`, `restart`, a typo) resolved to None, so the step was validated with
no input file and no declared parent. `validate --manifest` printed the same "Validation:
OK" it prints for the correctly spelt manifest, and `plan -m` showed `input=?` without a
word of why. The spelling is a structural error in the document, like a missing `steps`
list, so it is refused where those are, naming the step and the accepted values.
"""
from __future__ import annotations

import json

import pytest

from ambermeta.cli import main
from ambermeta.errors import AmberMetaError
from ambermeta.simulation import load_simulation


def _manifest(tmp_path, source):
    doc = {
        "version": 2,
        "simulation": {"topologies": [], "starting_structure": "start.rst"},
        "phases": [{"id": "p", "name": "Production", "role": "production", "order": 0}],
        "steps": [
            {"id": "s1", "name": "prod_1", "phase": "p", "order": 0,
             "input_coords": {"source": source}, "mdin": "prod_1.mdin"},
        ],
    }
    path = tmp_path / "sim.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.mark.parametrize("source", ["starting-structure", "restart", ""])
def test_an_unknown_source_is_refused_naming_the_step(tmp_path, source):
    with pytest.raises(AmberMetaError) as info:
        load_simulation(str(_manifest(tmp_path, source)))

    message = str(info.value)
    assert "prod_1" in message
    assert repr(source) in message
    assert "starting_structure, step, path" in message


@pytest.mark.parametrize("source", ["starting_structure", "step", "path"])
def test_the_known_sources_still_load(tmp_path, source):
    sim = load_simulation(str(_manifest(tmp_path, source)))

    assert sim.phases[0].steps[0].input_coords.source == source


def test_a_missing_input_coords_still_means_the_starting_structure(tmp_path):
    path = _manifest(tmp_path, "starting_structure")
    doc = json.loads(path.read_text(encoding="utf-8"))
    del doc["steps"][0]["input_coords"]
    path.write_text(json.dumps(doc), encoding="utf-8")

    sim = load_simulation(str(path))

    assert sim.phases[0].steps[0].input_coords.source == "starting_structure"


def test_validate_manifest_fails_on_it(tmp_path, capsys):
    rc = main(["validate", "--manifest", str(_manifest(tmp_path, "starting-structure"))])

    err = capsys.readouterr().err
    assert rc == 1
    assert "input_coords.source" in err


def test_the_gui_refuses_an_unknown_source_on_a_step_update(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ambermeta.gui.api import routes

    _manifest(tmp_path, "starting_structure")
    routes.set_base_directory(str(tmp_path))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    client = TestClient(app)
    assert client.post("/api/document/open", json={"path": "sim.json"}).status_code == 200

    r = client.put("/api/steps/s1", json={"input_coords": {"source": "restart"}})

    assert r.status_code == 422
    step = client.get("/api/document").json()["simulation"]["phases"][0]["steps"][0]
    assert step["input_coords"]["source"] == "starting_structure"


def test_opening_a_manifest_with_an_unknown_source_is_a_clean_400(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ambermeta.gui.api import routes

    _manifest(tmp_path, "starting-structure")
    routes.set_base_directory(str(tmp_path))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    r = TestClient(app).post("/api/document/open", json={"path": "sim.json"})

    assert r.status_code == 400
    assert "input_coords.source" in r.json()["detail"]
