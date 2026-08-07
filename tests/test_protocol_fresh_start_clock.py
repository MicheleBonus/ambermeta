# tests/test_protocol_fresh_start_clock.py
"""A fresh run sets its own clock, and the header's begin time is not it.

The Critical defect this file exists to keep fixed, measured on the real campaign at
`equil/01/18_ntp_equi`:

    mdin :  ntx = 1,  irest = 0,  t = 1800.0,  nstlim = 1600000,  dt = 0.002
    mdout:  t       =1800.00000, dt      =   0.00200        (CONTROL DATA)
            begin time read from input coords =     0.000 ps
            NSTEP =        0   TIME(PS) =    1800.000       <- first frame
            NSTEP =  1600000   TIME(PS) =    5000.000       <- last frame

Under `irest = 0` AMBER does not take the clock from the coordinate file. It initialises
from the mdin's `t` and reads no time at all from the coordinates, so it prints
`begin time read from input coords = 0.000` -- an honest report that it read nothing --
while the trajectory runs from 1800 to 5000. `time_end - begin_time_ps` therefore reports
5000 ps of dynamics for a run that did 3200. Three independent sources say 3200:
`nstlim x dt`, the frame span `5000 - 1800`, and 160 intervals of 20 ps.

Five runs, one per replica, 1800 ps each. The campaign published 5,039,000 ps; the truth is
5,030,000. `main` got these runs right, so the branch introduced this.

Also pins the second trap, which is latent until the first is fixed: the fencepost
correction (`time_end - time_start + interval`) OVERSHOOTS by exactly one interval on any
run that prints an `NSTEP = 0` record, because that record is the origin itself and there
is no missing leading interval to add back. Measured 3220 against a true 3200 on these
runs. `_origin_time_ps` never routes an `irest = 0` run through the fencepost, and
`test_the_fencepost_is_not_applied_to_a_run_that_printed_step_zero` is what says so.
"""
from __future__ import annotations

from ambermeta.mdout_header import read_mdout_header
from ambermeta.protocol import (
    ORIGIN_CONTROL_T,
    ORIGIN_FENCEPOST,
    ORIGIN_FIRST_FRAME,
    ORIGIN_HEADER,
    _elapsed_ps,
    _elapsed_ps_and_source,
    _fenced_elapsed_ps,
    auto_discover,
)


def test_a_fresh_run_is_measured_from_its_own_clock_not_the_header_zero(fresh_start_tree):
    """3200, not 5000. The whole defect in one assertion."""
    protocol = auto_discover(str(fresh_start_tree), recursive=True)
    by_name = {s.name: s for s in protocol.stages}
    equi = by_name["equi"]

    # Grounds the scenario: this really is the shape the real mdout has. The header states
    # a begin time, it is readable, and it is a lie about the clock origin.
    assert equi.mdout_header.irest == 0
    assert equi.mdout_header.begin_time_ps == 0.0
    assert equi.mdout_header.control_t_ps == 1800.0
    assert equi.mdout.details.stats.time_end == 5000.0

    elapsed, source = _elapsed_ps_and_source(equi)
    assert elapsed == 3200.0
    assert source == ORIGIN_CONTROL_T
    # The number the branch published for this shape, named so a future edit that
    # reintroduces it fails here rather than in a campaign total nobody recomputes.
    assert elapsed != 5000.0


def test_a_continuation_still_reads_its_begin_time_from_the_header(fresh_start_tree):
    """The other half of the same tree, and the reason `irest` is the discriminator rather
    than "always prefer `t`": under `irest = 1` AMBER IGNORES `t` (the repo's own
    back-compat fixtures say `t = 1000.0` for a run that began at 920.0, and the real
    campaign's `nvt_prod_0201` says `t = 5000.0` for a run that began at 1005019.992).
    Preferring the control-data `t` unconditionally would wreck every continuation in the
    repo while fixing the five fresh runs."""
    protocol = auto_discover(str(fresh_start_tree), recursive=True)
    by_name = {s.name: s for s in protocol.stages}
    prod = by_name["prod_0001"]

    assert prod.mdout_header.irest == 1
    assert prod.mdout_header.begin_time_ps == 5000.0
    elapsed, source = _elapsed_ps_and_source(prod)
    assert elapsed == 5000.0
    assert source == ORIGIN_HEADER


def test_the_fencepost_is_not_applied_to_a_run_that_printed_step_zero(fresh_start_tree):
    """The trap that goes live the moment the fencepost is preferred over the header.

    `_fenced_elapsed_ps` assumes frames print at `origin + iv, origin + 2iv, ...`, so it
    adds one interval back to `time_end - time_start`. An `irest = 0` run prints its
    starting energies at `NSTEP = 0`, so its first printed frame IS the origin and that
    added interval is pure invention: 3220 against a true 3200 here, and the same 20 ps
    per run on the real campaign. Asserted directly against the fencepost function rather
    than by inspection, so this stays true if the routing ever changes.
    """
    protocol = auto_discover(str(fresh_start_tree), recursive=True)
    equi = {s.name: s for s in protocol.stages}["equi"]
    stats = equi.mdout.details.stats

    assert _fenced_elapsed_ps(stats) == 3220.0     # what the fencepost would say
    assert _elapsed_ps(equi) == 3200.0             # what the run actually did


def test_a_fresh_run_whose_t_overflowed_falls_back_to_its_first_frame(tmp_path):
    """`t` shares AMBER's overflowing fixed-width field with the begin time -- the repo's
    back-compat fixtures print `t       =**********` from 21000 ps on -- so an `irest = 0`
    run whose clock was set past ~1e6 states no readable `t` either.

    The `NSTEP = 0` record carries the same number, un-fenced, and that is the route taken:
    NOT the fencepost, which would add one interval, and NOT the header's 0.000, which
    would report the whole absolute clock as elapsed time. Written by hand rather than
    through `RunSpec` because the fixture writes a real `t` by construction; blanking it is
    the entire point here.
    """
    from tests.conftest import RunSpec, _PROD_MDIN, _mdout_text

    spec = RunSpec(mdin=_PROD_MDIN, elapsed_ps=3200.0, begin_ps=1800000.0, irest=0,
                   frames=160)
    text = _mdout_text(spec).replace("t       = 1800000.00000", "t       =**********")
    assert "**********" in text, "the overflow substitution must actually have landed"
    (tmp_path / "equi.mdin").write_text(_PROD_MDIN, encoding="utf-8")
    (tmp_path / "equi.mdout").write_text(text, encoding="utf-8")

    header = read_mdout_header(str(tmp_path / "equi.mdout"))
    assert header.irest == 0 and header.control_t_ps is None

    protocol = auto_discover(str(tmp_path), recursive=True)
    stage, = protocol.stages
    elapsed, source = _elapsed_ps_and_source(stage)
    assert source == ORIGIN_FIRST_FRAME
    assert elapsed == 3200.0
    assert source != ORIGIN_FENCEPOST      # 3220 -- one interval of invention
    # And it says so in the artifact, in its own words rather than borrowing the
    # fencepost's "overflowed AMBER's fixed-width field" sentence: nothing here was derived
    # from spacing, and a reader sent looking for a `**********` begin time would not find
    # one (the begin time reads a perfectly ordinary 0.000).
    stage.validate()
    note, = [n for n in stage.validation if "first printed frame" in n]
    assert "irest = 0" in note


def test_the_campaign_total_is_what_the_machine_ran(sys021_tree):
    """The scaled equivalent of the real campaign's 5,030,000 ps -- the figure the
    specification predicted before any of this was implemented.

    5 x 3200 (equil, fresh clock at 1800) + 11 x 5000 (production chunks) = 71,000. Under
    the header rule the five equil runs report 5000 each and the total is 80,000: the
    scaled equivalent of the 5,039,000 the branch published.
    """
    totals = auto_discover(str(sys021_tree), recursive=True).totals()
    assert totals["time_ps"] == 71000.0
    assert totals["time_ps"] != 80000.0


def test_a_fresh_run_is_not_reported_as_overlapping_what_precedes_it(fresh_start_tree):
    """Continuity reads the clock origin through the SAME `_origin_time_ps`.

    Before that, `_check_stage_pair` had its own read of `begin_time_ps`, so fixing only
    the totals would leave continuity comparing a producer ending at 5000 against a
    consumer "starting" at 0.000 -- a phantom 5000 ps overlap reported on a healthy run.
    The stage's own inpcrd normally answers this first, so the header route is reached by
    removing it, which is also the real situation on a bare install (a NetCDF restart
    parses to `time=None` without the optional `netCDF4` extra).
    """
    protocol = auto_discover(str(fresh_start_tree), recursive=True)
    by_name = {s.name: s for s in protocol.stages}
    equi, prod = by_name["equi"], by_name["prod_0001"]
    prod.inpcrd = None

    protocol._check_stage_pair(equi, prod)
    # equi ends at 5000 and prod's clock starts at 5000: no gap, no overlap.
    assert prod.observed_gap_ps == 0.0
    assert not [n for n in prod.continuity if "overlap" in n]
