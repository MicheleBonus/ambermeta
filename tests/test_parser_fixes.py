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
