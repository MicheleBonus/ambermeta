"""The methods summary as Markdown a person can read and paste from.

From the workflow walk-through (`.claude/ux-audit/reports/2026-11-10-workflow.md`, E1): the
methods summary is careful (every value says where it came from) but it was JSON only, in
both front ends, so writing a Methods section meant reading nested JSON by hand.

`methods_summary.md` is a rendering of the same digest and nothing more: no generated prose,
so nothing is said that the JSON does not say. A key the renderer does not know is still
shown, as `Key: value`, so a field added to the digest later cannot vanish from the page.
"""
from __future__ import annotations

import json
import os

import pytest


def _run(argv, capsys, monkeypatch):
    from ambermeta.cli import main

    monkeypatch.setenv("NO_COLOR", "1")
    try:
        rc = main(argv)
    except SystemExit as exc:
        rc = exc.code
    out = capsys.readouterr()
    return rc, out.out, out.err


@pytest.fixture
def sample_digest(sample_md_data_dir, tmp_path, capsys, monkeypatch):
    manifest = tmp_path / "sim.yaml"
    rc, _, err = _run(["discover", str(sample_md_data_dir), "--write", str(manifest)],
                      capsys, monkeypatch)
    assert rc == 0, err
    out = tmp_path / "m.json"
    rc, _, err = _run(["plan", "-m", str(manifest), "--methods-summary-path", str(out)],
                      capsys, monkeypatch)
    assert rc == 0, err
    return json.loads(out.read_text(encoding="utf-8"))


def _render(digest):
    from ambermeta.methods_summary import render_methods_markdown
    return render_methods_markdown(digest)


def test_every_section_has_a_heading(sample_digest):
    text = _render(sample_digest)
    for heading in ("# Methods summary", "## Project", "## Software", "## System",
                    "## Protocol", "### 1. Production", "## Continuity", "## Findings",
                    "## Not recorded in the run files"):
        assert f"\n{heading}\n" in "\n" + text, heading


def test_a_setting_is_a_table_row_with_its_source(sample_digest):
    text = _render(sample_digest)
    assert "| Setting | Value | Source | Runs that differ |" in text
    # The sample ran at dt = 0.004 ps, set in its mdins.
    assert "| Time step (fs) | 4 | mdin |" in text


def test_values_that_differ_between_runs_are_spelled_out():
    digest = {"protocol": [{
        "name": "Equilibration", "role": "equilibration", "runs": 2,
        "settings": {
            "ensemble": {"value": "NVT", "source": "derived", "runs": 1,
                         "sequence_in_run_order": ["NVT", "NPT"]},
            "target_temperature_K": {"value": 300.0, "source": "mdin", "runs": 1,
                                     "other_values": [{"value": 310.0, "runs": 1,
                                                       "example_run": "eq_0002"}]},
        }}]}
    text = _render(digest)
    assert "| Ensemble | NVT | derived | 1 run; in run order: NVT -> NPT |" in text
    assert ("| Target temperature (K) | 300 | mdin | 1 run; also 310 (1 run, e.g. "
            "eq_0002) |") in text


def test_acknowledged_findings_are_listed_with_their_notes():
    digest = {"findings": {"total": 1, "patterns": 1, "grouped": [
        {"kind": "missing_run", "occurrences": 1, "example": "prod run 3 is missing"}],
        "acknowledged": [{"finding": "prod run 3 is missing: The prod runs here are "
                                     "numbered 1-2, 4.",
                          "note": "prod_0003 crashed and was not deposited."}]}}
    text = _render(digest)
    assert "### Acknowledged by the depositor" in text
    assert ("- prod run 3 is missing: The prod runs here are numbered 1-2, 4.\n"
            "  Note: prod_0003 crashed and was not deposited.") in text


def test_what_the_run_files_do_not_record_is_a_checklist(sample_digest):
    text = _render(sample_digest)
    assert "- [ ] water model name" in text


def test_a_key_the_renderer_does_not_know_is_still_shown():
    digest = {"protocol": [{"name": "Production", "role": "production", "runs": 1,
                            "settings": {}, "a_new_field": {"each": 2, "replicas": 3}}],
              "brand_new_section": {"count": 1}}
    text = _render(digest)
    assert "A new field: each 2, replicas 3" in text
    assert "Brand new section: count 1" in text


def test_the_rendering_is_deterministic(sample_digest):
    assert _render(sample_digest) == _render(sample_digest)


# --- where it is written --------------------------------------------------------------

@pytest.fixture
def manifest(sample_md_data_dir, tmp_path, capsys, monkeypatch):
    path = tmp_path / "sim.yaml"
    rc, _, err = _run(["discover", str(sample_md_data_dir), "--write", str(path)], capsys,
                      monkeypatch)
    assert rc == 0, err
    return path


def test_plan_out_writes_the_markdown_too(manifest, tmp_path, capsys, monkeypatch):
    results = tmp_path / "results"
    rc, out, err = _run(["plan", "-m", str(manifest), "--out", str(results)], capsys,
                        monkeypatch)
    assert rc == 0, err
    assert "methods_summary.md" in os.listdir(results)
    assert (results / "methods_summary.md").read_text(encoding="utf-8").startswith(
        "# Methods summary")


def test_plan_writes_the_markdown_where_asked(manifest, tmp_path, capsys, monkeypatch):
    target = tmp_path / "methods.md"
    rc, out, err = _run(["plan", "-m", str(manifest), "--methods-summary-md", str(target)],
                        capsys, monkeypatch)
    assert rc == 0, err
    assert target.read_text(encoding="utf-8").startswith("# Methods summary")
    assert "Wrote methods_summary_md:" in out


def test_the_module_renders_markdown_from_a_summary(manifest, tmp_path, capsys,
                                                    monkeypatch):
    from ambermeta.methods_summary import main

    summary = tmp_path / "summary.json"
    rc, _, err = _run(["plan", "-m", str(manifest), "--summary-path", str(summary)], capsys,
                      monkeypatch)
    assert rc == 0, err
    target = tmp_path / "methods.md"
    assert main([str(summary), "-o", str(target)]) == 0   # the extension says Markdown
    assert target.read_text(encoding="utf-8").startswith("# Methods summary")
    assert main([str(summary), "--format", "md"]) == 0
    assert capsys.readouterr().out.startswith("# Methods summary")


def test_the_gui_plan_writes_the_markdown(sample_md_data_dir, tmp_path):
    pytest.importorskip("fastapi")
    import shutil
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ambermeta.gui.api import routes

    base = tmp_path / "runs"
    shutil.copytree(sample_md_data_dir, base)
    routes.set_base_directory(str(base))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    client = TestClient(app)
    assert client.post("/api/document/discover", json={"recursive": True}).status_code == 200
    r = client.post("/api/plan", json={"methods_summary_md_path": "methods_summary.md"})
    assert r.status_code == 200, r.text
    assert [w["artifact"] for w in r.json()["written"]] == ["methods_summary_md"]
    assert (base / "methods_summary.md").read_text(encoding="utf-8").startswith(
        "# Methods summary")
