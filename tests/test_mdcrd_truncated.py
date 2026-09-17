"""A trajectory that is truncated -- or that pmemd is still writing -- must not be read
as a complete one.

NetCDF-3 stores record variables interleaved at the end of the file, and a record that was
never written back reads as fill (0.0). So a partial trajectory reports its DECLARED frame
count with the tail zeroed. Measured on a real 260 MB AMBER trajectory cut to 4 KB, the
parser used to return: 250 frames, 5020.0 -> 0.0 ps, avg_dt -20.16, total_duration
-5020 ps, volume (0, 0, 0), box type "Triclinic" -- and the only warning was "Variable
timestep detected within file."

That 0.0 went straight into `_check_stage_pair` as the run's end time, so a half-copied
file manufactured a discontinuity in a healthy chain. The GUI scans live directories, so
this is the ordinary case of looking at a campaign while it runs, not an exotic one.
"""
from __future__ import annotations

import numpy as np
import pytest

from ambermeta import netcdf_backend
from ambermeta.legacy_extractors.mdcrd import parse_mdcrd

pytestmark = pytest.mark.skipif(
    not netcdf_backend.HAS_NETCDF or netcdf_backend.NETCDF_BACKEND != "netCDF4",
    reason="needs the netCDF4 backend to build an AMBER trajectory fixture",
)

FRAMES = 20
ATOMS = 4


@pytest.fixture
def trajectory(tmp_path):
    path = tmp_path / "prod.nc"
    nc = netcdf_backend.nc
    ds = nc.Dataset(str(path), "w", format="NETCDF3_64BIT_OFFSET")
    ds.Conventions = "AMBER"
    ds.createDimension("frame", None)
    ds.createDimension("atom", ATOMS)
    ds.createDimension("spatial", 3)
    ds.createDimension("cell_spatial", 3)
    ds.createDimension("cell_angular", 3)
    ds.createVariable("time", "f4", ("frame",))[:] = (
        1000.0 + np.arange(FRAMES, dtype="f4") * 20.0)
    ds.createVariable("coordinates", "f4", ("frame", "atom", "spatial"))[:] = (
        np.zeros((FRAMES, ATOMS, 3), dtype="f4"))
    ds.createVariable("cell_lengths", "f8", ("frame", "cell_spatial"))[:] = (
        np.full((FRAMES, 3), 30.0))
    ds.createVariable("cell_angles", "f8", ("frame", "cell_angular"))[:] = (
        np.full((FRAMES, 3), 90.0))
    ds.close()
    return path


def test_an_intact_trajectory_is_unchanged(trajectory):
    md = parse_mdcrd(str(trajectory))
    assert md.n_frames == FRAMES
    assert md.has_time is True
    assert md.time_start == pytest.approx(1000.0)
    assert md.time_end == pytest.approx(1000.0 + 19 * 20.0)
    assert md.avg_dt == pytest.approx(20.0)
    assert md.box_type == "Orthogonal"
    assert md.volume_stats == pytest.approx((27000.0, 27000.0, 27000.0))
    assert md.warnings == []


def _truncate(path, fraction):
    size = path.stat().st_size
    with open(path, "r+b") as fh:
        fh.truncate(int(size * fraction))


def test_a_truncated_trajectory_reports_no_times_and_says_why(trajectory):
    _truncate(trajectory, 0.6)
    md = parse_mdcrd(str(trajectory))

    # The whole point: nothing time-shaped survives to be believed downstream.
    assert md.has_time is False
    assert md.time_start is None and md.time_end is None
    assert md.avg_dt is None
    assert md.total_duration == 0.0
    assert 0 < md.n_frames < FRAMES, "the frames that ARE on disk are still counted"
    assert any("truncated or still being written" in w for w in md.warnings)
    assert not any("Variable timestep" in w for w in md.warnings), (
        "a truncated file was being reported as a variable-timestep one")


def test_a_truncated_trajectory_does_not_invent_a_zero_volume_triclinic_box(trajectory):
    _truncate(trajectory, 0.6)
    md = parse_mdcrd(str(trajectory))

    assert md.box_type != "Triclinic", "empty cell_angles read as a triclinic cell"
    if md.volume_stats is not None:
        assert min(md.volume_stats) > 0.0, "an unwritten record was averaged in as 0 A^3"
        assert md.volume_stats == pytest.approx((27000.0, 27000.0, 27000.0))


def test_a_trajectory_with_no_complete_records_claims_no_box(trajectory):
    _truncate(trajectory, 0.05)
    md = parse_mdcrd(str(trajectory))

    assert md.has_box is False
    assert md.volume_stats is None
    assert md.has_time is False


def test_a_truncated_trajectory_defers_continuity_to_the_mdout(trajectory):
    """`_check_stage_pair` reads `mdcrd.time_end` first and falls through to the mdout when
    it is absent -- which is exactly what withholding the fabricated 0.0 buys."""
    _truncate(trajectory, 0.6)
    md = parse_mdcrd(str(trajectory))
    assert getattr(md, "time_end", "missing") is None
