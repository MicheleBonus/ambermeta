"""Regression tests for verified bugs (Task 7 of reliability hardening)."""

import sys

import pytest

from ambermeta.cli import _toml_escape


# --- 7a: TOML export must escape backslashes (Windows paths) ---

def test_toml_escape_backslashes_and_quotes():
    assert _toml_escape(r"C:\data\file.prmtop") == r"C:\\data\\file.prmtop"
    assert _toml_escape('quote"here') == 'quote\\"here'
    assert _toml_escape(r"C:\a\"b") == r"C:\\a\\\"b"


def test_toml_export_roundtrips_windows_path(tmp_path):
    """A TOML manifest with a Windows path must be re-parseable."""
    tomllib = pytest.importorskip(
        "tomllib" if sys.version_info >= (3, 11) else "tomli"
    )
    from ambermeta.cli import _write_manifest_payload

    payload = {"stages": [{"name": "prod", "prmtop": r"C:\runs\sys.prmtop"}]}
    out = tmp_path / "m.toml"
    _write_manifest_payload(str(out), payload, "toml")
    with open(out, "rb") as fh:
        parsed = tomllib.load(fh)
    assert parsed["stages"][0]["prmtop"] == r"C:\runs\sys.prmtop"


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
