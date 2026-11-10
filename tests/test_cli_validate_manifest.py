import json
from ambermeta.cli import main

# a v2 sim whose production sequence skips index 3 -> a sequence-hole (missing_run) finding.
# detect_sequence_gaps runs on step *names*, so the steps must be NAMED prod_000N.
V2_GAP = """\
version: 2
simulation:
  topologies: [ { id: top_wt, path: wt.prmtop, kind: normal } ]
  starting_structure: wt.inpcrd
phases:
  - { id: ph_prod, name: Production, role: production, order: 0 }
steps:
  - { id: st1, name: prod_0001, phase: ph_prod, order: 0, topology: top_wt, input_coords: { source: starting_structure }, mdin: prod_0001.in }
  - { id: st2, name: prod_0002, phase: ph_prod, order: 1, topology: top_wt, input_coords: { source: step, ref: st1 }, mdin: prod_0002.in }
  - { id: st4, name: prod_0004, phase: ph_prod, order: 2, topology: top_wt, input_coords: { source: step, ref: st2 }, mdin: prod_0004.in }
"""


def _write(tmp_path):
    m = tmp_path / "sim.yaml"
    m.write_text(V2_GAP, encoding="utf-8")
    return m


def test_validate_manifest_reports_sequence_gap(tmp_path, capsys):
    # The manifest references files that do not exist here, so validation fails (rc 1);
    # the point of this test is that the sequence-hole finding is surfaced to the user.
    m = _write(tmp_path)
    rc = main(["validate", "--manifest", str(m)])
    out = capsys.readouterr().out
    assert rc == 1                                  # missing referenced files -> not ok
    assert "Findings:" in out
    assert "prod" in out                            # the missing_run finding names the base "prod"


def test_validate_manifest_json_format(tmp_path, capsys):
    m = _write(tmp_path)
    main(["validate", "--manifest", str(m), "--format", "json"])
    report = json.loads(capsys.readouterr().out)
    assert "suggestions" in report and "stage_issues" in report
    assert any(s["kind"] == "missing_run" for s in report["suggestions"])


def test_validate_requires_files_or_manifest(capsys):
    rc = main(["validate"])
    assert rc == 2


def test_an_unnamed_step_is_validated_under_its_id(tmp_path, capsys, sample_md_data_dir):
    # `name` is optional on a v2 step (docs/manifest.md). The flat engine underneath
    # requires one, so an unnamed step used to stop validation with "Unexpected error
    # (ValueError: Each manifest entry must include a 'name'.)". The id is what the
    # step is called instead, as it is in the GUI's continuity messages.
    sample = sample_md_data_dir
    manifest = tmp_path / "unnamed.json"
    manifest.write_text(json.dumps({
        "version": 2,
        "simulation": {
            "topologies": [{"id": "top", "path": str(sample / "CH3L1_HUMAN_6NAG.top"),
                            "kind": "normal"}],
            "starting_structure": str(sample / "ntp_prod_0000.rst"),
        },
        "phases": [{"id": "ph", "name": "Production", "role": "production", "order": 0}],
        "steps": [{"id": "st_first", "phase": "ph", "order": 0, "topology": "top",
                   "input_coords": {"source": "starting_structure"},
                   "mdin": str(sample / "ntp_prod_0001.mdin"),
                   "mdout": str(sample / "ntp_prod_0001.mdout")}],
    }), encoding="utf-8")

    rc = main(["validate", "--manifest", str(manifest), "--format", "json"])

    out = capsys.readouterr().out
    assert rc == 0
    report = json.loads(out)
    # The sample's runs used a 4-fs time step on a standard-mass topology, which is a
    # Run check on this step; the card names the step by its id.
    checks = [s for s in report["suggestions"] if s["kind"] == "step_check"]
    assert checks
    assert all(s["evidence"].startswith("st_first: ") for s in checks)
