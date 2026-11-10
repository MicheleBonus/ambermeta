"""A numbered-sequence hole is a run whose files are missing, not a step that was renamed.

Sequence holes were detected from step names. Renaming `ntp_prod_0002` to `prod_two` in
the GUI left its files, its chain and its findings exactly as they were, and yet the run
was reported missing: a ghost card on the canvas, "ntp_prod sequence is missing member(s)
2" in the tray, and `validate --manifest --strict` failing on the saved document. The
numbering belongs to the run, which is its files; the name is a label.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ambermeta.cli import main  # noqa: E402
from ambermeta.gui.api import routes  # noqa: E402


def _missing_runs(suggestions):
    return [s for s in suggestions if s["kind"] == "missing_run"]


def test_renaming_a_step_in_the_gui_reports_no_missing_run(sample_md_data_dir):
    routes.set_base_directory(str(sample_md_data_dir))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    c = TestClient(app)
    doc = c.post("/api/document/discover", json={"recursive": False}).json()["document"]
    step = next(s for p in doc["simulation"]["phases"] for s in p["steps"]
                if s["name"] == "ntp_prod_0002")

    c.put(f"/api/steps/{step['id']}", json={"name": "prod_two"})
    report = c.post("/api/validate", json={}).json()

    assert _missing_runs(report["suggestions"]) == []


def test_a_renamed_step_in_a_manifest_reports_no_missing_run(tmp_path, sample_md_data_dir, capsys):
    sample = sample_md_data_dir
    steps = []
    for i, name in enumerate(["ntp_prod_0001", "prod_two", "ntp_prod_0003"], start=1):
        steps.append({
            "id": f"st{i}", "name": name, "phase": "ph", "order": i - 1, "topology": "top",
            "input_coords": ({"source": "starting_structure"} if i == 1
                             else {"source": "step", "ref": f"st{i - 1}"}),
            "mdin": str(sample / f"ntp_prod_000{i}.mdin"),
            "mdout": str(sample / f"ntp_prod_000{i}.mdout"),
            "rst": str(sample / f"ntp_prod_000{i}.rst"),
        })
    manifest = tmp_path / "renamed.json"
    manifest.write_text(json.dumps({
        "version": 2,
        "simulation": {"topologies": [{"id": "top", "path": str(sample / "CH3L1_HUMAN_6NAG.top"),
                                       "kind": "normal"}],
                       "starting_structure": str(sample / "ntp_prod_0000.rst")},
        "phases": [{"id": "ph", "name": "Production", "role": "production", "order": 0}],
        "steps": steps,
    }), encoding="utf-8")

    main(["validate", "--manifest", str(manifest), "--format", "json"])

    assert _missing_runs(json.loads(capsys.readouterr().out)["suggestions"]) == []
