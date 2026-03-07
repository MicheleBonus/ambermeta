from __future__ import annotations

from types import SimpleNamespace

from ambermeta.cli import _init_command


def test_init_standard_uses_discovered_stage_files(tmp_path):
    (tmp_path / "system.prmtop").write_text("", encoding="utf-8")
    (tmp_path / "prod_001.mdin").write_text("", encoding="utf-8")
    (tmp_path / "prod_001.mdout").write_text("", encoding="utf-8")
    (tmp_path / "prod_001.nc").write_text("", encoding="utf-8")
    (tmp_path / "prod_001.rst7").write_text("", encoding="utf-8")

    args = SimpleNamespace(directory=str(tmp_path), output="manifest.yaml", template="standard")
    result = _init_command(args)

    assert result == 0

    content = (tmp_path / "manifest.yaml").read_text(encoding="utf-8")
    assert "name: prod" in content
    assert "stage_role: production" in content
    assert "prmtop: system.prmtop" in content
    assert "mdin: prod_001.mdin" in content
    assert "mdout: prod_001.mdout" in content
    assert "mdcrd: prod_001.nc" in content
    assert "inpcrd: prod_001.rst7" in content
    assert "mdin: prod.in" not in content


def test_init_minimal_falls_back_when_no_groups(tmp_path):
    args = SimpleNamespace(directory=str(tmp_path), output="manifest.yaml", template="minimal")
    result = _init_command(args)

    assert result == 0

    content = (tmp_path / "manifest.yaml").read_text(encoding="utf-8")
    assert "name: production" in content
    assert "mdin: prod.in" in content
