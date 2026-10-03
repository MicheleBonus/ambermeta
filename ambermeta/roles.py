# ambermeta/roles.py
from __future__ import annotations

import re
from typing import Any, Optional, Tuple

CANONICAL_ROLES = ("minimization", "heating", "equilibration", "production")

# Word-boundary cues per path component. Directory components are read before the file
# name, and within a component the first pattern that matches wins. A cue starts at the
# start of a component or after one of _ . - and ends at the end of the component, at one
# of _ . -, or at a digit, so `prod1`, `eq0001` and `min_1` carry their cue. Bare
# ambiguous tokens (md, run) are excluded on purpose; content heuristics catch those when
# the parameters are available. Group 1 is the cue word itself; `phase_word` hands back
# the leftmost one, independent of this priority.
#
# The ensemble words `nvt`/`npt` are a weaker cue than production and are checked after
# it: `nvt_prod_0001` is a production run, while `equil_nvt` and `nvt_eq` stay
# equilibration (their `eq` cue is found first) and a bare `npt_02` is still one.
_END = r"(?:[_.\-\d]|$)"
_NAME_CUES = [
    (re.compile(r"(?:^|[_.\-])(minimi[sz]ation|minimi[sz]e|minim|min|em)" + _END), "minimization"),
    (re.compile(r"(?:^|[_.\-])(heat|warm|therm|anneal)(?:ing)?" + _END), "heating"),
    (re.compile(r"(?:^|[_.\-])(equilibration|equilibrate|equil|equi|eq)" + _END), "equilibration"),
    (re.compile(r"(?:^|[_.\-])(production|prod)" + _END), "production"),
    (re.compile(r"(?:^|[_.\-])(nvt|npt)" + _END), "equilibration"),
]


def _name_cue(name: str) -> Tuple[str, str]:
    """The first cue in `name` as (word, role), or ('', '') when it carries none."""
    lowered = name.lower().replace("\\", "/")
    for part in lowered.split("/"):
        for pattern, role in _NAME_CUES:
            match = pattern.search(part)
            if match:
                return match.group(1), role
    return "", ""


def _role_from_name(name: str) -> str:
    return _name_cue(name)[1]


def phase_word(name: str) -> str:
    """The phase word a name carries (`min`, `heat`, `npt`, `prod`), or '' if none: the
    LEFTMOST cue word of the first path component that carries one.

    Finer than the role on purpose: `nvt` and `npt` are both "equilibration", and they
    still name two different stages. The layout inference reads this to tell stage
    directories from replicas (#88), so it is not the role's cue: `nvt_equil/` and
    `npt_equil/` are two stages (`nvt`, `npt`) although both are equilibration by their
    `equil` cue, and `nvt_eq/` beside `npt_eq/` is not a pair of replicas. The role
    priority of `classify_role` (ensemble words after production) would make both `equil`
    and `eq`, and the stages would be read as members.
    """
    lowered = name.lower().replace("\\", "/")
    for part in lowered.split("/"):
        hits = []
        for rank, (pattern, _) in enumerate(_NAME_CUES):
            match = pattern.search(part)
            if match:
                hits.append((match.start(1), rank, match.group(1)))
        if hits:
            return min(hits)[2]
    return ""


def _role_from_content(mdin_details: Any, mdout_details: Any) -> str:
    cntrl = getattr(mdin_details, "cntrl_parameters", None) or {}
    if cntrl.get("ntr") == 1 or cntrl.get("ibelly") == 1:
        return "equilibration"
    tempi = cntrl.get("tempi")
    temp0 = cntrl.get("temp0")
    if isinstance(tempi, (int, float)) and isinstance(temp0, (int, float)):
        if tempi < temp0 and tempi <= 50:
            return "heating"
    nstlim = cntrl.get("nstlim")
    if isinstance(nstlim, (int, float)) and nstlim > 500000:
        return "production"
    return ""


def classify_role(
    name: Optional[str] = None,
    *,
    mdin_details: Any = None,
    mdout_details: Any = None,
) -> str:
    """Return the canonical stage role for a run, or '' if unknown.

    Precedence: (1) authoritative content (imin==1 -> minimization);
    (2) filename/path cues (word-boundary, path-aware);
    (3) other content heuristics (restraints/temperature ramp/length).
    Shared by GUI discover and CLI init so they never diverge.
    """
    cntrl = getattr(mdin_details, "cntrl_parameters", None) or {}
    if cntrl.get("imin") == 1 or getattr(mdout_details, "imin", None) == 1:
        return "minimization"
    if name:
        by_name = _role_from_name(name)
        if by_name:
            return by_name
    return _role_from_content(mdin_details, mdout_details)
