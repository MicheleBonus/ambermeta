from __future__ import annotations

import json
from types import SimpleNamespace

from ambermeta import manifest as m
from ambermeta.cli import _init_command, main


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
    assert "name: prod_001" in content
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
    # After fix: each numbered file is its own stage, no collapse
    assert len(payload["stages"]) == 2
    assert payload["stages"][0]["name"] == "prod_001"
    assert payload["stages"][1]["name"] == "prod_002"
    # each stage keeps only its own files
    assert payload["stages"][0]["mdin"] == "prod_001.mdin"
    assert payload["stages"][0]["mdout"] == "prod_001.mdout"
    assert payload["stages"][1]["mdin"] == "prod_002.mdin"
    assert payload["stages"][1]["mdout"] == "prod_002.mdout"


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
    # topology lives at top-level, not per-stage
    assert "global_prmtop" in payload
    assert payload["global_prmtop"] == "system.prmtop"
    assert "hmr_prmtop" not in payload
    assert "stages" in payload
    # After fix: stem is kept as-is, no numeric suffix stripped
    assert payload["stages"][0]["name"] == "heat_001"
    assert payload["stages"][0]["stage_role"] == "heating"
    # prmtop is no longer per-stage; topology is at top-level
    assert "prmtop" not in payload["stages"][0]
    assert payload["stages"][0]["mdin"] == "heat_001.mdin"
    assert payload["stages"][0]["mdout"] == "heat_001.mdout"


def test_init_auto_splits_normal_and_hmr_topology(tmp_path):
    from ambermeta import manifest as m
    from ambermeta.cli import main
    d = tmp_path
    # normal + HMR topologies, distinguishable by H masses
    from test_core_hardening import _write_prmtop_atoms
    _write_prmtop_atoms(d / "system.prmtop", ["N", "H1"], [14.0, 1.008])
    _write_prmtop_atoms(d / "system.hmr.prmtop", ["N", "H1"], [14.0, 3.024])
    (d / "prod.in").write_text("&cntrl\n imin=0, dt=0.004, nstlim=10,\n/\n")
    (d / "prod.out").write_text("Final Performance Info\n")
    main(["init", str(d), "--auto", "-o", "manifest.yaml", "--force"])
    loaded = m.load_manifest(str(d / "manifest.yaml"), expand_env=False)
    assert loaded.get("global_prmtop", "").endswith("system.prmtop")
    assert loaded.get("hmr_prmtop", "").endswith("system.hmr.prmtop")


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


def test_init_auto_csv_roundtrips(tmp_path):
    d = tmp_path
    (d / "system.prmtop").write_text("dummy")
    (d / "prod_001.in").write_text("&cntrl\n/\n")
    (d / "prod_001.out").write_text("Final Performance Info\n")
    rc = main(["init", str(d), "--auto", "--format", "csv",
               "-o", "manifest.csv", "--force"])
    assert rc == 0
    loaded = m.load_manifest(str(d / "manifest.csv"), expand_env=False)
    stages = loaded if isinstance(loaded, list) else loaded["stages"]
    # After fix: full stem is kept, no numeric suffix stripped
    assert [s["name"] for s in stages] == ["prod_001"]


def test_init_auto_keeps_every_numbered_file(tmp_path):
    d = tmp_path
    (d / "system.prmtop").write_text("dummy")
    for i in range(1, 6):
        (d / f"ntp_prod_{i:04d}.mdin").write_text("&cntrl\n/\n")
        (d / f"ntp_prod_{i:04d}.mdout").write_text("Final Performance Info\n")
        (d / f"ntp_prod_{i:04d}.rst").write_text("title\n 1\n")
    rc = main(["init", str(d), "--auto", "-o", "manifest.yaml", "--force"])
    assert rc == 0
    loaded = m.load_manifest(str(d / "manifest.yaml"), expand_env=False)
    stages = loaded["stages"] if isinstance(loaded, dict) else loaded
    names = sorted(s["name"] for s in stages)
    assert names == [f"ntp_prod_{i:04d}" for i in range(1, 6)]
    # each stage keeps its own mdin/mdout, none collapsed
    assert all(s.get("mdin") and s.get("mdout") for s in stages)
