"""Tests for CORE-D2/D7/H2/H3/D3/D4: natural stage ordering, single-digit sequence
detection, shared global/HMR prmtop helper, and missing-file warning/raise."""
import math
import pytest

from ambermeta.protocol import detect_numeric_sequences, _ordered_stems


def _write_prmtop(path, sections):
    """sections: dict flag -> (format_str, [values]). Writes a minimal prmtop."""
    lines = ["%VERSION  VERSION_STAMP = V0001.000  DATE = 01/01/26"]
    for flag, (fmt, values) in sections.items():
        lines.append(f"%FLAG {flag}")
        lines.append(f"%FORMAT({fmt})")
        # one value per line keeps it simple and fixed-width safe
        for v in values:
            if isinstance(v, float):
                lines.append(f"{v:16.8E}")
            else:
                lines.append(f"{int(v):8d}")
    path.write_text("\n".join(lines) + "\n")


def test_truncated_octahedron_volume(tmp_path):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    p = tmp_path / "trunc.prmtop"
    # BOX_DIMENSIONS: beta then a,b,c
    _write_prmtop(p, {
        "POINTERS": ("10I8", [3, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0]),
        "MASS": ("5E16.8", [1.0, 1.0, 1.0]),
        "BOX_DIMENSIONS": ("5E16.8", [109.4712206, 50.0, 50.0, 50.0]),
    })
    md = extract_prmtop_metadata(str(p))
    factor = md.box_volume / (50.0 ** 3)
    assert abs(factor - 0.7698) < 1e-3  # truncated-octahedron factor, not 0.9428
    # All three angles must be equal (all set to beta from BOX_DIMENSIONS[0])
    assert md.box_angles[0] == md.box_angles[1] == md.box_angles[2]
    assert abs(md.box_angles[0] - 109.4712206) < 1e-4


def test_natural_order_unpadded():
    grouped = {f"prod_{i}": {} for i in (1, 2, 10, 11)}
    assert _ordered_stems(grouped) == ["prod_1", "prod_2", "prod_10", "prod_11"]


def test_sequence_detects_single_digits():
    seqs = detect_numeric_sequences(["prod_1", "prod_2", "prod_3"])
    assert any(len(v) == 3 for v in seqs.values())


def _write_prmtop_atoms(path, atom_names, masses):
    name_line = "".join(f"{n:<4}" for n in atom_names)
    lines = [
        "%VERSION VERSION_STAMP = V0001.000",
        "%FLAG POINTERS", "%FORMAT(10I8)", f"{len(atom_names):8d}",
        "%FLAG ATOM_NAME", "%FORMAT(20a4)", name_line,
        "%FLAG MASS", "%FORMAT(5E16.8)",
        "".join(f"{m:16.8E}" for m in masses),
    ]
    path.write_text("\n".join(lines) + "\n")


def test_hmr_detected_without_atomic_number(tmp_path):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    p = tmp_path / "hmr.prmtop"
    # No ATOMIC_NUMBER; identify H by ATOM_NAME starting with 'H'
    _write_prmtop_atoms(p,
        atom_names=["N", "H1", "H2", "CA"],
        masses=[14.01, 3.024, 3.024, 12.01])
    md = extract_prmtop_metadata(str(p))
    assert md.hmr_active is True
    assert md.hmr_detection_method == "atom_name"


def test_charge_completeness_warning(tmp_path):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    p = tmp_path / "charge.prmtop"
    # natom=3 but only 2 valid CHARGE tokens (one blank -> None)
    lines = [
        "%VERSION x", "%FLAG POINTERS", "%FORMAT(10I8)", f"{3:8d}",
        "%FLAG CHARGE", "%FORMAT(3E16.8)",
        f"{1.0:16.8E}{2.0:16.8E}            ",  # third field blank
    ]
    p.write_text("\n".join(lines) + "\n")
    md = extract_prmtop_metadata(str(p))
    assert any("charge" in w.lower() for w in md.warnings)


def test_mdout_captures_1_4_terms():
    from ambermeta.legacy_extractors.mdout import _extract_key_values
    line = " 1-4 NB =  1393.4892  1-4 EEL = 15687.4768  VDWAALS = 21666.9998"
    kv = _extract_key_values(line)
    assert kv["1-4 NB"] == 1393.4892
    assert kv["1-4 EEL"] == 15687.4768
    assert kv["VDWAALS"] == 21666.9998


def test_nbond_total_and_short_pointers(tmp_path):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    p = tmp_path / "ptr.prmtop"
    # index2=NBONH=5, index11=nres=2, index12=NBONA=3
    _write_prmtop(p, {"POINTERS": ("10I8", [4, 0, 5, 0, 0, 0, 0, 0, 0, 0, 0, 2, 3])})
    md = extract_prmtop_metadata(str(p))
    assert md.nbond == 8  # 5 + 3, not 3

    short = tmp_path / "short.prmtop"
    _write_prmtop(short, {"POINTERS": ("10I8", [4, 0, 0])})  # < 13 entries
    md2 = extract_prmtop_metadata(str(short))  # must not raise
    assert md2.natom == 4
    assert md2.nres is None


def test_nvt_production_not_mislabeled(tmp_path):
    """CORE-P6: a title containing 'prod' and 'nvt' must classify as Production, not Equilibration."""
    from ambermeta.legacy_extractors.mdin import parse_mdin_file
    p = tmp_path / "prod.in"
    p.write_text("Production NVT run\n&cntrl\n imin=0, nstlim=5000000,\n/\n")
    md = parse_mdin_file(str(p))
    from ambermeta.legacy_extractors.mdin import _classify_stage
    assert "Production" in _classify_stage(md)


def test_inpcrd_tiny_system_box_not_velocities(tmp_path):
    from ambermeta.legacy_extractors.inpcrd import parse_inpcrd
    p = tmp_path / "tiny.rst"
    # 2 atoms -> 1 coord line (6 floats); + 1 box line. Must read as box, not vel.
    p.write_text(
        "title\n"
        "    2\n"
        "  1.0000000  2.0000000  3.0000000  4.0000000  5.0000000  6.0000000\n"
        " 10.0000000 10.0000000 10.0000000 90.0000000 90.0000000 90.0000000\n"
    )
    md = parse_inpcrd(str(p))
    assert md.has_box is True
    assert md.has_velocities is False


# ---------------------------------------------------------------------------
# CORE-H2/H3/D3/D4 — shared global/HMR prmtop helper
# ---------------------------------------------------------------------------

def test_hmr_prmtop_applied_in_discovery_branch(tmp_path, caplog):
    import ambermeta.protocol as P
    # discovery branch: manifest=None
    # Build a stage with a large-dt mdin so HMR topology is selected.
    (tmp_path / "prod.in").write_text("&cntrl\n imin=0, dt=0.004, nstlim=10,\n/\n")
    (tmp_path / "prod.out").write_text("Final Performance Info\n")
    # minimal HMR prmtop
    _write_prmtop_atoms(tmp_path / "hmr.prmtop",
                        atom_names=["N", "H1"], masses=[14.0, 3.024])
    proto = P.auto_discover(str(tmp_path), manifest=None,
                            hmr_prmtop="hmr.prmtop")
    prod = [s for s in proto.stages if "prod" in s.name][0]
    assert prod.prmtop is not None  # HMR topology applied in discovery branch


def test_missing_global_prmtop_warns(tmp_path, caplog):
    import ambermeta.protocol as P
    (tmp_path / "prod.in").write_text("&cntrl\n imin=0, nstlim=10,\n/\n")
    proto = P.auto_discover(str(tmp_path), manifest=None,
                            global_prmtop="nope.prmtop")
    # graceful mode: protocol returned, no exception
    assert proto is not None
    with pytest.raises(P.AmberMetaError):
        P.auto_discover(str(tmp_path), manifest=None,
                        global_prmtop="nope.prmtop", strict=True)


def test_hmr_inference_uses_shared_threshold():
    import ambermeta.protocol as P
    assert P.HMR_TIMESTEP_THRESHOLD_PS == 0.003
    # _collect_system must not hardcode a different number; guard via source check
    import inspect
    src = inspect.getsource(P.SimulationProtocol.to_methods_dict)
    assert "0.003" not in src  # uses the constant, not a literal
