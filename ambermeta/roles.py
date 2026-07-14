# ambermeta/roles.py
from __future__ import annotations

import re
from typing import Any, Optional

CANONICAL_ROLES = ("minimization", "heating", "equilibration", "production")

# Word-boundary cues per path component. First match wins. Separators: start/end
# of a component and any of _ . - . Bare ambiguous tokens (md, run) are excluded
# on purpose; content heuristics catch those when the parameters are available.
_NAME_CUES = [
    (re.compile(r"(?:^|[_.\-])(?:min|minim|em)(?:[_.\-]|$)"), "minimization"),
    (re.compile(r"(?:^|[_.\-])(?:heat|warm|therm|anneal)(?:[_.\-]|$|ing\b)"), "heating"),
    (re.compile(r"(?:^|[_.\-])(?:equil|eq|nvt|npt)(?:[_.\-]|$)"), "equilibration"),
    (re.compile(r"(?:^|[_.\-])(?:prod|production)(?:[_.\-]|$)"), "production"),
]


def _role_from_name(name: str) -> str:
    lowered = name.lower().replace("\\", "/")
    for part in lowered.split("/"):
        for pattern, role in _NAME_CUES:
            if pattern.search(part):
                return role
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
