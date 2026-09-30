# ambermeta/recorded_inputs.py
"""Whether a run read the coordinates its Step declares.

A document declares each Step's input coordinates, and `discover` fills that declaration
in from file order. The mdout says which file AMBER actually opened: the INPCRD row of its
File Assignments block (see :mod:`ambermeta.mdout_header`). Continuity reads the time
stored in the DECLARED file, so a declaration that names the wrong restart is measured
against the wrong clock and can pass. This module is the comparison between the two.

The recorded value is whatever was typed on the command line where the run executed, so
it is relative to a working directory this machine may not have, or absolute on a machine
this machine is not. Two rules follow:

* where the recorded path resolves to a file here, it is compared as a FILE, so two
  restarts with the same name in different directories are told apart;
* where it does not resolve, only the file NAME can be compared. That is the common case
  for data copied off a cluster, and a different name is still a different file.

A value AMBER clipped at its field width is never passed in here: `MdoutHeader.assignment`
returns None for it, because a clipped path matches nothing reliably.
"""
from __future__ import annotations

import os
from typing import Optional

__all__ = ["compare_recorded_input"]


def _resolve_here(recorded: str, run_directory: str) -> Optional[str]:
    """The local file `recorded` names, read from `run_directory`, or None."""
    candidate = recorded if os.path.isabs(recorded) else os.path.join(run_directory, recorded)
    candidate = os.path.normpath(candidate)
    return candidate if os.path.isfile(candidate) else None


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _display(path: str, run_directory: str) -> str:
    """`path` as the run's directory would spell it: short, and unambiguous beside it."""
    try:
        return os.path.relpath(path, run_directory).replace("\\", "/")
    except ValueError:  # another drive on Windows
        return os.path.basename(path)


def compare_recorded_input(declared_path: str, recorded: str,
                           run_directory: str) -> Optional[str]:
    """None when the run read `declared_path`, else a sentence saying what it read instead.

    `declared_path` is the input the document declares, resolved to this machine.
    `recorded` is the mdout's INPCRD value, unclipped. `run_directory` is where the mdout
    is, the best available stand-in for the directory the run executed in.
    """
    here = _resolve_here(recorded, run_directory)
    if here is not None and os.path.exists(declared_path):
        if _same_file(here, declared_path):
            return None
    else:
        recorded_name = recorded.replace("\\", "/").rstrip("/").rpartition("/")[2]
        if recorded_name == os.path.basename(declared_path):
            return None
    return (f"declares {_display(declared_path, run_directory)} as its input "
            f"coordinates, but its mdout records {recorded}")
