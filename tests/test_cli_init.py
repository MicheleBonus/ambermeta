from __future__ import annotations


def test_prmtop_substring_not_misclassified(tmp_path):
    """`_scan_directory_files` is still used by `plan --interactive`'s file
    suggestions (`_interactive_manifest`), not by `init` (which no longer
    scans anything)."""
    from ambermeta.cli import _scan_directory_files
    (tmp_path / "gen_prmtop.in").write_text("&cntrl\n/\n")
    files = _scan_directory_files(str(tmp_path))
    assert "gen_prmtop.in" in files["mdin"]
    assert "gen_prmtop.in" not in files["prmtop"]
