# ambermeta/mdout_header.py
"""The first ~250 lines of an mdout: what AMBER says about the run before it starts.

Four facts live in the header and nowhere else, and none of them is reachable from the
mdin:

* the **resolved random seed**. Under the common ``ig = -1`` the mdin says only "pick one",
  and the number actually used is echoed here. Whether two replicas were seeded
  differently is the one file-level fact that bears on whether they are distinct runs;
* the **authoritative begin time**. ``t`` in the mdin is a lie under ``irest=1`` — the
  fixtures say ``t = 1000.0`` for a run that began at 920.000 ps — and the first *printed*
  frame is one ``ntpr`` interval later still. Only this line says when the run actually
  started;
* the **resolved CONTROL DATA block** — ``irest``, ``t`` and ``dt`` as AMBER itself settled
  them, defaults filled in. This is what tells the begin-time line above apart from the
  clock origin when ``irest = 0``; see :attr:`MdoutHeader.irest`;
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

# `   2.  CONTROL  DATA  FOR  THE  RUN`, and where that block gives out again (`   3.
# ATOMIC COORDINATES AND VELOCITIES`, or anything else numbered). Scoping matters: the
# header also contains a VERBATIM ECHO of the user's mdin, several dozen lines ABOVE this
# banner, and that echo carries its own `irest = 1,` / `t = 1800.0,` lines. Reading those
# would report what the user typed rather than what AMBER resolved — the echo omits every
# defaulted variable, so a run that never wrote `t` at all would come back with no `t`
# instead of the 0.0 AMBER actually used. Only the block below has the resolved values.
_CONTROL_DATA = re.compile(r"CONTROL\s+DATA\s+FOR\s+THE\s+RUN")
_SECTION = re.compile(r"^\s*\d+\.\s+[A-Z]")

# Every one of these is anchored to the START of its field — line start or the comma that
# ends the previous field — never merely `\b`. AMBER lays the block out as
# `     t       =1800.00000, dt      =   0.00200, vlimit  =  -1.00000`, and a bare `\bt\s*=`
# would be safe there by luck rather than by construction; anchoring says so.
_IREST = re.compile(r"(?:^|,)\s*irest\s*=\s*(-?\d+)")
# `t` and `dt` share a field width AMBER OVERFLOWS: the repo's own back-compat fixtures
# print `t       =**********` from 21000 ps on. `[\d.]` therefore does not match and the
# value comes back None, which is the truthful answer — the same overflow `_BEGIN_TIME`
# already degrades on, for the same reason.
_CONTROL_T = re.compile(r"(?:^|,)\s*t\s*=\s*(-?[\d.]+)")
_CONTROL_DT = re.compile(r"(?:^|,)\s*dt\s*=\s*(-?[\d.]+)")

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
    #: `irest` as AMBER resolved it. **The one field that says whether
    #: :attr:`begin_time_ps` means anything.** Under ``irest = 1`` AMBER takes the clock
    #: from the coordinate file and that line is authoritative. Under ``irest = 0`` it
    #: takes the clock from the mdin's ``t`` and does not read a time from the coordinates
    #: at all — so it prints ``begin time read from input coords = 0.000`` (it read none)
    #: while the trajectory starts at ``t``. On the campaign this was written against that
    #: cost 1800 ps of phantom simulation per replica: five runs stated 3200 ps of dynamics
    #: (``nstlim x dt``), ran from 1800 to 5000 ps, and were counted as 5000 because
    #: ``time_end - 0.0`` looks like an elapsed time and is not one.
    irest: Optional[int] = None
    #: `t` as AMBER resolved it: the clock origin under ``irest = 0``, and a value AMBER
    #: ignores under ``irest = 1`` (the fixtures say ``t = 1000.0`` for a run that began at
    #: 920.0). Never read without checking :attr:`irest` first.
    control_t_ps: Optional[float] = None
    #: `dt` as AMBER resolved it, in ps. Distinct from ``MdoutMetadata.dt``, which defaults
    #: to a TRUTHY 0.001 and so cannot be told apart from an mdout that stated 0.001 —
    #: making every "fall back to the mdin's dt if the mdout had none" guard dead code and
    #: doubling the published `steps` of a 0.002 run whose CONTROL DATA block did not
    #: parse. `None` here means "not stated", unambiguously.
    control_dt_ps: Optional[float] = None

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
    in_control_data = False
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

            if _CONTROL_DATA.search(line):
                in_control_data = True
                continue
            if in_control_data:
                # Any later numbered banner closes the block. `_END` already breaks out at
                # `4. RESULTS`, so in practice this is `3. ATOMIC COORDINATES AND
                # VELOCITIES` — below which sits the begin-time line, which must NOT be
                # read as control data (`input coords =` is not an `irest`/`t`/`dt` field,
                # but relying on that is relying on a near miss).
                if _SECTION.match(line):
                    in_control_data = False
                else:
                    # Deliberately NOT `continue`. The Langevin seed block
                    # (`_SEED_SECTION`) lives INSIDE the CONTROL DATA block, so short-
                    # circuiting here silently stopped `resolved_ig` being read at all —
                    # every replica's seed reported as unknown, which is the one file-level
                    # fact this module exists to establish.
                    _read_control_data(line, header)

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


def _read_control_data(line: str, header: MdoutHeader) -> None:
    """Record `irest`/`t`/`dt` off one line of the CONTROL DATA block.

    First value wins for each field, so a later section that happens to spell one of these
    names cannot overwrite what AMBER printed under `Molecular dynamics:`. Everything stays
    optional: a truncated mdout that never reached this block, or an engine that lays it out
    differently, leaves all three `None`, and every caller treats `None` as "the file did
    not say" rather than as a value.
    """
    if header.irest is None:
        match = _IREST.search(line)
        if match:
            header.irest = int(match.group(1))
    if header.control_t_ps is None:
        header.control_t_ps = _matched_float(_CONTROL_T, line)
    if header.control_dt_ps is None:
        header.control_dt_ps = _matched_float(_CONTROL_DT, line)


def _matched_float(pattern: "re.Pattern", line: str) -> Optional[float]:
    """`pattern`'s first group as a float, or None when it does not match or does not
    convert. `[\\d.]+` admits `.` and `1.2.3` as well as real numbers; a malformed field is
    a field the file did not usefully state, and must degrade to `None` like every other
    absent value here rather than raise out of `read_mdout_header` and cost the caller the
    whole file."""
    match = pattern.search(line)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


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
