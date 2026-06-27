# tests/test_gui_files.py
import os
import pytest
from ambermeta.gui.api import files
from ambermeta.gui.api.schemas import FileType


def test_resolve_within_base_accepts_inside(tmp_path):
    inside = tmp_path / "sub" / "f.mdin"
    inside.parent.mkdir(parents=True)
    inside.write_text("x", encoding="utf-8")
    assert files.resolve_within_base(str(inside), str(tmp_path)) == os.path.realpath(str(inside))


def test_resolve_within_base_rejects_traversal(tmp_path):
    outside = tmp_path.parent / "secret.txt"
    with pytest.raises(ValueError):
        files.resolve_within_base(str(outside), str(tmp_path))


def test_resolve_within_base_rejects_sibling_prefix(tmp_path):
    # base "/a/base" must not admit sibling "/a/base-evil" (prefix-but-not-subdir)
    sibling = tmp_path.parent / (tmp_path.name + "-evil") / "x.txt"
    with pytest.raises(ValueError):
        files.resolve_within_base(str(sibling), str(tmp_path))


def test_detect_file_type():
    assert files.detect_file_type("a.prmtop") == FileType.PRMTOP
    assert files.detect_file_type("a.mdin") == FileType.MDIN
    assert files.detect_file_type("a.rst7") == FileType.INPCRD
    assert files.detect_file_type("a.txt") == FileType.OTHER
    assert files.detect_file_type("a.mdout") == FileType.MDOUT
    assert files.detect_file_type("a.mdcrd") == FileType.MDCRD


def test_build_file_tree_filters_and_include_all(tmp_path):
    (tmp_path / "min.mdin").write_text("x", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    tree = files.build_file_tree(str(tmp_path), recursive=False, include_all=False)
    names = {f.name for f in tree if not f.is_directory}
    assert "min.mdin" in names and "notes.txt" not in names
    tree_all = files.build_file_tree(str(tmp_path), recursive=False, include_all=True)
    names_all = {f.name for f in tree_all if not f.is_directory}
    assert "notes.txt" in names_all
