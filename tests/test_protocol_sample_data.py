from __future__ import annotations

from ambermeta.parsers import InpcrdParser, MdinParser, MdoutParser, PrmtopParser
from ambermeta.protocol import auto_discover


ATOM_COUNT = 64528
TIMESTEP = 0.004
STEPS_PER_STAGE = 5_000_000


def test_equilibration_pair_metadata(sample_md_data_dir):
    prmtop = PrmtopParser(str(sample_md_data_dir / "CH3L1_HUMAN_6NAG.top")).parse()
    inpcrd = InpcrdParser(str(sample_md_data_dir / "CH3L1_HUMAN_6NAG.crd")).parse()

    assert prmtop.details is not None
    assert inpcrd.details is not None
    assert prmtop.details.natom == ATOM_COUNT
    assert inpcrd.details.natoms == ATOM_COUNT
    assert prmtop.details.box_dimensions is not None
    assert inpcrd.details.has_box


def test_production_control_metadata(sample_md_data_dir):
    mdin = MdinParser(str(sample_md_data_dir / "ntp_prod_0001.mdin")).parse()
    mdout = MdoutParser(str(sample_md_data_dir / "ntp_prod_0001.mdout")).parse()

    assert mdin.details is not None
    assert mdout.details is not None
    assert mdin.details.length_steps == STEPS_PER_STAGE
    assert mdin.details.dt == TIMESTEP
    assert mdout.details.natoms == ATOM_COUNT
    assert mdout.details.box_type == "RECTILINEAR"
    assert mdout.details.nstlim == STEPS_PER_STAGE
    assert mdout.details.dt == TIMESTEP


def test_auto_discover_loads_equilibration_restart(sample_md_data_dir):
    protocol = auto_discover(
        str(sample_md_data_dir),
        grouping_rules={"CH3L1": "equilibration", "^ntp_prod": "production"},
        include_stems=["CH3L1_HUMAN_6NAG"],
        restart_files={"CH3L1_HUMAN_6NAG": str(sample_md_data_dir / "CH3L1_HUMAN_6NAG.crd")},
        skip_cross_stage_validation=True,
    )

    assert len(protocol.stages) == 1
    stage = protocol.stages[0]
    assert stage.prmtop is not None
    assert stage.inpcrd is not None
    assert stage.inpcrd.filename == str(sample_md_data_dir / "CH3L1_HUMAN_6NAG.crd")
    assert stage.prmtop.details.natom == ATOM_COUNT
    assert stage.inpcrd.details.natoms == ATOM_COUNT
    assert stage.inpcrd.details.has_box


def test_auto_discover_filters_production_and_overrides_restart(sample_md_data_dir):
    restart_source = sample_md_data_dir / "ntp_prod_0000.rst"
    protocol = auto_discover(
        str(sample_md_data_dir),
        grouping_rules={"^ntp_prod": "production"},
        include_stems=["ntp_prod_0001"],
        restart_files={"production": str(restart_source)},
        skip_cross_stage_validation=True,
    )

    assert len(protocol.stages) == 1
    stage = protocol.stages[0]
    assert stage.stage_role == "production"
    assert stage.inpcrd is not None
    assert stage.inpcrd.filename == str(restart_source)
    assert stage.restart_path == str(restart_source)
    assert stage.mdin is not None
    assert stage.mdout is not None
    assert stage.mdin.details.length_steps == STEPS_PER_STAGE
    assert stage.mdout.details.dt == TIMESTEP
    assert stage.mdout.details.natoms == ATOM_COUNT
