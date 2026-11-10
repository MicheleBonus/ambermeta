"""When two files of one kind share a run's name, the run says which one it did not read.

The scan groups files by stem, so `prod_0001.mdcrd` and `prod_0001.nc` (or
`system.parm7` beside `system.prmtop`) compete for one slot. The first in sorted order
wins, deterministically, and the other was recorded under an internal key that the
stage builder then filtered out with all the others: the `.nc` was never mentioned, and
the ASCII trajectory that was kept has no frame times, so the trajectory-duration check
quietly did not run either.
"""
from __future__ import annotations

from ambermeta.protocol import auto_discover

MDIN = "production\n &cntrl\n  imin = 0, nstlim = 1000, dt = 0.002, ntwx = 100,\n /\n"


def _tree(tmp_path, *names):
    (tmp_path / "prod_0001.mdin").write_text(MDIN, encoding="utf-8")
    for name in names:
        (tmp_path / name).write_text("title\n   1.000   2.000   3.000\n", encoding="utf-8")
    return auto_discover(str(tmp_path), skip_cross_stage_validation=True)


def _stage(proto, name):
    return next(s for s in proto.stages if s.name == name)


def test_the_file_not_read_is_named_on_the_run(tmp_path):
    stage = _stage(_tree(tmp_path, "prod_0001.mdcrd", "prod_0001.nc"), "prod_0001")

    notes = [v for v in stage.validation if "prod_0001.nc" in v]
    assert notes, stage.validation
    assert "prod_0001.mdcrd" in notes[0]
    assert not notes[0].startswith("INFO:")


def test_every_file_not_read_is_named(tmp_path):
    stage = _stage(_tree(tmp_path, "prod_0001.crd", "prod_0001.mdcrd", "prod_0001.nc"),
                   "prod_0001")

    note = next(v for v in stage.validation if "not read" in v)
    assert "prod_0001.mdcrd" in note and "prod_0001.nc" in note


def test_a_run_with_one_file_per_kind_says_nothing_of_the_kind(tmp_path):
    stage = _stage(_tree(tmp_path, "prod_0001.nc"), "prod_0001")

    assert not any("not read" in v for v in stage.validation)


def test_discover_warns_about_it_too(tmp_path):
    from ambermeta.gui.api.core_bridge import discover_draft

    (tmp_path / "prod_0001.mdin").write_text(MDIN, encoding="utf-8")
    for name in ("prod_0001.mdcrd", "prod_0001.nc"):
        (tmp_path / name).write_text("title\n   1.000   2.000   3.000\n", encoding="utf-8")

    result = discover_draft(str(tmp_path))
    warnings = result["warnings"]

    assert any("prod_0001.nc" in w and "not read" in w for w in warnings), warnings
