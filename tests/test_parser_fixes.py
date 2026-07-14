# tests/test_parser_fixes.py
import math
import pytest


def _write_prmtop(path, *, natom, nres, res_labels, charges=None, masses=None,
                  atomic_numbers=None, atom_names=None, radius_set=None, box=None):
    """Write a minimal but real prmtop containing only the flags a test needs.
    `box` is [beta, a, b, c] (the legacy BOX_DIMENSIONS layout)."""
    out = ["%VERSION VERSION_STAMP = V0001.000  DATE = 01/01/25"]

    def ints(vals, per=10, w=8):
        return ["".join(f"{v:{w}d}" for v in vals[i:i + per]) for i in range(0, len(vals), per)] or [""]

    def floats(vals, per=5, w=16):
        return ["".join(f"{v:{w}.8E}" for v in vals[i:i + per]) for i in range(0, len(vals), per)] or [""]

    def a4(vals, per=20):
        return ["".join(f"{str(v):<4}"[:4] for v in vals[i:i + per]) for i in range(0, len(vals), per)] or [""]

    def block(flag, fmt, cells):
        out.append(f"%FLAG {flag}")
        out.append(f"%FORMAT({fmt})")
        out.extend(cells)

    pointers = [0] * 32
    pointers[0] = natom
    pointers[11] = nres
    block("POINTERS", "10I8", ints(pointers))
    block("RESIDUE_LABEL", "20a4", a4(res_labels))
    if charges is not None:
        block("CHARGE", "5E16.8", floats(charges))
    if masses is not None:
        block("MASS", "5E16.8", floats(masses))
    if atomic_numbers is not None:
        block("ATOMIC_NUMBER", "10I8", ints(atomic_numbers))
    if atom_names is not None:
        block("ATOM_NAME", "20a4", a4(atom_names))
    if radius_set is not None:
        block("RADIUS_SET", "1a80", [radius_set])
    if box is not None:
        block("BOX_DIMENSIONS", "5E16.8", floats(box))
    path.write_text("\n".join(out) + "\n")


from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata, _classify_simulation, PrmtopMetadata


def test_boxless_prmtop_is_non_periodic_not_implicit(tmp_path):
    p = tmp_path / "vac.prmtop"
    _write_prmtop(p, natom=1, nres=1, res_labels=["LIG"],
                  radius_set="modified Bondi radii (mbondi)")  # RADIUS_SET but NO box
    md = extract_prmtop_metadata(str(p))
    assert md.solvent_type == "Non-periodic"
    assert "Implicit Solvent" not in md.simulation_category
    assert "non-periodic" in md.simulation_category.lower()


def test_boxed_prmtop_is_explicit(sample_md_data_dir):
    md = extract_prmtop_metadata(str(sample_md_data_dir / "CH3L1_HUMAN_6NAG.top"))
    assert md.solvent_type == "Explicit Solvent"


def _md(comp, solvent="Explicit Solvent"):
    return PrmtopMetadata(filename="x", residue_composition=comp, solvent_type=solvent)


def test_protein_ligand_complex_names_ligand():
    md = _md({"ALA": 20, "LIG": 1, "WAT": 500})
    _classify_simulation(md)
    assert "Protein" in md.simulation_category and "Ligand" in md.simulation_category


def test_signless_ions_not_ligands():
    md = _md({"ALA": 20, "NA": 8, "CL": 8, "WAT": 500})
    _classify_simulation(md)
    assert "Ligand" not in md.simulation_category  # NA/CL are ions, not a ligand


def test_incomplete_charge_leaves_neutrality_unknown(tmp_path):
    p = tmp_path / "partial.prmtop"
    # natom=4 but only 2 charges present -> incomplete
    _write_prmtop(p, natom=4, nres=1, res_labels=["LIG"], charges=[0.5, -0.5])
    md = extract_prmtop_metadata(str(p))
    assert md.is_neutral is None
    assert any("neutrality verdict is uncertain" in w for w in md.warnings)


def test_atom_name_hmr_fallback_excludes_non_hydrogen(tmp_path):
    p = tmp_path / "names.prmtop"
    # "He" (helium, ~4.0) currently passes startswith("H") and mass<5 -> wrongly a "hydrogen".
    _write_prmtop(p, natom=3, nres=1, res_labels=["LIG"],
                  masses=[4.003, 1.008, 1.008], atom_names=["He", "H1", "H2"])
    md = extract_prmtop_metadata(str(p))
    assert md.hmr_detection_method == "atom_name"
    assert md.hmr_hydrogen_mass_range == (1.008, 1.008)   # He excluded
    assert md.hmr_active is False


def test_box_flagged_topology_time(sample_md_data_dir):
    md = extract_prmtop_metadata(str(sample_md_data_dir / "CH3L1_HUMAN_6NAG.top"))
    assert md.box_dimensions is not None
    assert md.box_is_topology_time is True
    assert any("topology-time box" in w.lower() for w in md.force_field_features + md.warnings)


from ambermeta.legacy_extractors.inpcrd import _detect_format as _inpcrd_detect


def test_inpcrd_detect_format_magic(tmp_path):
    classic = tmp_path / "a.ncrst"; classic.write_bytes(b"CDF\x01rest")
    hdf5 = tmp_path / "b.ncrst"; hdf5.write_bytes(b"\x89HDF\r\n")
    ascii_cdf = tmp_path / "c.rst"; ascii_cdf.write_text("CDF2 my restart title\n     3\n")
    assert _inpcrd_detect(str(classic)) == "NetCDF"
    assert _inpcrd_detect(str(hdf5)) == "NetCDF"     # HDF5-backed NetCDF, was misread as ASCII
    assert _inpcrd_detect(str(ascii_cdf)) == "ASCII" # title starting 'CDF', was misread as NetCDF


from ambermeta.legacy_extractors.inpcrd import parse_inpcrd


def _coords_only_inpcrd(path, natoms, trailing_blank):
    # title, "NATOM", then ceil(natoms*3/6) coord lines of 6 floats
    import math as _m
    body = "\n".join("  1.0  2.0  3.0  4.0  5.0  6.0" for _ in range(_m.ceil(natoms * 3 / 6)))
    text = f"default_name\n{natoms:6d}\n{body}\n"
    if trailing_blank:
        text += "\n"
    path.write_text(text)


def test_trailing_blank_line_does_not_fabricate_box(tmp_path):
    clean = tmp_path / "clean.inpcrd"; _coords_only_inpcrd(clean, 4, trailing_blank=False)
    blanked = tmp_path / "blank.inpcrd"; _coords_only_inpcrd(blanked, 4, trailing_blank=True)
    assert parse_inpcrd(str(clean)).has_box is False
    assert parse_inpcrd(str(blanked)).has_box is False   # was True: coord line read as box


from ambermeta.legacy_extractors.mdout import parse_mdout


def _mdout(path, control):
    path.write_text(
        "          Amber 22 PMEMD\n\n"
        "   1.  RESOURCE   USE:\n\n"
        "     NATOM  =    1000 NRES   =     300\n\n"
        "   2.  CONTROL  DATA:\n\n"
        f"{control}\n"
    )


def test_barostat_from_keyword_not_ntp(tmp_path):
    p = tmp_path / "npt.mdout"
    _mdout(p, "     ntp     =       1, barostat=       2, temp0   = 300.0,")
    md = parse_mdout(str(p))
    assert md.barostat == "Monte Carlo"   # from barostat=2, NOT Berendsen-from-ntp=1


def test_minimization_run_type(tmp_path):
    p = tmp_path / "min.mdout"
    _mdout(p, "     imin    =       1, maxcyc  =    5000, ntb     =       1,")
    md = parse_mdout(str(p))
    assert md.run_type == "Minimization"


from ambermeta.legacy_extractors.mdcrd import _detect_format as _mdcrd_detect
from ambermeta.legacy_extractors import mdcrd as _mdcrd


def test_mdcrd_detect_format_magic(tmp_path):
    hdf5 = tmp_path / "t.nc"; hdf5.write_bytes(b"\x89HDF\r\n")
    ascii_cdf = tmp_path / "t.mdcrd"; ascii_cdf.write_text("CDF trajectory title\n")
    assert _mdcrd_detect(str(hdf5)) == "NetCDF"
    assert _mdcrd_detect(str(ascii_cdf)) == "ASCII"


@pytest.mark.skipif(not _mdcrd.HAS_NETCDF or _mdcrd.np is None,
                    reason="needs a NetCDF backend + numpy to build an AMBERRESTART file")
def test_amberrestart_does_not_crash_trajectory_parser(tmp_path):
    import numpy as np
    path = str(tmp_path / "prod.ncrst")
    if _mdcrd.NETCDF_BACKEND == "netCDF4":
        ds = _mdcrd.nc.Dataset(path, "w", format="NETCDF3_64BIT_OFFSET")
        ds.Conventions = "AMBERRESTART"
        ds.createDimension("atom", 3); ds.createDimension("spatial", 3)
        t = ds.createVariable("time", "f8", ())      # 0-d scalar time
        t[...] = 10.0
        ds.createVariable("coordinates", "f8", ("atom", "spatial"))
        ds.close()
        # It is a .ncrst, but force the trajectory path to prove it degrades, not crashes:
        md = _mdcrd.parse_mdcrd(path)
        assert md is not None  # no uncaught TypeError


from ambermeta.legacy_extractors.mdcrd import parse_mdcrd, _is_variable_dt
import numpy as _np


def test_ascii_trajectory_flagged_not_silent(tmp_path):
    p = tmp_path / "old.mdcrd"
    p.write_text("TITLE\n" + "  1.000  2.000  3.000  4.000  5.000  6.000\n" * 4)
    md = parse_mdcrd(str(p))
    assert md.file_format == "ASCII"
    assert any("sequence analysis" in w.lower() for w in md.warnings)


def test_relative_dt_variance_threshold():
    # ~2 ps interval, float32-scale jitter -> NOT variable (relative check)
    steady = _np.array([2.0, 2.0001, 1.9999, 2.0002])
    assert _is_variable_dt(steady, 2.0) is False
    # a real doubling -> variable
    jumpy = _np.array([2.0, 4.0, 2.0, 4.0])
    assert _is_variable_dt(jumpy, 3.0) is True


from ambermeta.gui.api.files import detect_file_type, FileType
from ambermeta.gui.api import core_bridge
from ambermeta.protocol import smart_group_files


def test_extensionless_defaults_classified(tmp_path):
    for name in ("prmtop", "inpcrd", "mdin", "mdout", "mdcrd", "restrt"):
        (tmp_path / name).write_text("x")
    assert detect_file_type(str(tmp_path / "prmtop")) == FileType.PRMTOP
    assert detect_file_type(str(tmp_path / "mdout")) == FileType.MDOUT
    assert detect_file_type(str(tmp_path / "restrt")) == FileType.INPCRD
    assert core_bridge._EXT_KIND.get("") is None  # unchanged; kind resolved by basename
    grouped = smart_group_files(str(tmp_path), recursive=False)
    # the default job groups under stems (prmtop/inpcrd/... each their own stem)
    kinds = {k for g in grouped.values() for k in g if not k.startswith("_")}
    assert {"prmtop", "inpcrd", "mdin", "mdout", "mdcrd"} <= kinds


def test_trj_classified_as_trajectory(tmp_path):
    (tmp_path / "run.trj").write_text("x")
    assert detect_file_type(str(tmp_path / "run.trj")) == FileType.MDCRD
    assert core_bridge._EXT_KIND.get(".trj") == "mdcrd"
    grouped = smart_group_files(str(tmp_path), recursive=False)
    assert any("mdcrd" in g for g in grouped.values())
