from __future__ import annotations

from ambermeta import manifest as m


def test_normalize_manifest_toml_stages_dict():
    """_normalize_manifest must unwrap {"stages": [...]} without TypeError."""
    manifest = {"stages": [{"name": "heat", "stage_role": "heating"},
                            {"name": "prod", "stage_role": "production"}],
                "global_prmtop": "system.prmtop"}
    entries = list(m._normalize_manifest(manifest))
    assert [e["name"] for e in entries] == ["heat", "prod"]
