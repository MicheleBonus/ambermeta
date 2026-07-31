from __future__ import annotations

import pytest

from ambermeta import manifest as m
from ambermeta.errors import AmberMetaError


def test_normalize_manifest_toml_stages_dict():
    """_normalize_manifest must unwrap {"stages": [...]} without TypeError."""
    manifest = {"stages": [{"name": "heat", "stage_role": "heating"},
                            {"name": "prod", "stage_role": "production"}],
                "global_prmtop": "system.prmtop"}
    entries = list(m._normalize_manifest(manifest))
    assert [e["name"] for e in entries] == ["heat", "prod"]


def test_a_csv_path_is_refused_with_the_formats_that_do_work(tmp_path):
    """CSV/TOML are not manifest formats in either direction — the reader has to say
    so without implying an export path that no longer exists."""
    from ambermeta.simulation import load_simulation

    bad = tmp_path / "stages.csv"
    bad.write_text("name,mdin\nprod,prod.in\n", encoding="utf-8")
    with pytest.raises(AmberMetaError,
                       match=r"reads and writes manifests as YAML or JSON only"):
        load_simulation(str(bad))
