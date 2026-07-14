# ambermeta/gui/api/document.py
"""Server-authoritative in-memory document (Simulation model) with undo/redo.

Pure state machine: no FastAPI, no filesystem, no core engine beyond the
Simulation dataclasses. The public ``lock`` (RLock) guards read-modify-write.
"""
from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ambermeta.simulation import Simulation, Phase, Step, Topology, InputCoords

_STEP_SLOTS = ("mdin", "mdout", "mdcrd")


def _default_settings() -> Dict[str, Any]:
    return {
        "auto_link_restarts": True,
        "strict_validation": True,
        "allow_gaps": False,
        "use_relative_paths": True,
    }


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Document:
    base_directory: str
    manifest_path: Optional[str] = None
    simulation: Simulation = field(default_factory=Simulation)
    settings: Dict[str, Any] = field(default_factory=_default_settings)
    dirty: bool = False


class DocumentStore:
    def __init__(self, base_directory: str, history_limit: int = 100) -> None:
        self.lock = threading.RLock()
        self._history_limit = history_limit
        self.reset(base_directory)

    def reset(self, base_directory: str) -> None:
        with self.lock:
            self._doc = Document(base_directory=base_directory)
            self._undo: List[Any] = []
            self._redo: List[Any] = []

    # -- internal -----------------------------------------------------------
    def _state(self) -> Any:
        d = self._doc
        return copy.deepcopy((d.simulation, d.settings, d.manifest_path, d.dirty))

    def _restore(self, state: Any) -> None:
        sim, settings, manifest_path, dirty = copy.deepcopy(state)
        self._doc.simulation = sim
        self._doc.settings = settings
        self._doc.manifest_path = manifest_path
        self._doc.dirty = dirty

    def _snapshot(self) -> None:
        self._undo.append(self._state())
        if len(self._undo) > self._history_limit:
            self._undo.pop(0)
        self._redo.clear()

    def _find_phase(self, phase_id: str) -> Phase:
        for p in self._doc.simulation.phases:
            if p.id == phase_id:
                return p
        raise KeyError(phase_id)

    def _find_step(self, step_id: str) -> Tuple[Phase, Step]:
        for p in self._doc.simulation.phases:
            for s in p.steps:
                if s.id == step_id:
                    return p, s
        raise KeyError(step_id)

    def _find_topology(self, topology_id: str) -> Topology:
        for t in self._doc.simulation.topologies:
            if t.id == topology_id:
                return t
        raise KeyError(topology_id)

    def _sim_to_model(self):
        from .schemas import (SimulationModel, PhaseModel, StepModel,
                              TopologyModel, InputCoordsModel)
        sim = self._doc.simulation
        return SimulationModel(
            version=sim.version,
            topologies=[TopologyModel(id=t.id, path=t.path, kind=t.kind)
                        for t in sim.topologies],
            starting_structure=sim.starting_structure,
            phases=[PhaseModel(id=p.id, name=p.name, role=(p.role or ""), steps=[
                StepModel(
                    id=s.id, name=s.name, topology=s.topology,
                    input_coords=InputCoordsModel(source=s.input_coords.source,
                                                  ref=s.input_coords.ref,
                                                  path=s.input_coords.path),
                    mdin=s.mdin, mdout=s.mdout, mdcrd=s.mdcrd,
                    expected_gap_ps=s.expected_gap_ps,
                    gap_tolerance_ps=s.gap_tolerance_ps, notes=list(s.notes),
                ) for s in p.steps
            ]) for p in sim.phases],
        )

    # -- reads --------------------------------------------------------------
    def get(self) -> Document:
        with self.lock:
            return self._doc

    def snapshot(self):
        with self.lock:
            d = self._doc
            return copy.deepcopy((d.simulation, d.settings, d.manifest_path, d.base_directory))

    def can_undo(self) -> bool:
        with self.lock:
            return bool(self._undo)

    def can_redo(self) -> bool:
        with self.lock:
            return bool(self._redo)

    def to_response(self):
        from .schemas import DocumentResponse, RuntimeSettings
        with self.lock:
            d = self._doc
            return DocumentResponse(
                base_directory=d.base_directory,
                manifest_path=d.manifest_path,
                dirty=d.dirty,
                can_undo=bool(self._undo),
                can_redo=bool(self._redo),
                settings=RuntimeSettings(**d.settings),
                simulation=self._sim_to_model(),
            )

    # -- document-level mutations -------------------------------------------
    def replace(self, *, simulation: Simulation, settings: Dict[str, Any],
                manifest_path: Optional[str], dirty: bool, reset_history: bool) -> None:
        with self.lock:
            if reset_history:
                self._undo.clear()
                self._redo.clear()
            else:
                self._snapshot()
            self._doc.simulation = copy.deepcopy(simulation)
            self._doc.settings = copy.deepcopy(settings)
            self._doc.manifest_path = manifest_path
            self._doc.dirty = dirty

    def patch_settings(self, patch: Dict[str, Any]) -> None:
        with self.lock:
            self._snapshot()
            for k, v in patch.items():
                if k in self._doc.settings:
                    self._doc.settings[k] = v
            self._doc.dirty = True

    def mark_saved(self, manifest_path: str) -> None:
        with self.lock:
            self._doc.manifest_path = manifest_path
            self._doc.dirty = False

    # -- topology mutations -------------------------------------------------
    def add_topology(self, path: str, kind: str) -> str:
        with self.lock:
            self._snapshot()
            tid = _new_id()
            self._doc.simulation.topologies.append(Topology(id=tid, path=path, kind=kind or "normal"))
            self._doc.dirty = True
            return tid

    def update_topology(self, topology_id: str, patch: Dict[str, Any]) -> None:
        with self.lock:
            t = self._find_topology(topology_id)
            self._snapshot()
            if patch.get("path") is not None:
                t.path = patch["path"]
            if patch.get("kind") is not None:
                t.kind = patch["kind"]
            self._doc.dirty = True

    def remove_topology(self, topology_id: str) -> None:
        with self.lock:
            t = self._find_topology(topology_id)
            self._snapshot()
            self._doc.simulation.topologies.remove(t)
            for p in self._doc.simulation.phases:
                for s in p.steps:
                    if s.topology == topology_id:
                        s.topology = None
            self._doc.dirty = True

    def set_starting_structure(self, path: Optional[str]) -> None:
        with self.lock:
            self._snapshot()
            self._doc.simulation.starting_structure = path or None
            self._doc.dirty = True

    def _topology_id_for_path(self, path: str, kind: Optional[str]) -> str:
        """Return the pool id for ``path``, adding a pool entry if absent.
        Caller must already hold the lock and have snapshotted."""
        for t in self._doc.simulation.topologies:
            if t.path == path:
                return t.id
        tid = _new_id()
        self._doc.simulation.topologies.append(Topology(id=tid, path=path, kind=kind or "normal"))
        return tid

    # -- phase mutations ----------------------------------------------------
    def add_phase(self, name: str, role: str) -> str:
        with self.lock:
            self._snapshot()
            pid = _new_id()
            self._doc.simulation.phases.append(Phase(id=pid, name=name, role=role or ""))
            self._doc.dirty = True
            return pid

    def update_phase(self, phase_id: str, patch: Dict[str, Any]) -> None:
        with self.lock:
            p = self._find_phase(phase_id)
            self._snapshot()
            if patch.get("name") is not None:
                p.name = patch["name"]
            if "role" in patch and patch["role"] is not None:
                p.role = patch["role"]
            self._doc.dirty = True

    def reorder_phases(self, ordered_ids: List[str]) -> None:
        with self.lock:
            phases = self._doc.simulation.phases
            if set(ordered_ids) != {p.id for p in phases} or len(ordered_ids) != len(phases):
                raise ValueError("reorder id set does not match current phases")
            self._snapshot()
            by_id = {p.id: p for p in phases}
            self._doc.simulation.phases = [by_id[i] for i in ordered_ids]
            self._doc.dirty = True

    def delete_phase(self, phase_id: str, reassign_to: Optional[str] = None) -> None:
        with self.lock:
            p = self._find_phase(phase_id)
            target = self._find_phase(reassign_to) if reassign_to is not None else None
            self._snapshot()
            if target is not None:
                target.steps.extend(p.steps)
            self._doc.simulation.phases.remove(p)
            self._doc.dirty = True

    # -- step mutations -----------------------------------------------------
    def add_step(self, phase_id: str, fields: Dict[str, Any]) -> str:
        with self.lock:
            p = self._find_phase(phase_id)
            self._snapshot()
            sid = _new_id()
            ic = fields.get("input_coords") or {}
            step = Step(
                id=sid, name=fields.get("name", ""), topology=fields.get("topology"),
                input_coords=InputCoords(source=ic.get("source", "starting_structure"),
                                         ref=ic.get("ref"), path=ic.get("path")),
                mdin=fields.get("mdin"), mdout=fields.get("mdout"), mdcrd=fields.get("mdcrd"),
                expected_gap_ps=fields.get("expected_gap_ps"),
                gap_tolerance_ps=fields.get("gap_tolerance_ps"),
                notes=list(fields.get("notes") or []),
            )
            p.steps.append(step)
            self._doc.dirty = True
            return sid

    def update_step(self, step_id: str, patch: Dict[str, Any]) -> None:
        with self.lock:
            _, s = self._find_step(step_id)
            self._snapshot()
            if patch.get("name") is not None:
                s.name = patch["name"]
            if "topology" in patch:                 # present => set (None clears)
                s.topology = patch["topology"]
            if patch.get("input_coords") is not None:
                ic = patch["input_coords"]
                s.input_coords = InputCoords(source=ic.get("source", "starting_structure"),
                                             ref=ic.get("ref"), path=ic.get("path"))
            for slot in _STEP_SLOTS:
                if slot in patch:
                    val = patch[slot]
                    setattr(s, slot, val if val else None)   # "" clears
            if patch.get("expected_gap_ps") is not None:
                s.expected_gap_ps = patch["expected_gap_ps"]
            if patch.get("gap_tolerance_ps") is not None:
                s.gap_tolerance_ps = patch["gap_tolerance_ps"]
            if patch.get("notes") is not None:
                s.notes = list(patch["notes"])
            self._doc.dirty = True

    def delete_step(self, step_id: str) -> None:
        with self.lock:
            p, s = self._find_step(step_id)
            self._snapshot()
            p.steps.remove(s)
            self._doc.dirty = True

    def move_step(self, step_id: str, phase_id: str, index: int) -> None:
        with self.lock:
            src, s = self._find_step(step_id)
            dst = self._find_phase(phase_id)
            self._snapshot()
            src.steps.remove(s)
            if index < 0 or index > len(dst.steps):
                dst.steps.append(s)
            else:
                dst.steps.insert(index, s)
            self._doc.dirty = True

    def reorder_steps(self, phase_id: str, ordered_ids: List[str]) -> None:
        with self.lock:
            p = self._find_phase(phase_id)
            if set(ordered_ids) != {s.id for s in p.steps} or len(ordered_ids) != len(p.steps):
                raise ValueError("reorder id set does not match phase steps")
            self._snapshot()
            by_id = {s.id: s for s in p.steps}
            p.steps = [by_id[i] for i in ordered_ids]
            self._doc.dirty = True

    def undo(self) -> None:
        with self.lock:
            if not self._undo:
                return
            self._redo.append(self._state())
            self._restore(self._undo.pop())

    def redo(self) -> None:
        with self.lock:
            if not self._redo:
                return
            self._undo.append(self._state())
            self._restore(self._redo.pop())
