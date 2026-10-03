"""A run that sets its own clock is not measured against the run before it.

Under `irest = 0` (new velocities, `ntx = 1`) AMBER starts the clock at the mdin's `t`,
whatever the coordinates it read say. A production run restarted with new velocities and
`t = 0` after 5000 ps of equilibration therefore "starts" 5000 ps before its producer
ended. Where the restart's own time is readable (an ASCII restart, or a NetCDF one with a
NetCDF backend installed) that time is used and the link is clean. Where it is not -- a
NetCDF restart on a bare `pip install ambermeta`, whose NetCDF support is an optional
extra -- the start time came from the run's own clock and `validate` reported "Stage
appears to overlap previous stage by 5000 ps". Continuity there follows the recorded input
coordinates, which the recorded-input check compares.
"""
from __future__ import annotations

import shutil

import pytest

from ambermeta.cli import main
from ambermeta.legacy_extractors import inpcrd as _inpcrd
from ambermeta.protocol import auto_discover
from ambermeta.simulation import load_simulation
from ambermeta.gui.api import core_bridge
from tests.conftest import RunSpec, md_mdin, write_run_tree


def _prep_chain(root, sample_dir):
    """equil (4000 -> 5000 ps) -> prod_0001 (irest = 0, t = 0, 0 -> 2000) -> prod_0002."""
    tree = write_run_tree(root, [
        ("equil", RunSpec(mdin=md_mdin("equil", 500000), elapsed_ps=1000.0,
                          begin_ps=4000.0, inpcrd="start.rst")),
        ("prod_0001", RunSpec(mdin=md_mdin("prod", 1000000, irest=0, t=0.0),
                              elapsed_ps=2000.0, begin_ps=0.0, irest=0,
                              inpcrd="equil.restrt")),
        ("prod_0002", RunSpec(mdin=md_mdin("prod", 1000000), elapsed_ps=2000.0,
                              begin_ps=2000.0, inpcrd="prod_0001.restrt")),
    ])
    # The restart prod_0001 read is a NetCDF file, as pmemd writes it.
    shutil.copy(sample_dir / "ntp_prod_0000.rst", tree / "equil.restrt")
    return tree


@pytest.fixture
def no_netcdf_backend(monkeypatch):
    """The restart reader as it is on an install without netCDF4 or SciPy."""
    monkeypatch.setattr(_inpcrd, "HAS_NETCDF", False)


def _stage(protocol, name):
    return next(s for s in protocol.stages if s.name == name)


def test_no_false_overlap_without_a_netcdf_backend(tmp_path, sample_md_data_dir,
                                                  no_netcdf_backend, capsys):
    tree = _prep_chain(tmp_path, sample_md_data_dir)
    manifest = tree / "manifest.yaml"
    assert main(["discover", str(tree), "--write", str(manifest)]) == 0
    capsys.readouterr()

    sim = load_simulation(str(manifest))
    report = core_bridge.validate_simulation(sim, {"strict_validation": True}, str(tree))
    prod = next(s for s in report["stage_issues"] if s["name"] == "prod_0001")
    assert prod["continuity"] == []
    assert any("set its own clock (irest = 0)" in note and
               "follows the recorded input coordinates" in note for note in prod["info"])
    assert not [s for s in report["suggestions"] if s["kind"] == "continuity_gap"]

    assert main(["validate", "--manifest", str(manifest), "--strict"]) == 0
    assert "overlap" not in capsys.readouterr().out


def test_the_run_after_it_is_still_measured(tmp_path, sample_md_data_dir, no_netcdf_backend):
    tree = _prep_chain(tmp_path, sample_md_data_dir)
    manifest = tree / "manifest.yaml"
    assert main(["discover", str(tree), "--write", str(manifest)]) == 0
    sim = load_simulation(str(manifest))
    flat = core_bridge._flatten_simulation(sim)
    protocol = core_bridge.build_protocol(flat, {"strict_validation": True}, str(tree))
    assert _stage(protocol, "prod_0001").observed_gap_ps is None
    assert _stage(protocol, "prod_0002").observed_gap_ps == 0.0


def test_a_readable_restart_time_is_still_used(tmp_path, sample_md_data_dir):
    """With the restart's time readable the link is measured as before: the coordinate
    file prod_0001 read was written when equil ended."""
    tree = write_run_tree(tmp_path, [
        ("equil", RunSpec(mdin=md_mdin("equil", 500000), elapsed_ps=1000.0,
                          begin_ps=4000.0, inpcrd="start.rst")),
        ("prod_0001", RunSpec(mdin=md_mdin("prod", 1000000, irest=0, t=0.0),
                              elapsed_ps=2000.0, begin_ps=0.0, irest=0,
                              inpcrd="equil.restrt")),
    ])
    manifest = tree / "manifest.yaml"
    assert main(["discover", str(tree), "--write", str(manifest)]) == 0
    sim = load_simulation(str(manifest))
    protocol = core_bridge.build_protocol(core_bridge._flatten_simulation(sim),
                                          {"strict_validation": True}, str(tree))
    assert _stage(protocol, "prod_0001").observed_gap_ps == 0.0


def test_the_scan_path_reports_no_overlap_either(tmp_path, sample_md_data_dir,
                                                 no_netcdf_backend):
    tree = _prep_chain(tmp_path, sample_md_data_dir)
    protocol = auto_discover(str(tree), recursive=True)
    prod = _stage(protocol, "prod_0001")
    assert not [n for n in prod.continuity if not n.startswith("INFO")]
    assert any("set its own clock" in n for n in prod.continuity)


@pytest.mark.parametrize("expected,verdict", [
    (-5000.0, "is within expected window"), (10.0, "is shorter than expected")])
def test_a_declared_gap_is_still_checked_on_a_run_that_set_its_own_clock(
        tmp_path, sample_md_data_dir, no_netcdf_backend, expected, verdict):
    """PR #93 review, M2. A step that declares the gap it expects has said what its `t`
    should be; the own-clock shortcut must not skip that check silently."""
    from ambermeta.simulation import iter_steps

    tree = _prep_chain(tmp_path, sample_md_data_dir)
    manifest = tree / "manifest.yaml"
    assert main(["discover", str(tree), "--write", str(manifest)]) == 0
    sim = load_simulation(str(manifest))
    for _, step in iter_steps(sim):
        if step.name == "prod_0001":
            step.expected_gap_ps, step.gap_tolerance_ps = expected, 1.0
    protocol = core_bridge.build_protocol(core_bridge._flatten_simulation(sim),
                                          {"strict_validation": True}, str(tree))
    prod = _stage(protocol, "prod_0001")
    assert prod.observed_gap_ps == -5000.0
    assert any(verdict in note for note in prod.continuity)
    assert not any("set its own clock" in note for note in prod.continuity)
