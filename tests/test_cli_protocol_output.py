from __future__ import annotations

from types import SimpleNamespace

from ambermeta.cli import _print_protocol
from ambermeta.protocol import SimulationProtocol, SimulationStage, auto_discover


def test_print_protocol_reports_control_and_stats(capsys, sample_md_data_dir):
    protocol = auto_discover(
        str(sample_md_data_dir),
        grouping_rules={"CH3L1": "equilibration", "^ntp_prod": "production"},
        include_stems=["ntp_prod_0001"],
        restart_files={"production": str(sample_md_data_dir / "ntp_prod_0000.rst")},
        skip_cross_stage_validation=True,
    )

    _print_protocol(protocol)
    output = capsys.readouterr().out

    assert "mdin: steps=5000000, dt=0.004 ps" in output
    assert (
        "mdout: status=complete, steps=5000000, dt=0.004 ps, "
        "thermostat=Langevin @ 300 K, barostat=Berendsen, box=RECTILINEAR" in output
    )
    assert (
        "stats: frames=200, time=1020–20920 ps, temp=300.43 ± 1.25 K, "
        "density=1.0370 ± 0.0012 g/cc" in output
    )


def test_print_protocol_includes_mdcrd_box_and_remd_metadata(capsys):
    mdcrd_details = SimpleNamespace(
        n_frames=10,
        time_start=0.0,
        time_end=9.0,
        avg_dt=1.0,
        has_box=True,
        box_type="Triclinic",
        volume_stats=(90.0, 110.0, 100.0),
        is_remd=True,
        remd_types=["T"],
        remd_temp_stats=(280.0, 320.0, 300.0),
    )
    stage = SimulationStage(
        name="remd_stage",
        mdin=SimpleNamespace(details=SimpleNamespace(length_steps=10, dt=1.0)),
        mdcrd=SimpleNamespace(details=mdcrd_details),
    )
    protocol = SimulationProtocol(stages=[stage])

    _print_protocol(protocol)
    output = capsys.readouterr().out

    assert "mdcrd: frames=10, time=0–9 ps, dt≈1 ps, box=Triclinic, volume≈100.00 Å³, T (280.0–320.0K, avg 300.0K)" in output


def test_print_protocol_reports_the_queued_count_and_marks_each_queued_stage(capsys, sys021_tree):
    """`plan --recursive`'s own terminal output, not only the JSON/GUI report, has to say
    a run was queued -- this was the third of three surfaces (`Step.status` via
    `discover_draft`, `SimulationStage.to_dict()`, and this one) that stayed silent after
    the engine started computing the right answer."""
    protocol = auto_discover(str(sys021_tree), recursive=True)

    _print_protocol(protocol)
    output = capsys.readouterr().out

    assert "Queued (no output): 5" in output
    assert "- prod/01/nvt_prod_0004" in output
    # The line belongs to that stage's own block, immediately under its name -- not merely
    # present anywhere in the output, which a query-string match would not catch a queued
    # stage's line drifting under the WRONG stage's header.
    block_start = output.index("- prod/01/nvt_prod_0004")
    block = output[block_start:output.index("\n\n", block_start)]
    assert "status: queued" in block


def test_print_protocol_prints_no_status_line_for_a_run_that_produced_output(capsys, sys021_tree):
    protocol = auto_discover(str(sys021_tree), recursive=True)

    _print_protocol(protocol)
    output = capsys.readouterr().out

    block_start = output.index("- prod/01/nvt_prod_0001")
    block = output[block_start:output.index("\n\n", block_start)]
    assert "status:" not in block


def test_print_protocol_says_nothing_about_queued_runs_when_there_are_none(capsys, sample_md_data_dir):
    """Emit-when-nonzero: a directory with nothing queued prints exactly what it always
    did, with no new "Queued" line to explain."""
    protocol = auto_discover(str(sample_md_data_dir), recursive=True)

    _print_protocol(protocol)
    output = capsys.readouterr().out

    assert "Queued" not in output
