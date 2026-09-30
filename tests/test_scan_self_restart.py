"""A run's own output restart is not the coordinates it read.

`smart_group_files` groups by stem, so `prod_0002.mdin`, `prod_0002.mdout` and
`prod_0002.restrt` all land in one group -- and the scan path loaded that `.restrt` into
`stage.inpcrd`, the slot continuity reads the run's START time from. AMBER wrote that file
with ``-r`` at the END of the run, so every chunk was measured as starting exactly one
chunk after the previous one ended: a fabricated gap of a full chunk on every run in the
campaign, plus the "Gap detected without stated expectation" note beside it, while any
genuine discontinuity was hidden under the same constant offset.

On the repo's own five-chunk fixture that was 20000 ps of phantom gap on four of five
runs. On the 1097-run campaign this was found on, roughly a thousand.

The scan already has the right answer to hand: the mdout header's `begin time read from
input coords`, which is what `_check_stage_pair` falls through to once the self-produced
restart stops pre-empting it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ambermeta.protocol import auto_discover

FIXTURE = Path(__file__).resolve().parent / "data" / "amber" / "md_test_files"


@pytest.fixture(scope="module")
def scanned():
    return auto_discover(str(FIXTURE), recursive=True)


def _by_name(protocol):
    return {s.name: s for s in protocol.stages}


def test_chunks_that_run_back_to_back_report_no_gap(scanned):
    stages = _by_name(scanned)
    chunked = [stages[f"ntp_prod_{i:04d}"] for i in range(2, 6)]
    assert chunked, "fixture layout changed"
    for stage in chunked:
        assert stage.observed_gap_ps == pytest.approx(0.0, abs=1e-3), (
            f"{stage.name} reports a {stage.observed_gap_ps} ps gap; the mdout headers say "
            "these chunks are contiguous"
        )


def test_no_gap_warning_is_raised_on_a_continuous_chain(scanned):
    noisy = {
        s.name: [n for n in (s.continuity or []) if not str(n).startswith("INFO:")]
        for s in scanned.stages
    }
    offenders = {name: notes for name, notes in noisy.items() if notes}
    assert not offenders, f"unexpected continuity problems on a continuous chain: {offenders}"


def test_the_run_still_knows_which_restart_it_wrote(scanned):
    """The file is still loaded -- the atom-count and box cross-checks read it.

    Only continuity's reading of its clock changed, so `restart_path` (which goes into
    summary.json) says exactly what it said before.
    """
    stage = _by_name(scanned)["ntp_prod_0003"]
    assert stage.inpcrd is not None
    assert stage.restart_path and stage.restart_path.endswith("ntp_prod_0003.rst")


def test_a_coordinate_file_that_is_not_a_run_output_is_still_read_as_input(tmp_path):
    """The rule is scoped to groups that ARE runs.

    A bare `system.prmtop` + `system.inpcrd` pair names starting coordinates, not something
    a run produced, and its time is exactly what continuity should measure against.
    """
    (tmp_path / "system.prmtop").write_text("%FLAG POINTERS\n")
    (tmp_path / "system.inpcrd").write_text("start\n    3\n"
                                            "  0.0  0.0  0.0  1.0  1.0  1.0\n")
    protocol = auto_discover(str(tmp_path), recursive=False)
    stage = {s.name: s for s in protocol.stages}["system"]
    assert stage.inpcrd is not None
    assert not stage.inpcrd_is_own_restart


# ---------------------------------------------------------------------------
# Issue #87: a run that kept neither its mdin nor its mdout
# ---------------------------------------------------------------------------
#
# An incomplete deposit -- trajectories and restarts only, every `.mdout` gone -- is still a
# campaign of runs. `prod_0002.nc` beside `prod_0002.rst` is a run's `-x` and `-r` output,
# and the restart is still written at the END of that run. Requiring an mdin or an mdout
# before believing that brought #81's phantom gap back in full on exactly such a tree.

def _ascii_trajectory(path: Path) -> None:
    """Title, then coordinates straight away -- no `natom time` header, unlike a restart."""
    path.write_text("trajectory\n"
                    "   1.000   2.000   3.000   4.000   5.000   6.000   7.000   8.000\n")


def _ascii_restart(path: Path, ps: float) -> None:
    path.write_text("restart\n     1 %14.7f\n"
                    "   1.0000000   2.0000000   3.0000000   4.0000000   5.0000000\n" % ps)


def test_a_restart_beside_its_own_trajectory_is_the_run_s_output(tmp_path):
    _ascii_trajectory(tmp_path / "prod_0002.mdcrd")
    _ascii_restart(tmp_path / "prod_0002.rst", 2000.0)
    protocol = auto_discover(str(tmp_path), recursive=False)
    stage = _by_name(protocol)["prod_0002"]
    assert stage.inpcrd is not None
    assert stage.inpcrd_is_own_restart


def test_a_single_frame_crd_is_not_a_trajectory(tmp_path):
    """The bare-pair guarantee has to survive the new rule. tLEaP's `saveamberparm` is
    routinely given a `.crd` name, which the extension map types as a trajectory; its
    content says it is one frame of starting coordinates, and the content is what counts."""
    (tmp_path / "system.prmtop").write_text("%FLAG POINTERS\n")
    (tmp_path / "system.crd").write_text("start\n    1\n"
                                         "  0.0  0.0  0.0  1.0  1.0  1.0\n")
    _ascii_restart(tmp_path / "system.rst7", 0.0)
    protocol = auto_discover(str(tmp_path), recursive=False)
    stage = _by_name(protocol)["system"]
    assert stage.inpcrd is not None
    assert not stage.inpcrd_is_own_restart


def _netcdf_trajectory(path: Path, times) -> None:
    from ambermeta import netcdf_backend

    nc = netcdf_backend.nc
    ds = nc.Dataset(str(path), "w", format="NETCDF3_64BIT_OFFSET")
    ds.Conventions = "AMBER"
    ds.createDimension("frame", None)
    ds.createDimension("atom", 1)
    ds.createDimension("spatial", 3)
    ds.createVariable("time", "f4", ("frame",))[:] = times
    ds.createVariable("coordinates", "f4", ("frame", "atom", "spatial"))[:] = [
        [[0.0, 0.0, 0.0]] for _ in times]
    ds.close()


def test_a_trajectory_only_chain_reports_no_phantom_gap(tmp_path):
    """The reproduction from #87, cut to two chunks of 1000 ps.

    `prod_0002.rst` holds 2000 ps, the moment chunk 2 FINISHED. Read as its start, it sat
    one whole chunk after chunk 1's trajectory ended at 1000 ps -- "Gap detected without
    stated expectation", 1000 ps, on a chain that is continuous. With no mdout there is no
    stated begin time to fall back on either, so the honest answer is the cautious one.
    """
    from ambermeta import netcdf_backend

    if not netcdf_backend.HAS_NETCDF or netcdf_backend.NETCDF_BACKEND != "netCDF4":
        pytest.skip("needs the netCDF4 backend to build a time-bearing trajectory")
    for chunk, end_ps in ((1, 1000.0), (2, 2000.0)):
        _netcdf_trajectory(tmp_path / f"prod_{chunk:04d}.nc",
                           [end_ps - 1000.0 + 100.0 * i for i in range(1, 11)])
        _ascii_restart(tmp_path / f"prod_{chunk:04d}.rst", end_ps)

    protocol = auto_discover(str(tmp_path), recursive=False)
    second = _by_name(protocol)["prod_0002"]
    assert second.inpcrd_is_own_restart
    assert second.observed_gap_ps is None
    assert [n for n in second.continuity if not n.startswith("INFO:")] == []
    assert any("Cannot verify continuity" in n for n in second.continuity)


def test_discover_does_not_take_a_run_s_restart_for_the_starting_structure(tmp_path):
    """The same assumption, on the GUI's side. `discover_draft` looks for the starting
    structure among the groups that are NOT runs, and it too decided that by the presence
    of an mdin or an mdout -- so the first trajectory-only chunk's own output restart won
    over the topology's real coordinates, because `md_npt_prod_0001` sorts first."""
    from ambermeta.gui.api.core_bridge import discover_draft

    (tmp_path / "topology").mkdir()
    (tmp_path / "topology" / "system.prmtop").write_text("%FLAG POINTERS\n")
    (tmp_path / "topology" / "system.inpcrd").write_text(
        "start\n    1\n  0.0  0.0  0.0  1.0  1.0  1.0\n")
    for chunk in (1, 2):
        _ascii_trajectory(tmp_path / f"md_npt_prod_{chunk:04d}.mdcrd")
        _ascii_restart(tmp_path / f"md_npt_prod_{chunk:04d}.rst", 1000.0 * chunk)

    sim = discover_draft(str(tmp_path))["simulation"]
    assert sim.starting_structure == "topology/system.inpcrd"
