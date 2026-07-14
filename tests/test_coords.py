# tests/test_coords.py
from ambermeta.coords import sniff_coordinate_kind


def test_real_crd_is_a_starting_structure(sample_md_data_dir):
    # tleap saveamberparm output — a single-frame starting structure, not a trajectory
    path = sample_md_data_dir / "CH3L1_HUMAN_6NAG.crd"
    assert sniff_coordinate_kind(str(path)) == "inpcrd"


def test_ascii_trajectory_is_mdcrd(tmp_path):
    traj = tmp_path / "run.crd"
    # classic ASCII trajectory: title then coordinate rows (no NATOM header line)
    traj.write_text("TITLE\n" + ("  1.000  2.000  3.000  4.000  5.000  6.000\n" * 4))
    assert sniff_coordinate_kind(str(traj)) == "mdcrd"


def test_inpcrd_header_with_time(tmp_path):
    rst = tmp_path / "x.crd"
    rst.write_text("default_name\n     6  0.0010000E+03\n" + "  1.0  2.0  3.0  4.0  5.0  6.0\n" * 3)
    assert sniff_coordinate_kind(str(rst)) == "inpcrd"
