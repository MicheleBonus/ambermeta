"""How a run says it finished, and which printed blocks are frames.

Two failures found on the same 1097-run campaign, both in the tail of `parse_mdout`:

* every minimisation was reported as crashed, because sander does not print pmemd's
  "Final Performance Info" banner and nothing else was recognised as a completion mark;
* every frame after the first interim `ntave` averages block was silently dropped,
  because the summary-block skip was a latch rather than a count.

Neither had a test. Both changed what a run's own metadata says about itself, which is
what continuity is then measured from.
"""
from __future__ import annotations

from ambermeta.legacy_extractors.mdout import parse_mdout

_CONTROL = """\
          -------------------------------------------------------
          Amber 18 SANDER                              2018
          -------------------------------------------------------

 Here is the input file:

--------------------------------------------------------------------------------
   2.  CONTROL  DATA  FOR  THE  RUN
--------------------------------------------------------------------------------

     ntx     =       5, irest   =       1, ntrx    =       1
     nstlim  =    500000, nscm    =      1000, dt      =   0.00400
     ntt     =       3, temp0   = 300.00000, ntc     =       2
"""


def _frame(nstep: int, time_ps: float, temp: float = 300.0) -> str:
    """One printed thermodynamic block, in the layout AMBER actually writes."""
    return (
        f" NSTEP = {nstep:8d}   TIME(PS) = {time_ps:11.3f}  TEMP(K) = {temp:8.2f}  PRESS ="
        "     0.0\n"
        " Etot   =   -163669.3255  EKtot   =     30843.5645  EPtot      =   -194512.8899\n"
        " BOND   =      1351.5067  ANGLE   =      3168.2108  DIHED      =      1903.9531\n"
        " EKCMT  =     13505.4123  VIRIAL  =     11765.2155  VOLUME     =    495151.8058\n"
        "                                                    Density    =         1.0348\n"
        " ------------------------------------------------------------------------------\n"
    )


def _averages_pair(nstep: int, time_ps: float) -> str:
    """The `A V E R A G E S` / `R M S` pair. AMBER prints one block under each banner."""
    return (
        "      A V E R A G E S   O V E R     200 S T E P S\n\n\n"
        + _frame(nstep, time_ps)
        + "\n\n      R M S  F L U C T U A T I O N S\n\n\n"
        + _frame(nstep, time_ps, temp=1.25)
    )


_SANDER_TAIL = """\
--------------------------------------------------------------------------------
   5.  TIMINGS
--------------------------------------------------------------------------------

|  NonSetup CPU Time in Major Routines:
|
|     Routine           Sec        %
|     ------------------------------
|     Nonbond        4800.12   92.78
|     Other           373.89    7.22
|     ------------------------------
| Total time              5174.01 (100.0% of ALL  )

| Highest rstack allocated:      44000
| wallclock() was called  254011 times

|  Run   done at   Mon Jan  1 12:00:00 2024
"""

_PMEMD_TAIL = """\
--------------------------------------------------------------------------------
   5.  TIMINGS
--------------------------------------------------------------------------------

|  Final Performance Info:
|         ns/day =     232.22   seconds/ns =     372.05

|  Total wall time:        7445    seconds     2.07 hours
"""


def _write(tmp_path, body: str):
    path = tmp_path / "run.mdout"
    path.write_text(body)
    return parse_mdout(str(path))


# -- how a run says it finished -------------------------------------------------

def test_a_sander_run_that_finished_is_not_reported_as_crashed(tmp_path):
    """sander never prints "Final Performance Info" -- that banner is pmemd's.

    On the campaign this was found on, the only five mdouts of 1091 flagged as not
    finished were the five minimisations, every one of them an Amber 18 sander.MPI run
    that had ended cleanly with a full TIMINGS breakdown.
    """
    md = _write(tmp_path, _CONTROL + _frame(500000, 2000.0) + _SANDER_TAIL)

    assert md.finished_properly is True


def test_sanders_total_time_is_read_as_the_wall_clock(tmp_path):
    md = _write(tmp_path, _CONTROL + _frame(500000, 2000.0) + _SANDER_TAIL)

    assert md.wall_time_seconds == 5174.01


def test_a_run_that_stopped_mid_flight_is_still_reported_as_unfinished(tmp_path):
    """The guard against the fix above being a blanket `finished_properly = True`."""
    md = _write(tmp_path, _CONTROL + _frame(25000, 1020.0) + _frame(50000, 1120.0))

    assert md.finished_properly is False
    assert md.wall_time_seconds == 0.0


def test_a_pmemd_run_is_unaffected(tmp_path):
    """pmemd prints `Total wall time:`, never sander's `Total time ... of ALL` line, so
    the two cannot collide -- the wall clock here comes from pmemd's own parsing."""
    md = _write(tmp_path, _CONTROL + _frame(500000, 2000.0) + _PMEMD_TAIL)

    assert md.finished_properly is True
    assert md.wall_time_seconds == 7445.0


# -- which printed blocks are frames --------------------------------------------

def test_interim_averages_do_not_truncate_the_run(tmp_path):
    """`ntave > 0` makes AMBER print an averages pair mid-run and then carry on.

    The skip used to be a latch, so the first interim pair ended frame collection for
    the rest of the file: the run's reported end time froze at the point of the first
    averages block, under-reporting the run's length and manufacturing a gap against
    whatever came next in the chain.
    """
    body = (
        _CONTROL
        + _frame(25000, 1000.0)
        + _frame(50000, 1100.0)
        + _averages_pair(50000, 1100.0)      # interim, ntave
        + _frame(75000, 1200.0)
        + _frame(100000, 1300.0)
        + _averages_pair(100000, 1300.0)     # end of run
        + _PMEMD_TAIL
    )

    md = _write(tmp_path, body)

    assert md.stats.count == 4
    assert md.stats.time_start == 1000.0
    assert md.stats.time_end == 1300.0


def test_the_closing_averages_pair_is_still_not_counted(tmp_path):
    """The reason the skip exists at all: the final pair is a summary, not two frames."""
    body = (
        _CONTROL
        + _frame(25000, 1000.0)
        + _frame(50000, 1100.0)
        + _averages_pair(50000, 1100.0)
        + _PMEMD_TAIL
    )

    md = _write(tmp_path, body)

    assert md.stats.count == 2
    assert md.stats.time_end == 1100.0


def test_a_banner_with_no_block_after_it_cannot_eat_a_later_frame(tmp_path):
    """A run killed between the banner and the block it announces leaves a skip owing.

    The timings banner clears it, so the count cannot run into whatever is parsed next.
    """
    body = (
        _CONTROL
        + _frame(25000, 1000.0)
        + "      A V E R A G E S   O V E R     200 S T E P S\n\n"
        + _PMEMD_TAIL
    )

    md = _write(tmp_path, body)

    assert md.stats.count == 1
    assert md.finished_properly is True
