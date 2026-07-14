# ambermeta/gui/api/files.py
"""Filesystem scanning and path containment for the GUI API."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from .schemas import FileInfo, FileType


def resolve_within_base(path: str, base_directory: str) -> str:
    if not os.path.isabs(path):
        path = os.path.join(base_directory, path)
    resolved = os.path.realpath(path)
    base = os.path.realpath(base_directory)
    if resolved == base or resolved.startswith(base + os.sep):
        return resolved
    raise ValueError("path outside base directory")


def detect_file_type(path: str) -> FileType:
    ext = Path(path).suffix.lower().lstrip(".")
    name = Path(path).name.lower()
    if ext in ("prmtop", "parm7", "top") or name.endswith(".prmtop"):
        return FileType.PRMTOP
    # NOTE: .in/.out are claimed for Amber mdin/mdout by convention; a non-Amber
    # .in/.out would be mis-typed. Accepted trade-off (content sniff is a follow-up).
    if ext in ("mdin", "in") or name.endswith(".mdin"):
        return FileType.MDIN
    if ext in ("mdout", "out") or name.endswith(".mdout"):
        return FileType.MDOUT
    if ext in ("mdcrd", "nc", "crd", "x") or name.endswith(".mdcrd"):
        return FileType.MDCRD
    if ext in ("inpcrd", "rst", "rst7", "restrt", "ncrst") or name.endswith(".inpcrd"):
        return FileType.INPCRD
    # Extensionless canonical Amber default filenames (sander/pmemd defaults).
    if not ext:
        base = Path(path).name.lower()
        if base in ("prmtop", "parm7"):
            return FileType.PRMTOP
        if base == "mdin":
            return FileType.MDIN
        if base == "mdout":
            return FileType.MDOUT
        if base == "mdcrd":
            return FileType.MDCRD
        if base in ("inpcrd", "restrt"):
            return FileType.INPCRD
    return FileType.OTHER


def build_file_tree(directory: str, recursive: bool = True, include_all: bool = False,
                    max_depth: int = 5, _depth: int = 0) -> List[FileInfo]:
    results: List[FileInfo] = []
    try:
        entries = sorted(os.listdir(directory))
    except (PermissionError, OSError):
        return results

    for entry in entries:
        if entry.startswith(".") or entry in ("__pycache__", "node_modules", ".git"):
            continue
        full = os.path.join(directory, entry)
        if os.path.isdir(full):
            children = None
            if recursive and _depth < max_depth:
                children = build_file_tree(full, recursive=recursive,
                                           include_all=include_all, max_depth=max_depth,
                                           _depth=_depth + 1)
            results.append(FileInfo(path=full, name=entry, file_type=FileType.FOLDER,
                                    is_directory=True, parent=directory,
                                    children=children))
        else:
            ftype = detect_file_type(full)
            if ftype == FileType.OTHER and not include_all:
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                size = None
            results.append(FileInfo(path=full, name=entry, file_type=ftype,
                                    is_directory=False, size=size,
                                    extension=Path(full).suffix, parent=directory))
    return results
