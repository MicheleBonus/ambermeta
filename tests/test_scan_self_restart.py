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
