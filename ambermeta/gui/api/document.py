# ambermeta/gui/api/document.py
"""Server-authoritative in-memory document with bounded undo/redo.

Pure state machine: no FastAPI, no filesystem, no core engine. Concurrency
safety is provided by the public ``lock`` (a threading.RLock) which callers
hold around read-modify-write sequences.
"""
from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_STAGE_KEYS = ("prmtop", "mdin", "mdout", "mdcrd", "inpcrd")


def _default_settings() -> Dict[str, Any]:
    return {
        "global_prmtop": None,
        "hmr_prmtop": None,
        "initial_coordinates": None,
        "auto_link_restarts": True,
        "strict_validation": True,
        "allow_gaps": False,
        "use_relative_paths": True,
    }


def _blank_stage(stage_id: str) -> Dict[str, Any]:
    return {
        "id": stage_id,
        "name": "",
        "role": "",
        "prmtop": None, "mdin": None, "mdout": None, "mdcrd": None, "inpcrd": None,
        "expected_gap_ps": None,
        "gap_tolerance_ps": None,
        "notes": [],
    }


@dataclass
class Document:
    base_directory: str
    manifest_path: Optional[str] = None
    stages: List[Dict[str, Any]] = field(default_factory=list)
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
        return copy.deepcopy((d.stages, d.settings, d.manifest_path, d.dirty))

    def _restore(self, state: Any) -> None:
        stages, settings, manifest_path, dirty = copy.deepcopy(state)
        self._doc.stages = stages
        self._doc.settings = settings
        self._doc.manifest_path = manifest_path
        self._doc.dirty = dirty

    def _snapshot(self) -> None:
        self._undo.append(self._state())
        if len(self._undo) > self._history_limit:
            self._undo.pop(0)
        self._redo.clear()

    def _find(self, stage_id: str) -> Dict[str, Any]:
        for s in self._doc.stages:
            if s["id"] == stage_id:
                return s
        raise KeyError(stage_id)

    # -- reads --------------------------------------------------------------
    def get(self) -> Document:
        with self.lock:
            return self._doc

    def snapshot(self):
        """Deep-copied point-in-time view (stages, settings, manifest_path, base_directory), taken under the lock."""
        with self.lock:
            d = self._doc
            return copy.deepcopy((d.stages, d.settings, d.manifest_path, d.base_directory))

    def can_undo(self) -> bool:
        with self.lock:
            return bool(self._undo)

    def can_redo(self) -> bool:
        with self.lock:
            return bool(self._redo)

    def to_response(self):  # -> schemas.DocumentResponse
        from .schemas import DocumentResponse, GlobalSettings, StageModel
        with self.lock:
            d = self._doc
            return DocumentResponse(
                base_directory=d.base_directory,
                manifest_path=d.manifest_path,
                dirty=d.dirty,
                can_undo=bool(self._undo),
                can_redo=bool(self._redo),
                settings=GlobalSettings(**d.settings),
                stages=[StageModel(**s) for s in d.stages],
            )

    # -- mutations ----------------------------------------------------------
    def add_stage(self, fields: Dict[str, Any]) -> str:
        with self.lock:
            self._snapshot()
            stage_id = uuid.uuid4().hex[:8]
            stage = _blank_stage(stage_id)
            for k, v in fields.items():
                if k in stage and k != "id":
                    stage[k] = v
            self._doc.stages.append(stage)
            self._doc.dirty = True
            return stage_id

    def update_stage(self, stage_id: str, patch: Dict[str, Any]) -> None:
        with self.lock:
            stage = self._find(stage_id)   # validate first; raises before any state change
            self._snapshot()
            for k, v in patch.items():
                if k in stage and k != "id":
                    stage[k] = v
            self._doc.dirty = True

    def delete_stage(self, stage_id: str) -> None:
        with self.lock:
            stage = self._find(stage_id)   # validate first; raises before any state change
            self._snapshot()
            self._doc.stages.remove(stage)
            self._doc.dirty = True

    def reorder(self, ordered_ids: List[str]) -> None:
        with self.lock:
            current = {s["id"] for s in self._doc.stages}
            if set(ordered_ids) != current or len(ordered_ids) != len(self._doc.stages):
                raise ValueError("reorder id set does not match current stages")
            self._snapshot()
            by_id = {s["id"]: s for s in self._doc.stages}
            self._doc.stages = [by_id[i] for i in ordered_ids]
            self._doc.dirty = True

    def bulk_update(self, stage_ids: List[str], patch: Dict[str, Any]) -> None:
        with self.lock:
            stages = [self._find(sid) for sid in stage_ids]   # validate all ids first
            self._snapshot()
            for stage in stages:
                for k, v in patch.items():
                    if k in stage and k != "id":
                        stage[k] = v
            self._doc.dirty = True

    def patch_settings(self, patch: Dict[str, Any]) -> None:
        with self.lock:
            self._snapshot()
            for k, v in patch.items():
                if k in self._doc.settings:
                    self._doc.settings[k] = v
            self._doc.dirty = True

    def replace(self, *, stages: List[Dict[str, Any]], settings: Dict[str, Any],
                manifest_path: Optional[str], dirty: bool,
                reset_history: bool) -> None:
        with self.lock:
            if reset_history:
                self._undo.clear()
                self._redo.clear()
            else:
                self._snapshot()
            self._doc.stages = copy.deepcopy(stages)
            self._doc.settings = copy.deepcopy(settings)
            self._doc.manifest_path = manifest_path
            self._doc.dirty = dirty

    def mark_saved(self, manifest_path: str) -> None:
        with self.lock:
            self._doc.manifest_path = manifest_path
            self._doc.dirty = False

    def apply_restarts(self, mapping_by_name: Dict[str, str]) -> int:
        with self.lock:
            would_change = any(
                mapping_by_name.get(s["name"]) is not None
                and s.get("inpcrd") != mapping_by_name.get(s["name"])
                for s in self._doc.stages
            )
            if not would_change:
                return 0
            self._snapshot()
            count = 0
            for s in self._doc.stages:
                new = mapping_by_name.get(s["name"])
                if new is not None and s.get("inpcrd") != new:
                    s["inpcrd"] = new
                    count += 1
            if count:
                self._doc.dirty = True
            return count

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
