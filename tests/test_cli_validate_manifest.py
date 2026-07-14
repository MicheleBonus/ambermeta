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
    assert "Continuity / sequence findings" in out
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
