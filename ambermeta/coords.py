# ambermeta/coords.py
from __future__ import annotations


def sniff_coordinate_kind(path: str) -> str:
    """Decide whether a coordinate file is single-frame input/restart coords
    ('inpcrd') or a multi-frame trajectory ('mdcrd') by content, not extension.

    Amber ASCII restart/inpcrd files carry an atom-count header on line 2
    (``NATOM`` and an optional ``TIME`` float). ASCII trajectories have no such
    header — line 2 is already coordinate data. NetCDF files keep their
    unambiguous extensions (.nc / .ncrst); a NetCDF-magic file here defaults to
    trajectory. Returns 'unknown' if the file cannot be read.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
    except OSError:
        return "unknown"

    if head[:3] == b"CDF" or head == b"\x89HDF":
        return "mdcrd"

    try:
        with open(path, "r", errors="replace") as fh:
            fh.readline()                      # title
            second = fh.readline().split()
    except OSError:
        return "unknown"

    if second and second[0].isdigit() and len(second) <= 2:
        if len(second) == 1:
            return "inpcrd"
        try:
            float(second[1])                   # the optional TIME token
            return "inpcrd"
        except ValueError:
            return "mdcrd"
    return "mdcrd"
