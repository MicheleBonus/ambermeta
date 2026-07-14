# ambermeta/simulation.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Topology:
    id: str
    path: str
    kind: str = "normal"          # "normal" | "hmr"


@dataclass
class InputCoords:
    source: str = "starting_structure"   # "starting_structure" | "step" | "path"
    ref: Optional[str] = None             # Step.id when source == "step"
    path: Optional[str] = None            # explicit path when source == "path"


@dataclass
class Step:
    id: str
    name: str
    topology: Optional[str] = None        # Topology.id
    input_coords: InputCoords = field(default_factory=InputCoords)
    mdin: Optional[str] = None
    mdout: Optional[str] = None
    mdcrd: Optional[str] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class Phase:
    id: str
    name: str
    role: str = ""
    steps: List[Step] = field(default_factory=list)


@dataclass
class Simulation:
    version: int = 2
    topologies: List[Topology] = field(default_factory=list)
    starting_structure: Optional[str] = None
    phases: List[Phase] = field(default_factory=list)
