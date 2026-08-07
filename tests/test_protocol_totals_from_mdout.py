# tests/test_protocol_totals_from_mdout.py
"""Totals are what ran, not what was queued.

Pins the arithmetic of `SimulationProtocol._sum_stages` after it stopped reading the
mdin. What is deliberately NOT asserted here: which steps carry the `queued` marker (that
is test_protocol_queued.py) and anything about lineages.

The formula is `stats.time_end - mdout_header.begin_time_ps`. The two obvious wrong
answers both have a test below, because both produce plausible-looking numbers:
summing `time_end` treats an absolute clock reading as a duration, and
`time_end - time_start` is short by one ntpr interval per run.
"""
from __future__ import annotations

from ambermeta.protocol import auto_discover, _elapsed_ps


# --- the core arithmetic ---

def test_a_queued_run_contributes_no_time(sys021_tree):
    """Five chunks were set up and never executed. The old rule read nstlim x dt off the
    mdin and counted all five, which on the real campaign was 25 ns of simulation that
    never happened, reported with ok: true."""
    totals = auto_discover(str(sys021_tree), recursive=True).totals()
    # 5 equil x 5000 + (3 + 2 + 2 + 2 + 2) prod x 5000
    assert totals["time_ps"] == 80000.0


def test_the_total_is_not_the_sum_of_absolute_end_times(sys021_tree):
    """`stats.time_end` is an absolute AMBER clock reading. Summing it directly gave
    304,600 ps against a true 100,000 ps on the back-compat fixture -- a worse error than
    the one being fixed. This asserts the number is the elapsed sum, not the absolute one."""
    totals = auto_discover(str(sys021_tree), recursive=True).totals()
    absolute_sum = 5 * 5000.0 + sum(
        5000.0 * i for reps in ((3,), (2,), (2,), (2,), (2,)) for ran in reps
        for i in range(2, ran + 2))
    assert totals["time_ps"] != absolute_sum
    assert totals["time_ps"] == 80000.0


def test_steps_are_derived_from_elapsed_time_and_dt(sys021_tree):
    """The final NSTEP is not retrievable -- ThermoStats parses the key and discards it,
    and MdoutMetadata.nstlim is the control-data intent, identical to the mdin's. So
    steps-that-ran is elapsed/dt and there is no other source."""
    totals = auto_discover(str(sys021_tree), recursive=True).totals()
    assert totals["steps"] == 80000.0 / 0.002


# --- two ways to contribute zero, and why they must not be confused ---
#
# A real minimisation mdout and a present-but-garbage mdout land in the exact same
# `stats.count == 0` bucket. A minimisation never populates ThermoStats at all (it prints
# `NSTEP ENERGY RMS GMAX`, never `TIME(PS)`). A garbage file matches none of
# `parse_mdout`'s patterns, and that function raises nothing, so it too comes back with
# every field -- `stats` included -- left at its class default. `_elapsed_ps` returns
# `None` for both, and neither test below can tell them apart from `_elapsed_ps`'s return
# value alone: swapping the order of the `run_type == "Minimization"` check and the
# `stats.count == 0` check inside `_elapsed_ps` changes NEITHER fixture's result, because a
# minimisation's own `stats.count` is also 0. The only way to pin the order is to prove
# `.stats` is never even read for a minimisation, which is what the poisoned stats object
# in the first test does.

_MIN_MDIN = "minimise\n &cntrl\n  imin = 1, maxcyc = 1000, ntb = 1,\n /\n"

# `imin = 1` is what routes `parse_mdout` to `run_type = "Minimization"`. The results table
# header is `NSTEP ENERGY RMS GMAX`, not `NSTEP = ... TIME(PS) = ...`, so `add_frame` is
# never called for any row in it and `stats.count` stays 0 -- this is the true shape of a
# minimisation mdout, not a stand-in for one.
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

_STAGE_MDIN = ("production\n &cntrl\n  imin = 0, irest = 1, nstlim = 2500000,\n"
               "  dt = 0.002, ntb = 2,\n /\n")

# No CONTROL DATA banner, no `imin` line, no NSTEP frames of either shape.
# `parse_mdout` has no exception handler around its line scan and none of this matches any
# pattern it looks for, so it returns a default-valued `MdoutMetadata` (`run_type = "MD"`,
# `stats.count == 0`) rather than raising -- which is exactly what makes this case
# different from `stage.mdout is None` (queued, covered above) and worth its own test.
_GARBAGE_MDOUT = (
    "this file is not a real amber mdout\n"
    "it has no CONTROL DATA banner, no imin line, and no NSTEP frames\n"
    "just enough bytes to exist as a PRESENT file that will not parse into anything\n"
)


def test_a_minimisation_is_recognised_by_run_type_before_stats_are_ever_read(tmp_path):
    """A minimisation's `stats.count` is 0, same as a malformed mdout's (see the next
    test) -- so if `_elapsed_ps` told the two apart by `stats.count == 0` alone it could
    not. The minimisation check has to run first and return before `.stats` is read at
    all. Swapping the two `if`s in `_elapsed_ps` would not change this fixture's result
    (still `None` either way, since a real minimisation's `stats.count` is also 0) -- so a
    plain `totals["time_ps"] == 0.0` assertion would pass under either order and would not
    have caught the bug the next task is about to introduce. Only proving `.stats` is
    never touched pins the order."""
    (tmp_path / "min.mdin").write_text(_MIN_MDIN, encoding="utf-8")
    (tmp_path / "min.mdout").write_text(_MIN_MDOUT, encoding="utf-8")
    protocol = auto_discover(str(tmp_path), recursive=True)
    stage, = protocol.stages

    # Grounds the scenario: this really is what a minimisation parses to, and it really
    # does land in the same "empty stats" bucket a malformed file does.
    details = stage.mdout.details
    assert details.run_type == "Minimization"
    assert details.stats.count == 0
    assert _elapsed_ps(stage) is None
    assert protocol.totals()["time_ps"] == 0.0

    class _RaisesIfRead:
        """Stands in for `stats`. Reading `.count` off it means whatever called
        `_elapsed_ps` did not return on the `run_type == "Minimization"` check first --
        exactly the reordering this test exists to catch."""
        @property
        def count(self):
            raise AssertionError(
                "stats.count was read for a Minimization stage -- run_type must be "
                "checked, and must return, before .stats is ever touched"
            )

    details.stats = _RaisesIfRead()
    assert _elapsed_ps(stage) is None


def test_a_present_but_malformed_mdout_contributes_nothing(tmp_path):
    """`parse_mdout` catches nothing and returns a default-valued `MdoutMetadata` rather
    than raising, so a garbage-but-present mdout is NOT `stage.mdout is None` -- that is
    `queued` (`test_a_queued_run_contributes_no_time`, above), a different situation with a
    different cause. This one has to be recognised by `stats.count == 0` with an mdout
    that is genuinely present: its `run_type` stays at the class default `"MD"`, so a
    caller that (wrongly) trusted `run_type == "Minimization"` alone to mean "nothing to
    report" would miss this case entirely."""
    (tmp_path / "garbage.mdin").write_text(_STAGE_MDIN, encoding="utf-8")
    (tmp_path / "garbage.mdout").write_text(_GARBAGE_MDOUT, encoding="utf-8")
    protocol = auto_discover(str(tmp_path), recursive=True)
    stage, = protocol.stages

    assert stage.mdout is not None
    assert stage.mdout.details is not None
    assert stage.mdout.details.run_type != "Minimization"
    assert stage.mdout.details.stats.count == 0
    assert _elapsed_ps(stage) is None
    assert protocol.totals()["time_ps"] == 0.0
