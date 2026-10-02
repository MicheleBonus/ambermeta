"""False positives found by running AmberMeta on a deposited corpus of 19 projects.

Each test reproduces the shape of one class of false finding, with the numbers of a real
case: frames that AMBER writes after `ntwx` steps and not at step 0, runs whose `nstlim` is
not a multiple of the write interval, and a run that starts from the starting structure
filed after an unrelated one.
"""
from types import SimpleNamespace as NS

import pytest

from ambermeta.protocol import (
    SimulationProtocol, SimulationStage, _record_tail_ps, _written_span_ps)


def _stage(name, *, mdin=None, mdout=None, mdcrd=None, inpcrd=None, **kw):
    def wrap(details):
        return NS(details=NS(**details), filename=name) if details is not None else None
    return SimulationStage(name=name, mdin=wrap(mdin), mdout=wrap(mdout), mdcrd=wrap(mdcrd),
                           inpcrd=wrap(inpcrd), **kw)


def _duration_notes(stage):
    stage.validate()
    return [n for n in stage.validation if n.startswith("Trajectory duration from mdcrd")]


def _gap_notes(stage):
    return [n for n in stage.continuity if not n.startswith("INFO:")]


# --- the written span of a record -----------------------------------------------------

@pytest.mark.parametrize("nsteps, dt, every, span", [
    (12500, 0.002, 1000, 22.0),     # 12 frames, 52..74 ps after t = 50
    (25000, 0.002, 10000, 20.0),    # 2 frames
    (5000000, 0.004, 25000, 19900.0),
    (1000, 0.002, 1000, None),      # one frame: no span
    (1000, 0.002, None, None),
])
def test_written_span(nsteps, dt, every, span):
    assert _written_span_ps(nsteps, dt, every) == (pytest.approx(span) if span else None)


@pytest.mark.parametrize("count, tail", [(62, 1.0), (63, 1.0), (50, 0.0), (None, 0.0)])
def test_record_tail_needs_a_complete_record(count, tail):
    # 62,500 steps printing every 1,000: the last print is 500 steps (1 ps) before the end
    assert _record_tail_ps(62500, 0.002, 1000, count) == pytest.approx(tail)


# --- B1: trajectory duration ------------------------------------------------------------

def test_a_trajectory_written_every_ntwx_steps_is_not_reported():
    stage = _stage("09_ntp_dens_02",
                   mdin=dict(length_steps=12500, dt=0.002, coord_freq=1000),
                   mdout=dict(nstlim=12500, dt=0.002),
                   mdcrd=dict(total_duration=22.0, avg_dt=2.0, n_frames=12))
    assert _duration_notes(stage) == []


def test_two_frames_of_a_run_that_is_not_a_multiple_of_ntwx_are_not_reported():
    stage = _stage("md_npt_ntr_01",
                   mdin=dict(length_steps=25000, dt=0.002, coord_freq=10000),
                   mdcrd=dict(total_duration=20.0, avg_dt=20.0, n_frames=2))
    assert _duration_notes(stage) == []


def test_a_short_trajectory_is_still_reported():
    stage = _stage("prod",
                   mdin=dict(length_steps=12500, dt=0.002, coord_freq=1000),
                   mdcrd=dict(total_duration=10.0, avg_dt=2.0, n_frames=6))
    notes = _duration_notes(stage)
    assert len(notes) == 1 and "(22 ps for frames written every 1000 steps)" in notes[0]


# --- B2: end of the producing run -----------------------------------------------------

def _pair(prev, current):
    proto = SimulationProtocol(stages=[prev, current])
    proto.validate(cross_stage=True)
    return current


def test_continuity_adds_the_run_after_its_last_frame():
    # 37,500 steps writing every 10,000: frames at 120, 140, 160 ps, the run ends at 175
    prev = _stage("07_ntp_initial", mdin=dict(length_steps=37500, dt=0.002, coord_freq=10000),
                  mdcrd=dict(time_start=120.0, time_end=160.0, avg_dt=20.0, n_frames=3,
                             total_duration=40.0))
    cur = _stage("08_ntp_pbceq_01", inpcrd=dict(time=175.0))
    cur = _pair(prev, cur)
    assert _gap_notes(cur) == []
    assert cur.observed_gap_ps == 0.0


def test_continuity_adds_the_run_after_its_last_printed_energy():
    stats = NS(count=62, time_start=189.5, time_end=311.5)
    prev = _stage("07_ntp_dens_02", mdin=dict(length_steps=62500, dt=0.002, energy_freq=1000),
                  mdout=dict(stats=stats, nstlim=62500, dt=0.002))
    cur = _stage("08_ntp_dens_03", inpcrd=dict(time=312.5))
    assert _gap_notes(_pair(prev, cur)) == []


def test_a_run_that_stopped_early_still_leaves_a_gap():
    # 6 of 12 frames: the run stopped, and no tail may be added
    prev = _stage("prev", mdin=dict(length_steps=12500, dt=0.002, coord_freq=1000),
                  mdcrd=dict(time_start=52.0, time_end=62.0, avg_dt=2.0, n_frames=6,
                             total_duration=10.0))
    cur = _stage("cur", inpcrd=dict(time=75.0))
    assert any("Gap detected" in n for n in _gap_notes(_pair(prev, cur)))


def test_a_gap_of_exactly_half_a_frame_interval_in_single_precision_is_accepted():
    prev = _stage("prev", mdcrd=dict(time_start=2.0, time_end=74.0, avg_dt=2.0, n_frames=37,
                                     total_duration=72.0))
    cur = _stage("cur", inpcrd=dict(time=75.000000000006608))
    assert _gap_notes(_pair(prev, cur)) == []


# --- B3: a document's stages are compared with what they declare ----------------------

def test_a_stage_reading_the_starting_structure_is_not_compared_with_its_neighbour():
    # equilibration/ sorts before minimization/: the minimisation follows a run that
    # ended at 1000 ps, but it read the starting structure
    equil = _stage("equilibration/run1/05_npt",
                   mdcrd=dict(time_start=10.0, time_end=1000.0, avg_dt=10.0, n_frames=100,
                              total_duration=990.0),
                   step_id="e5")
    minim = _stage("minimization/run1/01_min", inpcrd=dict(time=0.0), step_id="m1")
    proto = SimulationProtocol(stages=[equil, minim])
    proto.validate(cross_stage=True)
    assert _gap_notes(minim) == []
    assert any("declares no producing stage" in n for n in minim.continuity)
    assert equil.continuity == []      # the first stage of an untagged document: no note


def test_a_stage_is_compared_with_its_declared_producer_not_its_neighbour():
    a = _stage("a", mdcrd=dict(time_start=2.0, time_end=100.0, avg_dt=2.0, n_frames=50,
                               total_duration=98.0), step_id="a")
    b = _stage("b", mdcrd=dict(time_start=2.0, time_end=500.0, avg_dt=2.0, n_frames=250,
                               total_duration=498.0), step_id="b")
    c = _stage("c", inpcrd=dict(time=100.0), step_id="c", parent_id="a")
    proto = SimulationProtocol(stages=[a, b, c])
    proto.validate(cross_stage=True)
    assert _gap_notes(c) == []
    assert c.observed_gap_ps == 0.0


# --- B4: other programs' .out files ------------------------------------------------------

_AMBER_HEAD = """
          -------------------------------------------------------
          Amber 22 PMEMD                              2022
          -------------------------------------------------------
"""


def test_scheduler_logs_and_foreign_out_files_are_not_runs(tmp_path):
    from ambermeta.gui.api.files import FileType, detect_file_type
    from ambermeta.mdout_header import looks_like_mdout
    from ambermeta.protocol import smart_group_files

    (tmp_path / "prod_0001.mdin").write_text("&cntrl\n imin = 0, nstlim = 10,\n/\n")
    (tmp_path / "prod_0001.out").write_text(_AMBER_HEAD + "File Assignments:\n")
    (tmp_path / "slurm-2545610.out").write_text(_AMBER_HEAD)       # name alone decides
    (tmp_path / "nohup.out").write_text("srun: job 2545611 queued and waiting\n")
    (tmp_path / "crashed.out").write_text("")                      # empty: keeps the extension

    assert looks_like_mdout(str(tmp_path / "prod_0001.out"))
    assert not looks_like_mdout(str(tmp_path / "slurm-2545610.out"))
    assert not looks_like_mdout(str(tmp_path / "nohup.out"))
    assert looks_like_mdout(str(tmp_path / "crashed.out"))

    grouped = smart_group_files(str(tmp_path))
    assert set(grouped) == {"prod_0001", "crashed"}
    assert "mdout" in grouped["prod_0001"]
    assert detect_file_type(str(tmp_path / "nohup.out")) == FileType.OTHER
    assert detect_file_type(str(tmp_path / "prod_0001.out")) == FileType.MDOUT


# --- reading a trajectory without touching every frame ----------------------------------

class _CountingVar:
    def __init__(self, data):
        self.data = data
        self.shape = data.shape
        self.reads = 0

    def __getitem__(self, key):
        self.reads += 1
        return self.data[key]


def _fake_trajectory(n, *, dt=2.0, cut_at=None):
    import numpy as np
    times = 52.0 + dt * np.arange(n, dtype="f4")
    lengths = np.full((n, 3), 30.0)
    lengths[:, 0] += np.linspace(0.0, 1.0, n)      # the volume changes along the run
    angles = np.full((n, 3), 90.0)
    if cut_at is not None:
        times[cut_at:] = 0.0
        lengths[cut_at:] = 0.0
    return NS(variables={"time": _CountingVar(times),
                         "cell_lengths": _CountingVar(lengths),
                         "cell_angles": _CountingVar(angles)})


def test_an_intact_trajectory_is_read_from_five_frames():
    from ambermeta.legacy_extractors.mdcrd import TrajectoryMetadata, _read_intact_sample
    ds = _fake_trajectory(250000)
    md = TrajectoryMetadata(filename="prod.nc", file_format="NetCDF")
    assert _read_intact_sample(ds, md)
    assert md.n_frames == 250000
    assert md.time_start == pytest.approx(52.0)
    assert md.time_end == pytest.approx(52.0 + 2.0 * 249999, rel=1e-6)
    assert md.avg_dt == pytest.approx(2.0, rel=1e-6)
    assert md.box_type == "Orthogonal"
    assert md.volume_stats[0] == pytest.approx(27000.0)
    assert md.volume_stats[1] == pytest.approx(31.0 * 900.0)
    assert sum(v.reads for v in ds.variables.values()) == 15     # 5 frames x 3 variables


def test_a_trajectory_the_sample_cannot_vouch_for_is_read_in_full():
    from ambermeta.legacy_extractors.mdcrd import TrajectoryMetadata, _read_intact_sample
    md = TrajectoryMetadata(filename="prod.nc", file_format="NetCDF")
    assert not _read_intact_sample(_fake_trajectory(1000, cut_at=600), md)
    assert md.n_frames == 0 and md.time_start is None      # nothing written on refusal
