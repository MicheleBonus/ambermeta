from __future__ import annotations

import pytest
from ambermeta import manifest as m


def test_normalize_stage_keys_aliases():
    entry = {"stage": "prod_001", "role": "production",
             "expected_gap_ps": 2.0, "gap_tolerance_ps": 0.1}
    out = m.normalize_stage_keys(entry)
    assert out["name"] == "prod_001"
    assert out["stage_role"] == "production"
    assert out["gaps"] == {"expected": 2.0, "tolerance": 0.1}


@pytest.mark.parametrize("fmt,ext", [("yaml", "yaml"), ("json", "json"),
                                     ("toml", "toml"), ("csv", "csv")])
def test_write_then_load_roundtrip(tmp_path, fmt, ext):
    pytest.importorskip("yaml") if fmt == "yaml" else None
    payload = {"stages": [
        {"name": "min", "stage_role": "minimization", "prmtop": "s.prmtop",
         "mdin": "min.in", "mdout": "min.out"},
        {"name": "prod_001", "stage_role": "production", "prmtop": "s.prmtop",
         "mdin": "prod_001.in", "mdout": "prod_001.out",
         "gaps": {"expected": 2.0, "tolerance": 0.1}},
    ]}
    path = tmp_path / f"manifest.{ext}"
    m.write_manifest(payload, str(path), fmt)
    loaded = m.load_manifest(str(path), expand_env=False)
    stages = loaded["stages"] if isinstance(loaded, dict) else loaded
    names = [s["name"] for s in stages]
    assert names == ["min", "prod_001"]
    prod = [s for s in stages if s["name"] == "prod_001"][0]
    assert prod["stage_role"] == "production"
    assert prod.get("gaps", {}).get("expected") == 2.0
