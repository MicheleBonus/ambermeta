"""The header-only mdout read: resolved seed, authoritative begin time, File Assignments.

Design section 3 decision 8 and section 11. Section 11 is explicit that its four claims are
established only against one fixture family — Amber 22 pmemd.cuda, `ntt=3`, `irest=1` — so
the tests here split in two: what the five committed mdouts actually say, and what a header
missing each of those things must report. Absence has to read as absence. A seed reported
where none was stated would say a campaign's replicas share one, which is precisely the
claim decision 4 forbids emitting.
"""
from __future__ import annotations

import pytest

from ambermeta.mdout_header import read_mdout_header

SEEDS = {1: 70038, 2: 761443, 3: 410249, 4: 613120, 5: 570364}
BEGINS = {1: 920.0, 2: 20920.0, 3: 40920.0, 4: 60920.0, 5: 80920.0}


@pytest.fixture
def mdouts(sample_md_data_dir):
    return {i: str(sample_md_data_dir / f"ntp_prod_{i:04d}.mdout") for i in SEEDS}


# ---------------------------------------------------------------------------
# What the committed fixtures say
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("index", sorted(SEEDS))
def test_each_fixture_reports_its_own_seed_and_begin_time(mdouts, index):
    header = read_mdout_header(mdouts[index])
    assert header.resolved_ig == SEEDS[index]
    assert header.begin_time_ps == BEGINS[index]


def test_the_begin_time_is_not_the_first_printed_frame(mdouts):
    """`stats.time_start` is one `ntpr` interval later — 1020.0 against a true 920.0.

    Reaching for it instead of this line manufactures a 100 ps gap on every chunked run,
    and does it while appearing to agree with the committed summary.json, which records
    1020.0 because that genuinely is where the first frame was printed.
    """
    from ambermeta.legacy_extractors.mdout import parse_mdout
    assert read_mdout_header(mdouts[1]).begin_time_ps == 920.0
    assert parse_mdout(mdouts[1]).stats.time_start == 1020.0


def test_the_chain_amber_asserts_is_read_from_file_assignments(mdouts):
    """Not an inference from filename adjacency — the run says what it read and wrote."""
    header = read_mdout_header(mdouts[3])
    assert header.assignment("INPCRD").endswith("ntp_prod_0002.rst")
    assert header.assignment("RESTRT") == "ntp_prod_0003.rst"
    assert header.assignment("MDCRD") == "ntp_prod_0003.nc"


def test_a_value_that_filled_its_field_is_reported_as_unusable(mdouts):
    """87 is not a field width — the block mixes 80- and 87-character lines — so
    truncation is detected by the value having no trailing padding, not by a column.

    PARM is the only clipped value in these fixtures, and `.../cryst/CH3L1_HUMAN` prefix-
    matches every topology whose name starts that way. A match that cannot distinguish is
    not evidence, so `assignment` returns None rather than the fragment.
    """
    header = read_mdout_header(mdouts[1])
    assert header.truncated == {"PARM"}
    assert header.assignment("PARM") is None
    assert header.file_assignments["PARM"].endswith("CH3L1_HUMAN")   # still recorded
    assert header.assignment("MDOUT") == "ntp_prod_0001.mdout"       # short, so intact


# ---------------------------------------------------------------------------
# What a header that says nothing must report
# ---------------------------------------------------------------------------

def _mdout(tmp_path, body: str) -> str:
    path = tmp_path / "synthetic.mdout"
    path.write_text(body, encoding="utf-8")
    return str(path)


NOTE_ONLY = """\
          -------------------------------------------------------
File Assignments:
|   MDIN: min.in
|  MDOUT: min.out

Note: ig = -1. Setting random seed to    70038 based on wallclock time in
      microseconds.
| irandom = 1, using AMBER's internal random number generator (default).

   3.  ATOMIC COORDINATES AND VELOCITIES
--------------------------------------------------------------------------------
 begin time read from input coords =   500.000 ps

   4.  RESULTS
 NSTEP =    25000   TIME(PS) =     600.000  TEMP(K) =   302.09
"""


def test_a_minimisation_style_header_states_no_seed(tmp_path):
    """The seed block sits under `Langevin dynamics temperature regulation:`, which a
    minimisation or a non-Langevin thermostat need not print. Without it the seed is
    unknown — and the free-text note above must not be mistaken for it.

    The note is a trap, not a fallback: a key=value reader applied to
    `Note: ig = -1. Setting random seed to 70038...` returns **-1**, the value the user
    asked not to use, and the resolved 70038 is prose on a sentence that wraps onto the
    next line. Recording -1 gives every run in a campaign the same seed.
    """
    header = read_mdout_header(_mdout(tmp_path, NOTE_ONLY))
    assert header.resolved_ig is None
    assert header.begin_time_ps == 500.0


def test_a_header_with_no_begin_time_reports_none(tmp_path):
    header = read_mdout_header(_mdout(tmp_path, "File Assignments:\n|   MDIN: x.in   \n"))
    assert header.begin_time_ps is None
    assert header.resolved_ig is None
    assert header.assignment("MDIN") == "x.in"


def test_reading_stops_at_the_results_banner(tmp_path):
    """The stop is `4. RESULTS`, not the `3. ATOMIC COORDINATES` banner section 11 proposed
    — the begin time is four lines below that one, so stopping there returns None on every
    real file. Anything after the results banner is per-frame output and is not the
    header's to interpret."""
    body = NOTE_ONLY + """\
Langevin dynamics temperature regulation:
     ig      =   99999
 begin time read from input coords =   1.000 ps
"""
    header = read_mdout_header(_mdout(tmp_path, body))
    assert header.resolved_ig is None      # the block after RESULTS was never reached
    assert header.begin_time_ps == 500.0   # the real one, not the later line


def test_a_negative_seed_is_not_a_resolved_seed(tmp_path):
    """`-1` is the request, not the choice. Nothing is learned from recording it, and
    recording it makes every run that asked for a random seed look identically seeded."""
    body = "Langevin dynamics temperature regulation:\n     ig      =   -1\n"
    assert read_mdout_header(_mdout(tmp_path, body)).resolved_ig is None


# ---------------------------------------------------------------------------
# It has to reach the engine, by both routes
# ---------------------------------------------------------------------------

def test_the_header_reaches_the_stage_on_the_scan_path(sample_md_data_dir):
    """The anti-no-op assertion. `lineage` was the same shape of change in PR 2a and had
    to be plumbed through four sites; a header attached on one route into the engine and
    not the other is invisible until a user runs the other command."""
    from ambermeta.protocol import auto_discover
    protocol = auto_discover(str(sample_md_data_dir), manifest=None, recursive=True)
    seeded = [s for s in protocol.stages if s.mdout_header and s.mdout_header.resolved_ig]
    assert len(seeded) == 5
    assert {s.mdout_header.resolved_ig for s in seeded} == set(SEEDS.values())


def test_the_header_reaches_the_stage_on_the_manifest_path(sample_md_data_dir, tmp_path):
    import shutil

    from ambermeta.cli import main
    from ambermeta.gui.api.core_bridge import _flatten_simulation, build_protocol
    from ambermeta.simulation import load_simulation

    run = tmp_path / "run"
    run.mkdir()
    for f in sample_md_data_dir.iterdir():
        shutil.copy(f, run)
    assert main(["discover", str(run), "--write", str(run / "draft.yaml")]) == 0

    sim = load_simulation(str(run / "draft.yaml"))
    protocol = build_protocol(_flatten_simulation(sim), {}, str(run))
    seeded = [s for s in protocol.stages if s.mdout_header and s.mdout_header.resolved_ig]
    assert {s.mdout_header.resolved_ig for s in seeded} == set(SEEDS.values())


def test_the_header_stays_out_of_the_artifacts(sample_md_data_dir):
    """`MdoutMetadata` is serialised with `asdict()` straight into summary.json, so a field
    added there appears verbatim in an artifact users keep and fails the back-compat gate
    with real non-null values. That is why this is a side-car object on the stage, and why
    `SimulationStage.to_dict()`'s fixed key list is load-bearing."""
    from ambermeta.protocol import auto_discover
    protocol = auto_discover(str(sample_md_data_dir), manifest=None, recursive=True)
    assert any(s.mdout_header for s in protocol.stages)
    assert "70038" not in str(protocol.to_dict())
    assert all("mdout_header" not in s for s in protocol.to_dict()["stages"])
