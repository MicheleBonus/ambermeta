import json
from types import SimpleNamespace

import ambermeta.cli as cli
from ambermeta.simulation import load_simulation


V2_MANIFEST = """\
version: 2
simulation:
  topologies:
    - id: top_wt
      path: system.prmtop
      kind: normal
  starting_structure: null
phases:
  - { id: ph_min, name: Minimization, role: minimization, order: 0 }
  - { id: ph_prod, name: Production, role: production, order: 1 }
steps:
  - id: st_min
    name: minimize
    phase: ph_min
    order: 0
    topology: top_wt
    input_coords: { source: starting_structure }
    mdin: min.in
    mdout: min.out
  - id: st_prod_001
    name: prod_001
    phase: ph_prod
    order: 0
    topology: top_wt
    input_coords: { source: step, ref: st_min }
    mdin: prod.in
    mdout: prod.out
    mdcrd: prod.nc
"""


def _args(manifest, **over):
    base = dict(manifest=manifest, output=None, format=None)
    base.update(over)
    return SimpleNamespace(**base)


def test_export_v2_to_v2_stdout_is_v2_payload(tmp_path, capsys):
    """export re-emits a v2 manifest (a format conversion, not an "upgrade" — the v1
    file format it used to auto-migrate no longer exists)."""
    m = tmp_path / "sim.yaml"
    m.write_text(V2_MANIFEST, encoding="utf-8")
    rc = cli._export_command(_args(str(m)))          # no --output -> json stdout
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 2
    assert any(p["role"] == "production" for p in payload["phases"])
    assert any(s["name"] == "prod_001" for s in payload["steps"])


def test_export_v2_to_v2_file_roundtrips(tmp_path):
    m = tmp_path / "sim.yaml"
    m.write_text(V2_MANIFEST, encoding="utf-8")
    dest = tmp_path / "up.yaml"
    rc = cli._export_command(_args(str(m), output=str(dest)))
    assert rc == 0
    sim = load_simulation(str(dest))
    assert sim.version == 2
    assert {p.role for p in sim.phases} >= {"minimization", "production"}


def test_export_missing_manifest_returns_1(tmp_path):
    rc = cli._export_command(_args(str(tmp_path / "nope.yaml")))
    assert rc == 1


def test_export_rejects_a_non_v2_manifest_cleanly(tmp_path, capsys):
    """The v1 file format is gone; export must fail with a clear message, not a crash."""
    m = tmp_path / "old.yaml"
    m.write_text("stages:\n  - name: prod\n    mdin: prod.in\n", encoding="utf-8")
    rc = cli._export_command(_args(str(m)))
    assert rc == 1
    err = capsys.readouterr().err
    assert "not a v2 manifest" in err
