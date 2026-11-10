"""A `--prmtop` / `--hmr-prmtop` that exists but cannot be read is reported, like a missing one.

A path that does not exist gets "WARNING: Requested global prmtop not found" on every
stage. A path that exists but does not parse -- a directory, a `.gz`, a file the account
cannot read -- went through `_safe_parse` with no stage to record the failure on, and the
caller dropped the None without a word: no "using global prmtop" note, no warning, and
the HMR time-step check silently never ran.
"""
from __future__ import annotations

import pytest

from ambermeta.errors import AmberMetaError
from ambermeta.protocol import auto_discover

MDIN = "production\n &cntrl\n  imin = 0, nstlim = 1000, dt = 0.002,\n /\n"


@pytest.fixture
def run_dir(tmp_path):
    (tmp_path / "prod.mdin").write_text(MDIN, encoding="utf-8")
    (tmp_path / "topo").mkdir()
    return tmp_path


@pytest.mark.parametrize("option", ["global_prmtop", "hmr_prmtop"])
def test_a_prmtop_that_exists_but_cannot_be_read_is_warned_about(run_dir, option):
    proto = auto_discover(str(run_dir), manifest=[{"name": "prod", "mdin": "prod.mdin"}],
                          skip_cross_stage_validation=True, **{option: "topo"})

    notes = proto.stages[0].validation
    assert any(n.startswith("WARNING: Requested") and "could not be read" in n and "topo" in n
               for n in notes), notes


def test_strict_makes_it_fatal(run_dir):
    with pytest.raises(AmberMetaError):
        auto_discover(str(run_dir), manifest=[{"name": "prod", "mdin": "prod.mdin"}],
                      skip_cross_stage_validation=True, global_prmtop="topo", strict=True)
