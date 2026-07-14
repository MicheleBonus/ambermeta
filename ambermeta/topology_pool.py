from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata

# Non-HMR SHAKE runs top out at dt = 0.002 ps; anything larger implies HMR.
HMR_MIN_TIMESTEP_PS = 0.002


def implies_hmr(dt) -> bool:
    return isinstance(dt, (int, float)) and dt > HMR_MIN_TIMESTEP_PS


@dataclass
class Topology:
    id: str
    path: str
    kind: str = "normal"          # "normal" | "hmr"
    n_atoms: Optional[int] = None


@dataclass
class TopologyPool:
    topologies: List[Topology] = field(default_factory=list)

    def _by_kind(self, kind: str) -> List[Topology]:
        return [t for t in self.topologies if t.kind == kind]

    def normal(self) -> List[Topology]:
        return self._by_kind("normal")

    def hmr(self) -> List[Topology]:
        return self._by_kind("hmr")

    def distinct_systems(self) -> List[int]:
        return sorted({t.n_atoms for t in self.topologies if t.n_atoms})


def _slug(path: str, idx: int) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    return f"top_{base}" if base else f"top_{idx}"


def classify_topology_pool(directory: str, prmtop_rels: List[str]) -> TopologyPool:
    """Classify every prmtop into a labeled pool entry, keeping all of them.

    Distinct chemical systems (differing atom counts) are preserved — the old
    two-bucket classify_topologies collapsed them into one global prmtop.
    """
    pool = TopologyPool()
    for idx, rel in enumerate(sorted(prmtop_rels)):
        kind, n_atoms = "normal", None
        try:
            md = extract_prmtop_metadata(os.path.join(directory, rel))
            kind = "hmr" if getattr(md, "hmr_active", False) else "normal"
            n_atoms = getattr(md, "n_atoms", None) or getattr(md, "natom", None)
        except (IOError, OSError, ValueError, LookupError):
            pass
        pool.topologies.append(Topology(id=_slug(rel, idx), path=rel, kind=kind, n_atoms=n_atoms))
    return pool
