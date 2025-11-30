from ambermeta.parsers import (
    InpcrdParser,
    MdcrdParser,
    MdinParser,
    MdoutParser,
    PrmtopParser,
)


def test_prmtop_parser(sample_md_data_dir):
    prmtop_file = sample_md_data_dir / "CH3L1_HUMAN_6NAG.top"
    result = PrmtopParser(str(prmtop_file)).parse()
    assert result.filename == str(prmtop_file)
    assert result.details is not None


def test_inpcrd_parser(sample_md_data_dir):
    inpcrd_file = sample_md_data_dir / "CH3L1_HUMAN_6NAG.crd"
    result = InpcrdParser(str(inpcrd_file)).parse()
    assert result.filename == str(inpcrd_file)
    assert result.details is not None
    assert result.details.file_format


def test_mdin_parser(sample_md_data_dir):
    mdin_file = sample_md_data_dir / "ntp_prod_0001.mdin"
    result = MdinParser(str(mdin_file)).parse()
    assert result.filename == str(mdin_file)
    assert result.details is not None


def test_mdout_parser(sample_md_data_dir):
    mdout_file = sample_md_data_dir / "ntp_prod_0001.mdout"
    result = MdoutParser(str(mdout_file)).parse()
    assert result.filename == str(mdout_file)
    assert result.details is not None


def test_mdcrd_parser(sample_md_data_dir):
    trajectory_file = sample_md_data_dir / "CH3L1_HUMAN_6NAG.crd"
    result = MdcrdParser(str(trajectory_file)).parse()
    assert result.filename == str(trajectory_file)
    assert result.details is not None
