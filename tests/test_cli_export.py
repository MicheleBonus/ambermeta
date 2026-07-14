import json
from types import SimpleNamespace

import ambermeta.cli as cli
from ambermeta.simulation import load_simulation


V1_MANIFEST = """\
global_prmtop: system.prmtop
stages:
  - name: minimize
    stage_role: minimization
    mdin: min.in
    mdout: min.out
  - name: prod_001
    stage_role: production
    mdin: prod.in
    mdout: prod.out
    mdcrd: prod.nc
"""


def _args(manifest, **over):
    base = dict(manifest=manifest, to="v2", output=None, format=None)
    base.update(over)
    return SimpleNamespace(**base)


def test_export_v1_to_v2_stdout_is_v2_payload(tmp_path, capsys):
    m = tmp_path / "v1.yaml"
    m.write_text(V1_MANIFEST, encoding="utf-8")
    rc = cli._export_command(_args(str(m)))          # default --to v2, no --output -> json stdout
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 2
    assert any(p["role"] == "production" for p in payload["phases"])
    assert any(s["name"] == "prod_001" for s in payload["steps"])


def test_export_v1_to_v2_file_roundtrips(tmp_path):
    m = tmp_path / "v1.yaml"
    m.write_text(V1_MANIFEST, encoding="utf-8")
    dest = tmp_path / "up.yaml"
    rc = cli._export_command(_args(str(m), output=str(dest)))
    assert rc == 0
    sim = load_simulation(str(dest))
    assert sim.version == 2
    assert {p.role for p in sim.phases} >= {"minimization", "production"}


def test_export_to_legacy_flat(tmp_path, capsys):
    # start from a v2 manifest, downgrade to a legacy flat stages: list
    m = tmp_path / "v1.yaml"
    m.write_text(V1_MANIFEST, encoding="utf-8")
    up = tmp_path / "up.json"
    cli._export_command(_args(str(m), output=str(up)))       # -> v2
    capsys.readouterr()                                       # discard the "Wrote v2 manifest" line
    rc = cli._export_command(_args(str(up), to="legacy"))    # v2 -> legacy stdout (json)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "stages" in payload
    names = [s["name"] for s in payload["stages"]]
    assert "minimize" in names and "prod_001" in names
    assert payload["stages"][0]["stage_role"] == "minimization"


def test_export_missing_manifest_returns_1(tmp_path):
    rc = cli._export_command(_args(str(tmp_path / "nope.yaml")))
    assert rc == 1
