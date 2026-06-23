"""Tests for CORE-D2/D7: natural stage ordering and single-digit sequence detection."""
import math

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
