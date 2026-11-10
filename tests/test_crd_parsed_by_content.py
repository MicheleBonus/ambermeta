"""A `.crd` file is parsed as whatever its content says, in the Inspector and in `info`.

AMBER uses `.crd` both for LEaP's single-frame coordinate file and for trajectories.
The file list and Discover already type it by content (`coords.sniff_coordinate_kind`),
so the sample's CH3L1_HUMAN_6NAG.crd shows as input coordinates in the tree. But clicking
it handed it to the trajectory parser, and the Inspector said "Kind: mdcrd" with no atoms
and an "ASCII trajectory" warning, for a 64,528-atom restart with a box. `ambermeta info`
and `validate` picked the parser by extension the same way and printed `n_atoms: 0`.
"""
from __future__ import annotations

import pytest

from ambermeta.cli import main
from ambermeta.gui.api.core_bridge import file_metadata


@pytest.fixture
def leap_crd(sample_md_data_dir):
    return sample_md_data_dir / "CH3L1_HUMAN_6NAG.crd"


def test_the_inspector_reads_a_leap_crd_as_input_coordinates(leap_crd):
    meta = file_metadata(str(leap_crd))

    assert meta["kind"] == "inpcrd"
    assert meta["details"]["natoms"] == 64528
    assert meta["details"]["has_box"] is True
    assert not any("trajectory" in w.lower() for w in meta["warnings"])


def test_info_reads_a_leap_crd_as_input_coordinates(leap_crd, capsys):
    rc = main(["info", str(leap_crd)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "natoms: 64528" in out
    assert "ASCII trajectory" not in out


def test_a_crd_trajectory_is_still_a_trajectory(tmp_path):
    traj = tmp_path / "prod.crd"
    # An ASCII trajectory: a title, then coordinate data straight away (10F8.3).
    traj.write_text("trajectory written by cpptraj\n"
                    "   1.000   2.000   3.000   4.000   5.000   6.000\n", encoding="utf-8")

    assert file_metadata(str(traj))["kind"] == "mdcrd"
