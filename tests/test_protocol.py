from __future__ import annotations

from pathlib import Path

from ambermeta.protocol import auto_discover


TEST_DATA = Path(__file__).resolve().parent.parent / "md_test_files"


def test_auto_discover_filters_by_role():
    protocol = auto_discover(
        str(TEST_DATA),
        grouping_rules={"CH3L1": "equilibration", "^ntp_prod": "production"},
        include_roles=["production"],
        skip_cross_stage_validation=True,
    )

    assert protocol.stages
    assert all(stage.stage_role == "production" for stage in protocol.stages)
    assert all(stage.name.startswith("ntp_prod") for stage in protocol.stages)


def test_auto_discover_restart_override_for_subset():
    restart_file = TEST_DATA / "ntp_prod_0000.rst"

    protocol = auto_discover(
        str(TEST_DATA),
        grouping_rules={"^ntp_prod": "production"},
        include_stems=["ntp_prod_0001"],
        restart_files={"production": str(restart_file)},
        skip_cross_stage_validation=True,
    )

    assert len(protocol.stages) == 1
    stage = protocol.stages[0]
    assert stage.stage_role == "production"
    assert stage.inpcrd is not None
    assert stage.inpcrd.filename == str(restart_file)
    assert stage.restart_path == str(restart_file)


def test_auto_discover_can_isolate_equilibration():
    protocol = auto_discover(
        str(TEST_DATA),
        grouping_rules={"CH3L1": "equilibration", "^ntp_prod": "production"},
        include_roles=["equilibration"],
        skip_cross_stage_validation=True,
    )

    assert len(protocol.stages) == 1
    assert protocol.stages[0].name.startswith("CH3L1_HUMAN_6NAG")
    assert protocol.stages[0].stage_role == "equilibration"
