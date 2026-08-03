"""Regression tests for verified bugs (Task 7 of reliability hardening)."""


# --- 7d: inpcrd ASCII box line parses correctly with CRLF line endings ---

def test_inpcrd_ascii_box_parses_with_crlf(tmp_path):
    """Box dimensions must survive CRLF line endings (Windows)."""
    from ambermeta.legacy_extractors.inpcrd import InpcrdMetadata, _parse_ascii_box

    # title, atom count, two coordinate lines, then a box line — all CRLF.
    content = (
        "default_name\r\n"
        "    2\r\n"
        "   1.0000000   2.0000000   3.0000000   4.0000000   5.0000000   6.0000000\r\n"
        "  30.0000000  30.0000000  30.0000000  90.0000000  90.0000000  90.0000000\r\n"
    )
    f = tmp_path / "sys.inpcrd"
    with open(f, "w", newline="") as fh:
        fh.write(content)

    md = InpcrdMetadata(filename=str(f))
    _parse_ascii_box(md)
    assert md.box_dimensions == [30.0, 30.0, 30.0]
    assert md.box_angles == [90.0, 90.0, 90.0]
