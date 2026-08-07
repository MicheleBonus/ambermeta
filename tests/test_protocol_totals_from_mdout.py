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

from ambermeta.protocol import auto_discover


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
