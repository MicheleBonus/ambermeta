# tests/test_protocol_begin_time_overflow.py
"""AMBER prints `begin time read from input coords` into a fixed-width Fortran field.
Once a restarted chain's accumulated simulated time passes roughly 1e6 ps the value no
longer fits and AMBER writes `**********` instead of a number:

    begin time read from input coords =********** ps

`mdout_header.py`'s `_BEGIN_TIME` requires a digit and simply does not match, so
`begin_time_ps` comes back `None` -- for a run that is otherwise perfectly healthy: same
file size as its neighbours, a full TIMINGS block, both a trajectory and a restart
written. Before this file, that meant `_elapsed_ps` returned `None` and the run's whole
elapsed time silently vanished from `totals()` -- the exact failure P1.1 exists to
prevent, pointed the other way, and one that gets *worse* with campaign length rather
than better (`sys021`'s own `prod/01/nvt_prod_0201` crossed this threshold; the rest of
the campaign will follow it).

Pins the fencepost fallback (`_fenced_elapsed_ps`/`_fenced_begin_time_ps` in
`ambermeta/protocol.py`) at both of its call sites -- `_elapsed_ps_and_source` (totals,
`_validate_elapsed_time`'s note) and `_check_stage_pair` (continuity) -- and the one
detail most likely to be broken by accident: a single-frame chunk must report `None`, not
a false `0.0`, because `ThermoStats.avg_interval_ps`/`true_coverage_ns` both special-case
`count < 2` to `0.0`.

What is deliberately NOT re-asserted here: the ordinary header-present arithmetic
(`test_protocol_totals_from_mdout.py`) and the "mdout present but unusable" note's other
three causes (`test_protocol_unusable_mdout.py`). This file is only about the fourth
route to the same numbers -- the one that exists because the header can overflow.
"""
from __future__ import annotations

from ambermeta.legacy_extractors.mdout import ThermoStats
from ambermeta.mdout_header import MdoutHeader
from ambermeta.protocol import (
    SimulationProtocol,
    SimulationStage,
    _elapsed_ps,
    auto_discover,
)

from tests.conftest import RunSpec, write_run_tree

_PROD_MDIN = ("production\n &cntrl\n  imin = 0, irest = 1, nstlim = 2500000,\n"
              "  dt = 0.002, ntb = 2,\n /\n")

# The real tree's own overflowed value (`prod/01/nvt_prod_0201`'s header), reused here
# rather than an arbitrary number past the ~1e6 threshold so the fixture is traceable back
# to the run that motivated this file.
_OVERFLOW_BEGIN_PS = 999999.992


def _derived_notes(stage):
    return [m for m in stage.validation if "derived from frame spacing" in m]


def _unusable_notes(stage):
    return [m for m in stage.validation if "could not be measured" in m]


# --- 1 & 2: the overflowed run still contributes its elapsed time, with a note --------

def test_an_overflowed_header_still_contributes_its_elapsed_time(tmp_path):
    """The defect itself, reproduced and fixed: without the fallback this stage's 5000 ps
    would vanish from `totals()` exactly as `prod/01/nvt_prod_0201`'s did on the real
    tree."""
    write_run_tree(tmp_path, [
        ("overflowed", RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0,
                                begin_ps=_OVERFLOW_BEGIN_PS, begin_overflowed=True)),
    ])
    protocol = auto_discover(str(tmp_path), recursive=True)
    stage, = protocol.stages

    # Grounds the scenario: the header line really did fail to parse, the way it does on
    # the real overflowed run -- not merely a fixture bug that happens to leave a number
    # out of the file.
    assert stage.mdout_header.begin_time_ps is None
    assert stage.mdout.details.stats.count == 5

    assert _elapsed_ps(stage) == 5000.0
    assert protocol.totals()["time_ps"] == 5000.0


def test_the_derived_value_agrees_with_the_header_formula_to_the_digit(tmp_path):
    """Design-doc claim, pinned: measured against a healthy twin covering the identical
    span, the fencepost estimate agrees with `time_end - begin_time_ps` "to the digit" --
    5000.0 in both cases, not merely close."""
    write_run_tree(tmp_path, [
        ("healthy", RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0, begin_ps=920.0)),
        ("overflowed", RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0,
                                begin_ps=_OVERFLOW_BEGIN_PS, begin_overflowed=True)),
    ])
    protocol = auto_discover(str(tmp_path), recursive=True)
    by_name = {s.name: s for s in protocol.stages}

    healthy_elapsed = _elapsed_ps(by_name["healthy"])
    overflowed_elapsed = _elapsed_ps(by_name["overflowed"])
    assert healthy_elapsed == 5000.0
    assert overflowed_elapsed == 5000.0
    assert healthy_elapsed == overflowed_elapsed


def test_the_overflowed_run_carries_a_note_that_the_value_was_derived(tmp_path):
    """Requirement 3: a stage measured by the fallback has to say so, because a value
    silently substituted for the header's is indistinguishable from one AMBER actually
    printed -- exactly where that distinction matters most, on a campaign where many
    overflowed chunks compound the estimate's error."""
    write_run_tree(tmp_path, [
        ("overflowed", RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0,
                                begin_ps=_OVERFLOW_BEGIN_PS, begin_overflowed=True)),
    ])
    protocol = auto_discover(str(tmp_path), recursive=True)
    stage, = protocol.stages

    assert _derived_notes(stage) == [
        "INFO: Elapsed time for overflowed was derived from frame spacing, not read "
        "from the header (its stated begin time overflowed AMBER's fixed-width field)."
    ]
    # Not the OTHER note: a value was produced, so this is not "unusable".
    assert _unusable_notes(stage) == []


# --- 3: a single-frame chunk must not report a false zero -----------------------------

def test_a_single_frame_overflowed_run_reports_none_not_a_false_zero(tmp_path):
    """The detail most likely to be broken by accident. `ThermoStats.avg_interval_ps`
    returns `0.0` for `count < 2`, and `true_coverage_ns` propagates that into a "0.0 ns"
    that reads as a legitimate answer rather than "cannot estimate" -- so a naive fallback
    would report this stage's one frame as exactly zero elapsed time, a false zero
    indistinguishable from "this stage ran no time at all". It must come back `None`
    instead, and keep the SAME "could not be measured" note a header-less single-frame run
    already gets (see test_protocol_unusable_mdout.py) -- not a new, misleading "derived"
    one, since nothing was in fact derived."""
    write_run_tree(tmp_path, [
        ("overflowed_one_frame", RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0,
                                          begin_ps=_OVERFLOW_BEGIN_PS,
                                          begin_overflowed=True, frames=1)),
    ])
    protocol = auto_discover(str(tmp_path), recursive=True)
    stage, = protocol.stages

    assert stage.mdout.details.stats.count == 1     # really did run one frame
    assert _elapsed_ps(stage) is None
    assert protocol.totals()["time_ps"] == 0.0

    assert _unusable_notes(stage) == [
        "INFO: Elapsed time for overflowed_one_frame could not be measured "
        "(mdout present but unusable)."
    ]
    assert _derived_notes(stage) == []


# --- 4: continuity is still checked across a pair whose consumer's header overflowed --
#
# `_check_stage_pair` reads `begin_time_ps` a second time, independently of
# `_elapsed_ps_and_source`, so the fix has to be applied there too or continuity is
# silently skipped for exactly the runs whose totals were just fixed. Built at the
# `SimulationStage`/`ThermoStats` level, the way `test_continuity_p1.py` already does for
# this same method, rather than through `write_run_tree` + `auto_discover`: the file-based
# fixtures type a run's OWN `.restrt` as ITS OWN `inpcrd` by extension (see
# `_restart_text`'s docstring), which reaches `_check_stage_pair`'s `inpcrd` branch before
# the header branch is ever tried and so cannot exercise the header-overflow fallback at
# all.

def _stats_from_frames(*times_ps):
    """A real `ThermoStats`, built the way `parse_mdout` builds one -- by feeding it
    `TIME(PS)` frames -- so `avg_interval_ps`/`true_coverage_ns` are genuinely computed
    here rather than asserted into a stand-in object."""
    stats = ThermoStats()
    for t in times_ps:
        stats.add_frame({"TIME(PS)": t})
    return stats


class _Details:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FileData:
    def __init__(self, **kw):
        self.details = _Details(**kw)


def test_continuity_is_checked_across_a_pair_whose_consumer_header_overflowed():
    prev = SimulationStage(name="a")
    prev.mdout = _FileData(stats=_stats_from_frames(10000.0))   # a ends at 10000 ps

    # b's header overflowed (`begin_time_ps=None`) but its own 5 frames, evenly spaced
    # 1000 ps apart from 11000 to 15000, let the fencepost recover its true begin exactly:
    # avg_interval_ps = 1000.0, so fenced elapsed = (15000-11000+1000) = 5000.0 and fenced
    # begin = 15000 - 5000 = 10000.0 -- a seamless continuation of `a`.
    curr = SimulationStage(name="b")
    curr.mdout = _FileData(stats=_stats_from_frames(11000.0, 12000.0, 13000.0, 14000.0,
                                                      15000.0))
    curr.mdout_header = MdoutHeader(begin_time_ps=None)

    SimulationProtocol(stages=[prev, curr]).validate()

    assert curr.observed_gap_ps == 0.0
    assert not any("Cannot verify" in n for n in curr.continuity)
    assert any(
        n == ("INFO: Start time for b was derived from frame spacing, not read from "
              "the header (its stated begin time overflowed AMBER's fixed-width field).")
        for n in curr.continuity
    )


def test_continuity_still_reports_a_real_gap_through_the_derived_start_time():
    """Not just "agrees when seamless" -- the fallback has to carry a REAL gap through
    too, or a silent bug that always derived `time_end` (reporting 0 every time) could
    pass the seamless test above for the wrong reason."""
    prev = SimulationStage(name="a")
    prev.mdout = _FileData(stats=_stats_from_frames(10000.0))

    # Same spacing as above, but shifted 50 ps later throughout -- fenced begin becomes
    # 10050.0, a real 50 ps gap against `a`'s 10000.0 end.
    curr = SimulationStage(name="b")
    curr.mdout = _FileData(stats=_stats_from_frames(11050.0, 12050.0, 13050.0, 14050.0,
                                                      15050.0))
    curr.mdout_header = MdoutHeader(begin_time_ps=None)

    SimulationProtocol(stages=[prev, curr]).validate()

    assert curr.observed_gap_ps == 50.0
    assert any("starts 50 ps after" in n for n in curr.continuity)


def test_a_single_frame_consumer_still_cannot_verify_continuity():
    """The same no-false-zero rule applies to the begin-time fallback: a single-frame
    consumer has no interval to infer a begin time from, so it must fall through to
    "Cannot verify continuity", not report a fabricated start time of exactly its own
    `time_end`."""
    prev = SimulationStage(name="a")
    prev.mdout = _FileData(stats=_stats_from_frames(10000.0))

    curr = SimulationStage(name="b")
    curr.mdout = _FileData(stats=_stats_from_frames(15000.0))   # one frame only
    curr.mdout_header = MdoutHeader(begin_time_ps=None)

    SimulationProtocol(stages=[prev, curr]).validate()

    assert curr.observed_gap_ps is None
    assert any("Cannot verify continuity" in n for n in curr.continuity)


# --- 5: a healthy run is unaffected -----------------------------------------------------

def test_a_healthy_run_is_unaffected_and_carries_no_derived_note(tmp_path):
    """The control: header intact, well below the overflow threshold -- the fallback must
    stay dead code here, exactly as it must against the byte-pinned goldens."""
    write_run_tree(tmp_path, [
        ("healthy", RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0, begin_ps=920.0)),
    ])
    protocol = auto_discover(str(tmp_path), recursive=True)
    stage, = protocol.stages

    assert stage.mdout_header.begin_time_ps == 920.0
    assert _elapsed_ps(stage) == 5000.0
    assert _derived_notes(stage) == []
    assert _unusable_notes(stage) == []
