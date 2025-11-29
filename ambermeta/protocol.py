from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ambermeta.parsers.inpcrd import InpcrdData, InpcrdParser
from ambermeta.parsers.mdcrd import MdcrdData, MdcrdParser
from ambermeta.parsers.mdin import MdinData, MdinParser
from ambermeta.parsers.mdout import MdoutData, MdoutParser
from ambermeta.parsers.prmtop import PrmtopData, PrmtopParser


@dataclass
class SimulationStage:
    name: str
    prmtop: Optional[PrmtopData] = None
    inpcrd: Optional[InpcrdData] = None
    mdin: Optional[MdinData] = None
    mdout: Optional[MdoutData] = None
    mdcrd: Optional[MdcrdData] = None
    validation: List[str] = field(default_factory=list)

    def validate(self) -> None:
        self.validation.extend(self._validate_atoms())
        self.validation.extend(self._validate_box())
        self.validation.extend(self._validate_timing())
        self.validation.extend(self._validate_sampling())

    def _validate_atoms(self) -> List[str]:
        counts = []
        labels = []
        if self.prmtop and self.prmtop.details and getattr(self.prmtop.details, "natom", None):
            counts.append(self.prmtop.details.natom)
            labels.append("prmtop")
        if self.inpcrd and self.inpcrd.details and getattr(self.inpcrd.details, "natoms", None):
            counts.append(self.inpcrd.details.natoms)
            labels.append("inpcrd")
        if self.mdout and self.mdout.details and getattr(self.mdout.details, "natoms", None):
            counts.append(self.mdout.details.natoms)
            labels.append("mdout")
        if self.mdcrd and self.mdcrd.details and getattr(self.mdcrd.details, "n_atoms", None):
            counts.append(self.mdcrd.details.n_atoms)
            labels.append("mdcrd")

        if not counts:
            return ["No atom counts available for validation."]
        if len(set(counts)) > 1:
            return [f"Atom count mismatch across {labels}: {counts}"]
        return []

    def _validate_box(self) -> List[str]:
        boxes = []
        if self.prmtop and self.prmtop.details and getattr(self.prmtop.details, "box_dimensions", None):
            boxes.append("prmtop")
        if self.inpcrd and self.inpcrd.details and getattr(self.inpcrd.details, "has_box", False):
            boxes.append("inpcrd")
        if self.mdcrd and self.mdcrd.details and getattr(self.mdcrd.details, "has_box", False):
            boxes.append("mdcrd")
        if self.mdout and self.mdout.details and getattr(self.mdout.details, "box_type", None):
            boxes.append("mdout")

        if boxes and len(boxes) < 2:
            return [f"Only {boxes[0]} reports box information; check consistency."]
        return []

    def _validate_timing(self) -> List[str]:
        timing = []
        if self.mdin and self.mdin.details:
            length = getattr(self.mdin.details, "length_steps", None)
            dt = getattr(self.mdin.details, "dt", None)
            if length and dt:
                timing.append(("mdin", length, dt))
        if self.mdout and self.mdout.details:
            length = getattr(self.mdout.details, "nstlim", None)
            dt = getattr(self.mdout.details, "dt", None)
            if length and dt:
                timing.append(("mdout", length, dt))
        if self.mdcrd and self.mdcrd.details:
            dur = getattr(self.mdcrd.details, "total_duration", None)
            if dur:
                timing.append(("mdcrd", "duration_ps", dur))

        notes: List[str] = []
        if len(timing) > 1:
            base = timing[0]
            for label, length, dt in timing[1:]:
                if isinstance(base[1], (int, float)) and isinstance(length, (int, float)) and base[1] != length:
                    notes.append(f"Step count differs between {base[0]} and {label} ({base[1]} vs {length}).")
                if isinstance(base[2], (int, float)) and isinstance(dt, (int, float)) and base[2] != dt:
                    notes.append(f"Timestep differs between {base[0]} and {label} ({base[2]} vs {dt}).")
        return notes

    def _validate_sampling(self) -> List[str]:
        freq = []
        if self.mdin and self.mdin.details:
            freq.append(("mdin", getattr(self.mdin.details, "coord_freq", None)))
        if self.mdout and self.mdout.details:
            freq.append(("mdout", getattr(self.mdout.details, "ntwx", None)))
        notes: List[str] = []
        if len(freq) > 1:
            base = freq[0]
            for label, val in freq[1:]:
                if base[1] and val and base[1] != val:
                    notes.append(f"Coordinate write frequency differs between {base[0]} and {label} ({base[1]} vs {val}).")
        return notes

    def summary(self) -> Dict[str, str]:
        intent = "Unknown"
        result = "Unknown"
        if self.mdin and self.mdin.details:
            intent = getattr(self.mdin.details, "stage_role", "MD Stage")
        if self.mdout and self.mdout.details:
            result = "Completed" if getattr(self.mdout.details, "finished_properly", False) else "Unclear"
        evidence = "; ".join(self.validation or [])
        return {"intent": intent, "result": result, "evidence": evidence}


@dataclass
class SimulationProtocol:
    stages: List[SimulationStage] = field(default_factory=list)

    def validate(self) -> None:
        for stage in self.stages:
            stage.validate()
        self._check_continuity()

    def _check_continuity(self) -> None:
        for prev, current in zip(self.stages, self.stages[1:]):
            if prev.mdcrd and prev.mdcrd.details and current.inpcrd and current.inpcrd.details:
                end_time = getattr(prev.mdcrd.details, "time_end", None)
                start_time = getattr(current.inpcrd.details, "time", None)
                if end_time and start_time and start_time < end_time:
                    current.validation.append("Stage appears to start before previous ended.")

    def totals(self) -> Dict[str, float]:
        total_steps = 0.0
        total_time = 0.0
        for stage in self.stages:
            if stage.mdin and stage.mdin.details:
                length = getattr(stage.mdin.details, "length_steps", 0) or 0
                dt = getattr(stage.mdin.details, "dt", 0) or 0
                if isinstance(length, (int, float)) and isinstance(dt, (int, float)):
                    total_steps += float(length)
                    total_time += float(length) * float(dt)
        return {"steps": total_steps, "time_ps": total_time}


def auto_discover(directory: str) -> SimulationProtocol:
    files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
    grouped: Dict[str, Dict[str, str]] = {}
    ext_map = {
        ".prmtop": "prmtop",
        ".top": "prmtop",
        ".inpcrd": "inpcrd",
        ".rst": "inpcrd",
        ".rst7": "inpcrd",
        ".mdin": "mdin",
        ".in": "mdin",
        ".mdout": "mdout",
        ".out": "mdout",
        ".mdcrd": "mdcrd",
        ".nc": "mdcrd",
    }

    for fname in files:
        stem, ext = os.path.splitext(fname)
        kind = ext_map.get(ext.lower())
        if not kind:
            continue
        grouped.setdefault(stem, {})[kind] = os.path.join(directory, fname)

    stages: List[SimulationStage] = []
    for stem, kinds in sorted(grouped.items()):
        stage = SimulationStage(name=stem)
        if "prmtop" in kinds:
            stage.prmtop = PrmtopParser(kinds["prmtop"]).parse()
        if "inpcrd" in kinds:
            stage.inpcrd = InpcrdParser(kinds["inpcrd"]).parse()
        if "mdin" in kinds:
            stage.mdin = MdinParser(kinds["mdin"]).parse()
        if "mdout" in kinds:
            stage.mdout = MdoutParser(kinds["mdout"]).parse()
        if "mdcrd" in kinds:
            stage.mdcrd = MdcrdParser(kinds["mdcrd"]).parse()
        stage.validate()
        stages.append(stage)

    protocol = SimulationProtocol(stages=stages)
    protocol.validate()
    return protocol


__all__ = ["SimulationProtocol", "SimulationStage", "auto_discover"]
