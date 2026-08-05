# ambermeta/mdout_header.py
"""The first ~250 lines of an mdout: what AMBER says about the run before it starts.

Three facts live in the header and nowhere else, and none of them is reachable from the
mdin:

* the **resolved random seed**. Under the common ``ig = -1`` the mdin says only "pick one",
  and the number actually used is echoed here. Whether two replicas were seeded
  differently is the one file-level fact that bears on whether they are distinct runs;
* the **authoritative begin time**. ``t`` in the mdin is a lie under ``irest=1`` — the
  fixtures say ``t = 1000.0`` for a run that began at 920.000 ps — and the first *printed*
  frame is one ``ntpr`` interval later still. Only this line says when the run actually
  started;
* the **File Assignments** block, which is the chain AMBER itself asserts: the INPCRD it
  read and the RESTRT it wrote, rather than an inference from filename adjacency.

Deliberately separate from :func:`ambermeta.legacy_extractors.mdout.parse_mdout`, on two
counts. It stops at the results banner instead of reading the whole file — 0.12 ms against
10.6 ms on the repo's 2553-line fixtures, which is what makes it affordable during a
directory scan. And it returns its own object rather than adding fields to
``MdoutMetadata``: that dataclass is serialised with ``asdict()`` straight into
``summary.json``, so every field added to it appears verbatim in an artifact users keep.

Everything here degrades to ``None``. A header that does not state a seed means the seed is
unknown, never that two runs share one — the difference between a finding and a fabricated
one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

__all__ = ["MdoutHeader", "read_mdout_header"]

# ` begin time read from input coords =   920.000 ps`
_BEGIN_TIME = re.compile(r"begin time read from input coords\s*=\s*(-?[\d.]+)")

# `     ig      =   70038`, and only in that form. The free-text note near the top of the
# file — `Note: ig = -1. Setting random seed to    70038 based on wallclock time in` — is a
# sentence that wraps onto the next line, and a key=value reader applied to it returns -1:
# the value the user asked *not* to use. Recording that as the seed says every run in a
# campaign shares one, which is the false claim this whole feature exists to avoid making.
_IG = re.compile(r"^\s*ig\s*=\s*(-?\d+)")

# The seed block sits under a thermostat-specific header, so it is present for `ntt=3` and
# may be absent or elsewhere for other thermostats, for minimisation, and for engines the
# repo has no fixture of. Absence is reported as absence.
_SEED_SECTION = re.compile(r"temperature regulation:\s*$")
_SEED_WINDOW = 12

# Where the header stops. NOT the `3. ATOMIC COORDINATES` banner: the begin time is four
# lines *below* it, so stopping there would return None on every file. A fixed line budget
# is no good either — the header embeds a verbatim echo of the user's mdin, so its length
# varies with the input.
_END = re.compile(r"^\s*4\.\s+RESULTS|^ NSTEP =")

# The File Assignments prefix is columns 1-10: `|`, the tag right-aligned in 7, then `: `.
_ASSIGNMENT_VALUE_COLUMN = 10


@dataclass
class MdoutHeader:
    """What the header stated. Every field is optional because every field may be absent."""

    file_assignments: Dict[str, str] = field(default_factory=dict)
    #: Tags whose value ran to the end of its field and so may be cut short. AMBER pads the
    #: value to a fixed width, and only a value with no trailing whitespace has been
    #: clipped — the repo's fixtures show 80-char and 87-char lines in one block, so the
    #: width is not a constant to slice at, and a clipped value must not be compared.
    truncated: Set[str] = field(default_factory=set)
    resolved_ig: Optional[int] = None
    begin_time_ps: Optional[float] = None

    def assignment(self, tag: str) -> Optional[str]:
        """The value for `tag`, or None when it is absent **or** was clipped.

        One accessor rather than two lookups, so a caller cannot compare a truncated path
        by accident: `.../cryst/CH3L1_HUMAN` prefix-matches every topology whose name
        starts that way, which is a match that means nothing.
        """
        if tag in self.truncated:
            return None
        return self.file_assignments.get(tag)


def read_mdout_header(path: str) -> MdoutHeader:
    """Read the header of the mdout at `path`, stopping at the results banner."""
    header = MdoutHeader()
    in_assignments = False
    seed_countdown = 0

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n").rstrip("\r")

            if _END.match(line):
                break

            if line.strip() == "File Assignments:":
                in_assignments = True
                continue
            if in_assignments:
                if _read_assignment(line, header):
                    continue
                in_assignments = False

            if header.begin_time_ps is None:
                match = _BEGIN_TIME.search(line)
                if match:
                    header.begin_time_ps = float(match.group(1))
                    continue

            if _SEED_SECTION.search(line):
                seed_countdown = _SEED_WINDOW
                continue
            if seed_countdown:
                seed_countdown -= 1
                match = _IG.match(line)
                if match:
                    value = int(match.group(1))
                    # A resolved seed is what the generator was actually given. A negative
                    # value here would be the request (`-1` = "choose one"), not the
                    # choice, and there is nothing to learn from recording it.
                    if value >= 0:
                        header.resolved_ig = value
                    seed_countdown = 0

    return header


def _read_assignment(line: str, header: MdoutHeader) -> bool:
    """Record one `File Assignments` row. False when `line` is not one, ending the block."""
    if not line.startswith("|"):
        return False
    prefix = line[:_ASSIGNMENT_VALUE_COLUMN]
    if ":" not in prefix:
        return False
    tag = prefix.strip().lstrip("|").strip().rstrip(":").strip()
    if not tag:
        return False
    value_field = line[_ASSIGNMENT_VALUE_COLUMN:]
    value = value_field.strip()
    if not value:
        return True
    header.file_assignments[tag] = value
    # No trailing whitespace means the value filled its field, so it may have been cut off
    # at the width rather than ended. Only PARM is clipped in the repo's fixtures, and only
    # because those particular paths are long.
    if value_field == value_field.rstrip():
        header.truncated.add(tag)
    return True
