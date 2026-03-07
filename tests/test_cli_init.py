from __future__ import annotations

import json
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


def test_init_auto_mode_groups_stages_deterministically(tmp_path):
    (tmp_path / "system.prmtop").write_text("", encoding="utf-8")
    (tmp_path / "prod_002.mdout").write_text("", encoding="utf-8")
    (tmp_path / "prod_001.mdin").write_text("", encoding="utf-8")
    (tmp_path / "prod_001.mdout").write_text("", encoding="utf-8")
    (tmp_path / "prod_002.mdin").write_text("", encoding="utf-8")

    args = SimpleNamespace(
        directory=str(tmp_path),
        output="manifest.json",
        template="standard",
        auto=True,
        format="json",
        dry_run=False,
        validate=False,
        force=False,
    )

    result = _init_command(args)
    assert result == 0

    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert payload["stages"][0]["name"] == "prod"
    # deterministic pick via sorted traversal
    assert payload["stages"][0]["mdin"] == "prod_002.mdin"
    assert payload["stages"][0]["mdout"] == "prod_002.mdout"


def test_init_auto_mode_json_output_structure(tmp_path):
    (tmp_path / "system.prmtop").write_text("", encoding="utf-8")
    (tmp_path / "heat_001.mdin").write_text("", encoding="utf-8")
    (tmp_path / "heat_001.mdout").write_text("", encoding="utf-8")

    args = SimpleNamespace(
        directory=str(tmp_path),
        output="manifest.json",
        template="standard",
        auto=True,
        format="json",
        dry_run=False,
        validate=False,
        force=False,
    )

    result = _init_command(args)
    assert result == 0

    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert list(payload.keys()) == ["stages"]
    assert payload["stages"][0]["name"] == "heat"
    assert payload["stages"][0]["stage_role"] == "heating"
    assert payload["stages"][0]["prmtop"] == "system.prmtop"
    assert payload["stages"][0]["mdin"] == "heat_001.mdin"
    assert payload["stages"][0]["mdout"] == "heat_001.mdout"


def test_init_auto_mode_dry_run_does_not_write_output(tmp_path):
    (tmp_path / "prod_001.mdin").write_text("", encoding="utf-8")

    args = SimpleNamespace(
        directory=str(tmp_path),
        output="manifest.yaml",
        template="standard",
        auto=True,
        format="yaml",
        dry_run=True,
        validate=False,
        force=False,
    )

    result = _init_command(args)
    assert result == 0
    assert not (tmp_path / "manifest.yaml").exists()
