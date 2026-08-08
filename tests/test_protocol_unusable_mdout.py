# tests/test_protocol_unusable_mdout.py
"""The specification's fourth run state: "Ran, mdout unusable -> contributes nothing, plus
a note." No task before this one wrote that note -- `_elapsed_ps`'s own docstring defers it
("...for the note it writes, but not here") and nothing downstream ever picked it up, so a
truncated or corrupt mdout silently contributed a zero indistinguishable from a stage that
never ran at all. That is the exact silence `status="queued"` (test_protocol_queued.py)
removes for the *other* zero-contributing state; this file is the equivalent guard for the
one the brief for this task did not cover.

Pins `SimulationStage._validate_elapsed_time`, the one caller of `_elapsed_ps` that turns
its four `None` cases into a report rather than a silent number. What is deliberately NOT
asserted here: the arithmetic (test_protocol_totals_from_mdout.py, which already owns the
`_MIN_MDIN`/`_MIN_MDOUT`/`_GARBAGE_MDOUT` fixtures this file's constants mirror) and the
`queued` marker (test_protocol_queued.py) -- this file is only about the note, and only
about the two `_elapsed_ps` `None` causes ("unreadable", "no stated begin") that are not
already spoken for by one of those two markers.
"""
from __future__ import annotations

from ambermeta.protocol import auto_discover

_STAGE_MDIN = ("production\n &cntrl\n  imin = 0, irest = 1, nstlim = 2500000,\n"
               "  dt = 0.002, ntb = 2,\n /\n")

# Present, non-empty, and matches none of `parse_mdout`'s patterns: no CONTROL DATA banner,
# no imin line, no NSTEP frames. `stats.count` stays at its class default of 0 -- the
# "unreadable" branch of `_elapsed_ps`'s docstring.
_GARBAGE_MDOUT = (
    "this file is not a real amber mdout\n"
    "it has no CONTROL DATA banner, no imin line, and no NSTEP frames\n"
    "just enough bytes to exist as a PRESENT file that will not parse into anything\n"
)

_MIN_MDIN = "minimise\n &cntrl\n  imin = 1, maxcyc = 1000, ntb = 1,\n /\n"

# The true shape of a minimisation mdout: `NSTEP ENERGY RMS GMAX`, never `TIME(PS)`, so
# `stats.count` stays 0 for a completely different, entirely legitimate reason.
_MIN_MDOUT = (
    "   2.  CONTROL  DATA  FOR  THE  RUN\n"
    "     imin    = 1, maxcyc  = 1000, ntb = 1,\n"
    " begin time read from input coords =   920.000 ps\n\n"
    "   4.  RESULTS\n\n"
    "   NSTEP       ENERGY          RMS            GMAX         NAME    NUMBER\n"
    "      1     -1.23450E+04     5.4321E-01     2.1000E+00     C1      123\n\n"
    "      BOND    =        1.234  ANGLE   =        2.345  DIHED      =        3.456\n"
    "      VDWAALS =        4.567  EEL     =        5.678  HBOND      =        0.000\n\n"
    "      5.  FINAL RESULTS\n"
)

# Real CONTROL DATA, a real NSTEP/TIME(PS) frame -- `stats.count` is 1, NOT 0 -- but no
# "begin time read from input coords" line anywhere, the `irest=0` situation
# `_elapsed_ps`'s docstring calls "no stated begin". Proves the note also fires on the
# `_elapsed_ps` branch that is not `stats.count == 0`, which a check written against only
# the garbage-mdout fixture below could miss.
_NO_BEGIN_MDOUT = (
    "   2.  CONTROL  DATA  FOR  THE  RUN\n"
    "     imin    = 0, nstlim  = 2500000, dt = 0.00200\n\n"
    "   4.  RESULTS\n\n"
    " NSTEP =     5000   TIME(PS) =    1000.000  TEMP(K) =   300.00  PRESS =     0.0\n"
    " Etot   =    -1000.0000  EKtot   =      200.0000  EPtot      =    -1200.0000\n"
    "  ----------------------------------------------------------------\n"
    "\n      5.  TIMINGS\n"
)


def _elapsed_notes(stage):
    return [m for m in stage.validation if "could not be measured" in m]


def test_a_present_but_malformed_mdout_gets_a_note_naming_the_stage(tmp_path):
    (tmp_path / "garbage.mdin").write_text(_STAGE_MDIN, encoding="utf-8")
    (tmp_path / "garbage.mdout").write_text(_GARBAGE_MDOUT, encoding="utf-8")
    protocol = auto_discover(str(tmp_path), recursive=True)
    stage, = protocol.stages

    assert stage.mdout.details.stats.count == 0
    assert stage.status is None      # not queued: an mdout was present, just unusable
    assert _elapsed_notes(stage) == [
        "INFO: Elapsed time for garbage could not be measured (mdout present but unusable)."
    ]


def test_a_run_with_no_stated_begin_time_also_gets_the_note(tmp_path):
    (tmp_path / "prod.mdin").write_text(_STAGE_MDIN, encoding="utf-8")
    (tmp_path / "prod.mdout").write_text(_NO_BEGIN_MDOUT, encoding="utf-8")
    protocol = auto_discover(str(tmp_path), recursive=True)
    stage, = protocol.stages

    assert stage.mdout.details.stats.count == 1   # really did run, unlike the case above
    assert _elapsed_notes(stage) == [
        "INFO: Elapsed time for prod could not be measured (mdout present but unusable)."
    ]


def test_a_minimisation_gets_no_note_despite_never_having_an_elapsed_time(tmp_path):
    """The state table's third row, not its fourth: minimisation legitimately reports no
    elapsed time, and always has -- the old nstlim x dt rule contributed 0 for it too,
    because a min mdin carries no nstlim/dt of its own. Noting it here would send a user to
    go investigate a stage that has nothing wrong with it."""
    (tmp_path / "min.mdin").write_text(_MIN_MDIN, encoding="utf-8")
    (tmp_path / "min.mdout").write_text(_MIN_MDOUT, encoding="utf-8")
    protocol = auto_discover(str(tmp_path), recursive=True)
    stage, = protocol.stages

    assert stage.mdout.details.run_type == "Minimization"
    assert stage.mdout.details.stats.count == 0     # same empty bucket as the garbage case
    assert _elapsed_notes(stage) == []


def test_a_queued_run_gets_no_note_because_its_own_status_already_says_so(sys021_tree):
    """The state table's second row, not its fourth: queued has `status="queued"` (this
    task's main change) to say it, and stacking this note on top would say the same thing
    twice in two different vocabularies."""
    protocol = auto_discover(str(sys021_tree), recursive=True)
    queued = [s for s in protocol.stages if s.status == "queued"]
    assert len(queued) == 5
    assert all(_elapsed_notes(s) == [] for s in queued)


def test_a_run_that_produced_output_gets_no_note(sys021_tree):
    """The common case: a real mdout with real elapsed time gets nothing extra. Guards
    against a condition broad enough to fire on every stage regardless of whether anything
    was actually wrong."""
    protocol = auto_discover(str(sys021_tree), recursive=True)
    ran = [s for s in protocol.stages if s.name == "prod/01/nvt_prod_0001"]
    assert ran and _elapsed_notes(ran[0]) == []
