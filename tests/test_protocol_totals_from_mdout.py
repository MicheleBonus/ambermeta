# tests/test_protocol_totals_from_mdout.py
"""Totals are what ran, not what was queued.

Pins the arithmetic of `SimulationProtocol._sum_stages` after it stopped reading the
mdin. What is deliberately NOT asserted here: which steps carry the `queued` marker (that
is test_protocol_queued.py) and anything about lineages.

The formula is `stats.time_end - <the run's clock origin>`, where the origin comes from
`_origin_time_ps` -- the header's begin time on a continuation, the CONTROL DATA `t` on a
fresh `irest=0` run whose header begin time is a meaningless 0.000. THREE wrong answers
have a test below, because all three produce plausible-looking numbers:

* summing `time_end` treats an absolute clock reading as a duration;
* `time_end - time_start` is short by one ntpr interval per continuation run;
* `nstlim x dt` reports what the run SAID it would do, not what it did -- see
  `test_a_truncated_run_contributes_what_it_ran_not_what_it_declared`, which is the first
  test in this repo able to tell those two apart at all (`conftest._mdout_text` wrote
  `nstlim = elapsed_ps / dt` into every fixture until `RunSpec.stated_ps` existed).
"""
from __future__ import annotations

import csv

from ambermeta.protocol import auto_discover, _elapsed_ps, write_stats_csv


# --- the core arithmetic ---

# 5 equil x 3200 (a fresh irest=0 run: clock origin 1800, ends at 5000) + 11 prod chunks
# x 5000. The scaled equivalent of the real campaign's 5,030,000 ps.
_SYS021_TIME_PS = 5 * 3200.0 + 11 * 5000.0


def test_a_queued_run_contributes_no_time(sys021_tree):
    """Five chunks were set up and never executed. The old rule read nstlim x dt off the
    mdin and counted all five, which on the real campaign was 25 ns of simulation that
    never happened, reported with ok: true."""
    totals = auto_discover(str(sys021_tree), recursive=True).totals()
    assert totals["time_ps"] == _SYS021_TIME_PS


def test_the_total_is_not_the_sum_of_absolute_end_times(sys021_tree):
    """`stats.time_end` is an absolute AMBER clock reading. Summing it directly gave
    304,600 ps against a true 100,000 ps on the back-compat fixture -- a worse error than
    the one being fixed. This asserts the number is the elapsed sum, not the absolute one."""
    totals = auto_discover(str(sys021_tree), recursive=True).totals()
    absolute_sum = 5 * 5000.0 + sum(
        5000.0 * i for reps in ((3,), (2,), (2,), (2,), (2,)) for ran in reps
        for i in range(2, ran + 2))
    assert totals["time_ps"] != absolute_sum
    assert totals["time_ps"] == _SYS021_TIME_PS


def test_steps_are_derived_from_elapsed_time_and_dt(sys021_tree):
    """The final NSTEP is not retrievable -- ThermoStats parses the key and discards it --
    so steps-that-ran is elapsed/dt and there is no other source.

    This pins the CAMPAIGN number only. It cannot, on its own, tell that rule from
    `sum(nstlim)`: every run in this tree ran exactly what it declared, so the two agree at
    35,500,000 and the assertion holds under either. The discrimination lives in
    `test_a_truncated_run_contributes_what_it_ran_not_what_it_declared` below, which is the
    first fixture in the repo where intent and execution differ at all.
    """
    totals = auto_discover(str(sys021_tree), recursive=True).totals()
    assert totals["steps"] == _SYS021_TIME_PS / 0.002


def test_a_truncated_run_contributes_what_it_ran_not_what_it_declared(truncated_run_tree):
    """"Ran, but not to the end" -- the run state the branch had no fixture for.

    `prod_0002` declares `nstlim = 2500000, dt = 0.002` (5000 ps) in both its mdin and its
    mdout, and its frames stop at 3000 ps: a wall-clock kill or a dead node, which is how
    most long chunks actually end. It must contribute 3000. `prod_0001` beside it declares
    and delivers the same 5000, so a rule that clipped every run to its frame span rather
    than reading the origin correctly would also have to survive that.

    This is the assertion the mutation "a ran stage contributes its own nstlim x dt" fails
    on, for both published numbers. Before `RunSpec.stated_ps` no fixture in the repo could
    express it: `_mdout_text` wrote `nstlim = elapsed_ps / dt`, making intent and execution
    identical everywhere.
    """
    protocol = auto_discover(str(truncated_run_tree), recursive=True)
    by_name = {s.name: s for s in protocol.stages}
    assert _elapsed_ps(by_name["prod_0001"]) == 5000.0
    assert _elapsed_ps(by_name["prod_0002"]) == 3000.0
    # Both stated 5000, so the pair totals 10000 under the intent rule and 8000 under the
    # execution rule. Only one of those is what the machine did.
    totals = protocol.totals()
    assert totals["time_ps"] == 8000.0
    assert totals["steps"] == 8000.0 / 0.002
    # Spelled out rather than left implicit: 5,000,000 is what the intent rule reports.
    assert totals["steps"] != 2 * 2500000.0


def test_steps_use_the_mdins_timestep_when_the_mdout_stated_none(tmp_path):
    """`steps` doubled, silently, whenever the mdout's CONTROL DATA block did not parse.

    `MdoutMetadata.dt` defaults to **0.001** -- truthy, and a perfectly ordinary real
    timestep -- so the guard `if not dt: <fall back to the mdin>` was dead code and the
    default sailed straight through. A 0.002 run whose control block the legacy parser
    missed published exactly TWICE its true step count, with the mdin sitting beside it
    stating 0.002 in plain text. `steps` is a published number: it is in `summary.json`'s
    totals, in every per-lineage breakdown, and in what the CLI prints.

    `MdoutHeader.control_dt_ps` is `None` when the file stated nothing, which is what makes
    the fallback reachable at all. The mdout here keeps its frames and its begin-time line
    and loses only the control block, which is the shape a truncated or unusually laid out
    mdout actually has.
    """
    from tests.conftest import RunSpec, _PROD_MDIN, _mdout_text

    text = _mdout_text(RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0, begin_ps=0.0))
    head, _, rest = text.partition("   2.  CONTROL  DATA  FOR  THE  RUN\n")
    _, _, tail = rest.partition("   3.  ATOMIC COORDINATES AND VELOCITIES\n")
    (tmp_path / "prod_0001.mdin").write_text(_PROD_MDIN, encoding="utf-8")
    (tmp_path / "prod_0001.mdout").write_text(head + tail, encoding="utf-8")

    protocol = auto_discover(str(tmp_path), recursive=True)
    stage, = protocol.stages
    # Grounds the scenario: the mdout really did state no timestep, and the value that
    # would be read off it instead is the class default rather than anything in the file.
    assert stage.mdout_header.control_dt_ps is None
    assert stage.mdout.details.dt == 0.001
    assert stage.mdin.details.dt == 0.002

    assert _elapsed_ps(stage) == 5000.0
    assert protocol.totals()["steps"] == 5000.0 / 0.002
    # 5,000,000 is the number the dead guard published: twice the truth.
    assert protocol.totals()["steps"] != 5000.0 / 0.001


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


# --- the CSV artifact must agree with the JSON artifact ---

def test_the_stats_csv_duration_agrees_with_the_summary_total(sys021_tree, tmp_path):
    """`summary.json`'s `totals()["time_ps"]` and `stats.csv`'s `duration_ns` column used
    to come from two different formulas and quietly disagreed: `stats.csv` read
    `stats.duration_ns` (`time_end - time_start`), short by one ntpr interval per chunk,
    while `totals()` used `time_end - begin_time_ps`. On the back-compat fixture that was
    99.5 ns against a true 100.0 ns for the identical run, both numbers shipped in the same
    artifact bundle a researcher would plot from.

    Both now call `_elapsed_ps(stage)` -- `write_stats_csv` directly, `_sum_stages`
    through the same function -- so this is not "the two numbers happen to match today",
    it is "the two numbers cannot come apart without one of them stopping to call
    `_elapsed_ps`". Recomputing the CSV's total independently (summing the column back up,
    rather than re-deriving it a third way) and comparing it against `totals()["time_ps"]`
    is what a future formula change on either side would have to break.
    """
    protocol = auto_discover(str(sys021_tree), recursive=True)
    out = tmp_path / "stats.csv"
    write_stats_csv(protocol, str(out))
    rows = list(csv.DictReader(out.open(encoding="utf-8")))

    # Every ran stage wrote a duration; every queued one left the cell blank -- not "0.0",
    # which would misreport "no time" as a measured fact rather than an absent one.
    ran = [r for r in rows if r["duration_ns"] != ""]
    queued = [r for r in rows if r["duration_ns"] == ""]
    assert len(ran) + len(queued) == len(rows)
    # One queued chunk per replica (5), plus the stray `cpptraj.in` sys021_tree's docstring
    # says gets typed as a queued mdin by extension -- both are "no mdout", so both belong
    # in this bucket rather than the ran one.
    assert len(queued) == 6

    csv_total_ns = sum(float(r["duration_ns"]) for r in ran)
    assert csv_total_ns * 1000.0 == protocol.totals()["time_ps"]
