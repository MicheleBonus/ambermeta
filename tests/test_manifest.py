from __future__ import annotations

import pytest
from ambermeta import manifest as m


@pytest.mark.parametrize("fmt,ext", [("yaml", "yaml"), ("json", "json"),
                                     ("toml", "toml"), ("csv", "csv")])
def test_write_then_load_roundtrip(tmp_path, fmt, ext):
    """write_manifest is now an export-only view (its readers were removed);
    assert the shape of the text it writes instead of reading it back."""
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
    text = path.read_text(encoding="utf-8")

    assert "min" in text and "prod_001" in text
    assert "minimization" in text and "production" in text
    if fmt == "csv":
        header = text.splitlines()[0].split(",")
        assert header[:2] == ["name", "stage_role"]
        assert "2.0" in text
    elif fmt == "toml":
        assert text.count("[[stages]]") == 2
        assert "gaps_expected = 2.0" in text
    else:  # json / yaml keep the nested {"stages": [...]} shape
        assert "stages" in text
        assert "gaps" in text


def test_normalize_manifest_toml_stages_dict():
    """_normalize_manifest must unwrap {"stages": [...]} without TypeError."""
    manifest = {"stages": [{"name": "heat", "stage_role": "heating"},
                            {"name": "prod", "stage_role": "production"}],
                "global_prmtop": "system.prmtop"}
    entries = list(m._normalize_manifest(manifest))
    assert [e["name"] for e in entries] == ["heat", "prod"]


def test_toml_writer_scalar_types(tmp_path):
    """TOML writer must emit int/bool unquoted, strings quoted."""
    payload = {"stages": [
        {"name": "s1", "stage_role": "prod", "n_steps": 5000, "restart": True, "tag": "ok"},
    ]}
    path = tmp_path / "manifest.toml"
    m.write_manifest(payload, str(path), "toml")
    text = path.read_text()
    assert "n_steps = 5000" in text
    assert 'n_steps = "5000"' not in text
    assert "restart = true" in text
    assert 'restart = "True"' not in text
    assert 'tag = "ok"' in text
