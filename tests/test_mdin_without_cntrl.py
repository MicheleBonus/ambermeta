"""An `.in` file with no `&cntrl` namelist is warned about, not read as an MD run.

`tleap.in`, `cpptraj.in` and a misspelt `&cntl` all share the mdin extension. With no
namelist to read, every setting kept AMBER's default, and the file was described as a
complete run: `info` showed "Molecular Dynamics (MD)", `dt: 0.001`, NVE and an 8 A
cutoff; `validate` printed "Validation PASSED"; `plan --recursive` chained a stage named
"tleap" after production, whose methods summary was those defaults. The settings are
kept (other code reads them), but the file now says they were not read from it.
"""
from __future__ import annotations

import pytest

from ambermeta.cli import main
from ambermeta.parsers.mdin import MdinParser
from ambermeta.protocol import auto_discover

TLEAP = ("source leaprc.protein.ff19SB\nmol = loadpdb protein.pdb\n"
         "saveamberparm mol system.prmtop system.inpcrd\nquit\n")


@pytest.mark.parametrize("content", [TLEAP, "", "minimisation\n &cntl\n  imin = 1,\n /\n"])
def test_the_mdin_parser_warns_when_there_is_no_cntrl(tmp_path, content):
    path = tmp_path / "leap.in"
    path.write_text(content, encoding="utf-8")

    warnings = MdinParser(str(path)).parse().details.warnings

    assert any("&cntrl" in w and "not read from" in w for w in warnings), warnings


def test_a_real_mdin_gets_no_such_warning(sample_md_data_dir):
    warnings = MdinParser(str(sample_md_data_dir / "ntp_prod_0001.mdin")).parse().details.warnings

    assert not any("&cntrl" in w and "not read from" in w for w in warnings)


def test_validate_no_longer_passes_it_clean(tmp_path, capsys):
    path = tmp_path / "tleap.in"
    path.write_text(TLEAP, encoding="utf-8")

    main(["validate", str(path)])

    out = capsys.readouterr().out
    assert "&cntrl" in out
    assert "Validation PASSED\n" not in out


def test_plan_carries_the_warning_on_the_stage(tmp_path):
    (tmp_path / "tleap.in").write_text(TLEAP, encoding="utf-8")

    stage = auto_discover(str(tmp_path), manifest=[{"name": "tleap", "mdin": "tleap.in"}],
                          skip_cross_stage_validation=True).stages[0]

    assert any("&cntrl" in v for v in stage.validation), stage.validation
