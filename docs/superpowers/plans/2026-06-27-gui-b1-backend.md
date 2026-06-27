# GUI Redesign — B1: Backend & API Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the GUI's triplicated FastAPI backend with a thin, server-authoritative API whose only manifest/validation/discovery engine is the canonical `ambermeta.manifest` + `ambermeta.protocol` core.

**Architecture:** A single in-memory **Document** (stages + settings + bound manifest path + dirty flag) lives behind a `threading.RLock` in a module-level `DocumentStore`. All FastAPI path operations that touch the filesystem or the document are plain `def` (sync) handlers, so Starlette runs them in its worker threadpool — keeping blocking I/O off the event loop while making the lock safe. Routes hold **no** engine logic: every export/open/discover/validate/restart/metadata concern is delegated to a thin `core_bridge` module that calls the A-hardened core. Undo/redo is a bounded snapshot history on the store (covers stages **and** settings).

**Tech Stack:** Python 3.8+, FastAPI, Pydantic v2, `starlette.testclient.TestClient` (needs `httpx`), pytest. No new runtime dependencies beyond `httpx` for the test suite.

## Global Constraints

- **Python floor: 3.8** — no `match`, no `X | Y` runtime unions in evaluated positions (annotations under `from __future__ import annotations` are fine), no `str.removeprefix`. Use `typing.Optional`/`typing.Dict`/`typing.List`.
- **The core is the only engine.** Routes and `core_bridge` MUST call `ambermeta.manifest` / `ambermeta.protocol` / `ambermeta.parsers`. No hand-rolled serializers, validators, sequence detectors, restart heuristics, or role inference may remain in `ambermeta/gui/`.
- **Canonical save payload shape is exactly** `{"global_prmtop"?: str, "hmr_prmtop"?: str, "stages": [ {name, stage_role?, prmtop?, mdin?, mdout?, mdcrd?, inpcrd?, gaps?, notes?}, ... ] }` — no `base_directory`, no `settings` block, no GUI-only `id`. This is what `ambermeta.cli._build_auto_manifest_payload` produces, and what makes GUI save byte-identical to the CLI.
- **Path containment:** every filesystem path accepted from the client (open, save, discover dir, metadata, file list, picker) MUST resolve to within `base_directory`; otherwise raise `HTTPException(status_code=403)`. `base_directory` is fixed at server launch and is never changed by a request.
- **Single user, localhost.** Server-authoritative document + lock. No per-session isolation, no websockets, no auth.
- **Stage file kinds** are exactly `manifest.STAGE_FILE_KINDS == ("prmtop", "mdin", "mdout", "mdcrd", "inpcrd")`. Use that constant; never hardcode the list.
- **Format inference** mirrors `cli._resolve_manifest_format`: explicit format wins; else extension map `{yml→yaml, yaml→yaml, json→json, toml→toml, csv→csv}`; else default `yaml`.
- **Relative paths:** when serializing to a payload, any path located within `base_directory` is written relative to it (`os.path.relpath`); paths outside (or on another drive) are left as-is. This matches CLI `init --auto` output (all discovered paths are relative).

---

## File Structure

**New modules (`ambermeta/gui/api/`):**
- `document.py` — `Document` dataclass + `DocumentStore` (lock, undo/redo snapshots, stage CRUD on dicts, settings patch, dirty tracking). No FastAPI, no FS, no core imports. The pure state machine.
- `core_bridge.py` — the single delegation surface to the core: serialize/save/preview/open, discover + topology split, validation report, file metadata, restart chain, format inference, payload⇄document conversion. The only module in `gui/` that imports `ambermeta.manifest`/`ambermeta.protocol`/`ambermeta.parsers`.
- `files.py` — filesystem scanning (`build_file_tree`, `detect_file_type`) and the path-containment helper (`resolve_within_base`).

**Modified:**
- `ambermeta/gui/api/schemas.py` — add the new request/response models; evolve `GlobalSettings`; keep `FileType`/`StageRole`/`FileInfo`/`StageFiles`.
- `ambermeta/gui/api/routes.py` — gutted of engine logic; thin sync handlers over `DocumentStore` + `core_bridge` + `files`.
- `ambermeta/gui/server.py` — `set_base_directory` now resets the store; CORS unchanged; SPA serving unchanged (A's traversal fix stays).
- `pyproject.toml` — add `httpx` to the `tests` extra (TestClient dependency).

**New tests (`tests/`):**
- `test_gui_document.py` — `DocumentStore` unit tests (undo/redo, dirty, CRUD).
- `test_gui_core_bridge.py` — delegation/serialization/discovery/validation/metadata/restart unit tests.
- `test_gui_files.py` — scan + containment unit tests.
- `test_gui_api.py` — end-to-end `TestClient` tests for every endpoint, incl. byte-identical save parity and validation parity.

---

## Canonical data shapes (referenced by every task)

**GUI stage (`StageModel`, flat — what the frontend sees):**
```
id: str                       # GUI-only stable id (8-char uuid); never written to disk
name: str
role: StageRole               # "" == unknown
prmtop / mdin / mdout / mdcrd / inpcrd: Optional[str]
expected_gap_ps: Optional[float]
gap_tolerance_ps: Optional[float]
notes: List[str]
```

**Canonical payload stage (what `core_bridge.document_to_payload` emits, consumed by `manifest.write_manifest` / `protocol.auto_discover`):**
```
{ "name": str,
  "stage_role": str,          # omitted when ""
  "prmtop"/"mdin"/"mdout"/"mdcrd"/"inpcrd": str,   # each omitted when None
  "gaps": {"expected": float, "tolerance": float}, # omitted when both None
  "notes": [str] }            # omitted when empty
```

**`DocumentResponse` (returned by every state-mutating endpoint):**
```
{ base_directory: str, manifest_path: Optional[str], dirty: bool,
  can_undo: bool, can_redo: bool,
  settings: GlobalSettings, stages: List[StageModel] }
```

---

## Task 1: Document store (state + undo/redo)

**Files:**
- Create: `ambermeta/gui/api/document.py`
- Modify: `ambermeta/gui/api/schemas.py` (add `StageModel`, `DocumentResponse`; evolve `GlobalSettings`)
- Test: `tests/test_gui_document.py`

**Interfaces:**
- Consumes: nothing (pure Python + Pydantic).
- Produces:
  - `schemas.GlobalSettings` (Pydantic) fields: `global_prmtop: Optional[str]=None`, `hmr_prmtop: Optional[str]=None`, `initial_coordinates: Optional[str]=None`, `auto_link_restarts: bool=True`, `strict_validation: bool=True`, `allow_gaps: bool=False`, `use_relative_paths: bool=True`.
  - `schemas.StageModel` (Pydantic, `use_enum_values=True`): `id: str`, `name: str`, `role: StageRole=StageRole.UNKNOWN`, `prmtop/mdin/mdout/mdcrd/inpcrd: Optional[str]=None`, `expected_gap_ps: Optional[float]=None`, `gap_tolerance_ps: Optional[float]=None`, `notes: List[str]=[]`.
  - `schemas.DocumentResponse` (Pydantic): `base_directory: str`, `manifest_path: Optional[str]=None`, `dirty: bool=False`, `can_undo: bool=False`, `can_redo: bool=False`, `settings: GlobalSettings`, `stages: List[StageModel]`.
  - `document.Document` dataclass: `base_directory: str`, `manifest_path: Optional[str]`, `stages: List[Dict[str, Any]]` (each dict is a `StageModel.model_dump()`), `settings: Dict[str, Any]` (a `GlobalSettings.model_dump()`), `dirty: bool`.
  - `document.DocumentStore` with methods (all signatures below are relied on by later tasks):
    - `__init__(self, base_directory: str, history_limit: int = 100)`
    - `lock` (a `threading.RLock`, public attribute)
    - `reset(self, base_directory: str) -> None`
    - `get(self) -> Document`
    - `to_response(self) -> "DocumentResponse"`
    - `add_stage(self, fields: Dict[str, Any]) -> str` — returns new stage id
    - `update_stage(self, stage_id: str, patch: Dict[str, Any]) -> None` — raises `KeyError` if absent
    - `delete_stage(self, stage_id: str) -> None` — raises `KeyError` if absent
    - `reorder(self, ordered_ids: List[str]) -> None` — raises `ValueError` on id-set mismatch
    - `bulk_update(self, stage_ids: List[str], patch: Dict[str, Any]) -> None` — raises `KeyError`
    - `patch_settings(self, patch: Dict[str, Any]) -> None`
    - `replace(self, *, stages: List[Dict[str, Any]], settings: Dict[str, Any], manifest_path: Optional[str], dirty: bool, reset_history: bool) -> None`
    - `mark_saved(self, manifest_path: str) -> None` — sets `manifest_path`, clears `dirty`; does **not** push history
    - `undo(self) -> None`, `redo(self) -> None` — no-op when stack empty
    - `can_undo(self) -> bool`, `can_redo(self) -> bool`

**Design notes for the implementer:**
- Every mutating method (add/update/delete/reorder/bulk/patch_settings/replace) first calls a private `self._snapshot()` that deep-copies `(stages, settings, manifest_path, dirty)` onto `self._undo` (bounded to `history_limit`, dropping oldest), clears `self._redo`, then applies the change and sets `self.dirty = True`. `replace(reset_history=True)` clears both stacks instead of snapshotting (used by Open — a brand-new document).
- `undo()` pushes the current state onto `_redo`, pops `_undo`, restores. `redo()` mirrors it. Snapshots are `copy.deepcopy` of a 4-tuple; restore reassigns all four fields.
- New stage id: `uuid.uuid4().hex[:8]`.
- `to_response()` builds `DocumentResponse(base_directory=..., manifest_path=..., dirty=..., can_undo=self.can_undo(), can_redo=self.can_redo(), settings=GlobalSettings(**doc.settings), stages=[StageModel(**s) for s in doc.stages])`.
- The store does NOT import schemas at module top if it creates a cycle; import inside `to_response()` is acceptable. (schemas.py must not import document.py.)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gui_document.py
from ambermeta.gui.api.document import DocumentStore


def _new() -> DocumentStore:
    return DocumentStore(base_directory="/base")


def test_add_stage_returns_id_and_marks_dirty():
    store = _new()
    assert store.get().dirty is False
    sid = store.add_stage({"name": "min", "role": "minimization"})
    assert isinstance(sid, str) and len(sid) == 8
    doc = store.get()
    assert doc.dirty is True
    assert [s["name"] for s in doc.stages] == ["min"]
    assert doc.stages[0]["id"] == sid


def test_update_and_delete_stage():
    store = _new()
    sid = store.add_stage({"name": "min"})
    store.update_stage(sid, {"name": "minim", "mdin": "min.in"})
    doc = store.get()
    assert doc.stages[0]["name"] == "minim"
    assert doc.stages[0]["mdin"] == "min.in"
    store.delete_stage(sid)
    assert store.get().stages == []


def test_reorder_rejects_mismatched_ids():
    store = _new()
    a = store.add_stage({"name": "a"})
    b = store.add_stage({"name": "b"})
    store.reorder([b, a])
    assert [s["name"] for s in store.get().stages] == ["b", "a"]
    try:
        store.reorder([a])  # missing b
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_undo_redo_covers_stages_and_settings():
    store = _new()
    store.add_stage({"name": "a"})
    store.patch_settings({"global_prmtop": "sys.prmtop"})
    assert store.get().settings["global_prmtop"] == "sys.prmtop"
    assert len(store.get().stages) == 1

    store.undo()  # revert settings patch
    assert store.get().settings["global_prmtop"] is None
    assert len(store.get().stages) == 1

    store.undo()  # revert add_stage
    assert store.get().stages == []

    store.redo()  # re-add stage
    assert len(store.get().stages) == 1
    assert store.can_redo() is True


def test_mark_saved_clears_dirty_without_history():
    store = _new()
    store.add_stage({"name": "a"})
    could_undo_before = store.can_undo()
    store.mark_saved("/base/protocol.yaml")
    doc = store.get()
    assert doc.dirty is False
    assert doc.manifest_path == "/base/protocol.yaml"
    # mark_saved did not add an undo frame
    assert store.can_undo() == could_undo_before


def test_replace_with_reset_history_clears_undo():
    store = _new()
    store.add_stage({"name": "a"})
    store.replace(stages=[{"id": "x", "name": "b", "role": "",
                           "prmtop": None, "mdin": None, "mdout": None,
                           "mdcrd": None, "inpcrd": None,
                           "expected_gap_ps": None, "gap_tolerance_ps": None,
                           "notes": []}],
                  settings={"global_prmtop": None, "hmr_prmtop": None,
                            "initial_coordinates": None, "auto_link_restarts": True,
                            "strict_validation": True, "allow_gaps": False,
                            "use_relative_paths": True},
                  manifest_path="/base/p.yaml", dirty=False, reset_history=True)
    assert store.can_undo() is False
    assert store.get().manifest_path == "/base/p.yaml"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_document.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ambermeta.gui.api.document'`.

- [ ] **Step 3: Evolve `GlobalSettings` and add the new schema models**

In `ambermeta/gui/api/schemas.py`, replace the existing `GlobalSettings` class body with the evolved fields, and add `StageModel` + `DocumentResponse` (place `StageModel` after `StageResponse`, `DocumentResponse` after `ProtocolState`):

```python
class GlobalSettings(BaseModel):
    """Global protocol settings (runtime; only prmtop fields are persisted)."""
    global_prmtop: Optional[str] = None
    hmr_prmtop: Optional[str] = None
    initial_coordinates: Optional[str] = None
    auto_link_restarts: bool = True
    strict_validation: bool = True
    allow_gaps: bool = False
    use_relative_paths: bool = True


class StageModel(BaseModel):
    """A protocol stage as edited in the GUI (flat gap fields)."""
    id: str
    name: str
    role: StageRole = StageRole.UNKNOWN
    prmtop: Optional[str] = None
    mdin: Optional[str] = None
    mdout: Optional[str] = None
    mdcrd: Optional[str] = None
    inpcrd: Optional[str] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: List[str] = Field(default_factory=list)

    class Config:
        use_enum_values = True


class DocumentResponse(BaseModel):
    """The whole server-authoritative document in one payload."""
    base_directory: str
    manifest_path: Optional[str] = None
    dirty: bool = False
    can_undo: bool = False
    can_redo: bool = False
    settings: GlobalSettings = Field(default_factory=GlobalSettings)
    stages: List[StageModel] = Field(default_factory=list)
```

- [ ] **Step 4: Implement `document.py`**

```python
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
            self._snapshot()
            stage = self._find(stage_id)
            for k, v in patch.items():
                if k in stage and k != "id":
                    stage[k] = v
            self._doc.dirty = True

    def delete_stage(self, stage_id: str) -> None:
        with self.lock:
            self._snapshot()
            stage = self._find(stage_id)
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
            self._snapshot()
            for sid in stage_ids:
                stage = self._find(sid)
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_gui_document.py -q`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add ambermeta/gui/api/document.py ambermeta/gui/api/schemas.py tests/test_gui_document.py
git commit -m "feat(gui): server-authoritative Document store with undo/redo (B1 Task 1)"
```

---

## Task 2: core_bridge — serialize / format / save / preview / open

**Files:**
- Create: `ambermeta/gui/api/core_bridge.py`
- Test: `tests/test_gui_core_bridge.py`

**Interfaces:**
- Consumes: `ambermeta.manifest.write_manifest`, `ambermeta.manifest.load_manifest`, `ambermeta.manifest.STAGE_FILE_KINDS`, `ambermeta.manifest.normalize_stage_keys`.
- Produces:
  - `core_bridge.resolve_format(path: Optional[str], explicit: Optional[str]) -> str`
  - `core_bridge.document_to_payload(stages: List[Dict[str, Any]], settings: Dict[str, Any], base_directory: str) -> Dict[str, Any]` — canonical payload (relativizes in-base paths; strips `id`; flat gaps→nested; omits empties).
  - `core_bridge.save_document(stages, settings, base_directory, path: str, fmt: str) -> List[str]` — writes via `write_manifest`; returns warnings (e.g. CSV cannot represent HMR).
  - `core_bridge.preview_document(stages, settings, base_directory, fmt: str) -> Dict[str, Any]` — `{"content": str, "warnings": List[str]}` via `write_manifest` to a temp file then read back.
  - `core_bridge.open_manifest(path: str, base_directory: str) -> Dict[str, Any]` — `{"stages": List[Dict], "settings_patch": Dict}` where stages are GUI `StageModel.model_dump()` dicts and `settings_patch` carries any `global_prmtop`/`hmr_prmtop`/`strict_validation`/`allow_gaps` found.

**Design notes:**
- `document_to_payload`: build top-level `global_prmtop`/`hmr_prmtop` from settings (relativized, omit None). For each stage, emit `{"name": name}`, add `stage_role` only when role truthy, add each kind in `STAGE_FILE_KINDS` only when set (relativized), add `gaps` only when expected or tolerance set (`{"expected":…}`/`{"tolerance":…}` only for the non-None ones), add `notes` only when non-empty. **Never** include `id`, `base_directory`, or `settings`.
- Relativize helper: honors `settings["use_relative_paths"]` (default True). When relative, if `os.path.isabs(p)`, try `rel = os.path.relpath(p, base_directory)`; if `rel` does not start with `..` and is not absolute, use `rel`; else keep `p`. Guard `relpath` with try/except `ValueError` (Windows cross-drive). When `use_relative_paths` is False, absolute paths are written verbatim (the setting is live, not dead).
- `save_document`: warnings — if `fmt == "csv"` and `settings.get("hmr_prmtop")`, append `"CSV format cannot represent a separate HMR topology; hmr_prmtop was folded into each stage's prmtop column."` (mirrors A's CLI behavior). Then `write_manifest(payload, path, fmt)`.
- `preview_document`: write to `tempfile.NamedTemporaryFile(delete=False)` with the right suffix, read text, unlink in a `finally`. Return content + warnings.
- `open_manifest`: `raw = load_manifest(path)`. `raw` is either a list of normalized stage dicts or a dict (`{...globals, "stages":[...]}` or dict-of-stages). Extract globals if dict (`global_prmtop`, fallback `prmtop`; `hmr_prmtop`; optional `settings.strict_validation`/`settings.allow_gaps`). Resolve the stages list (mirror `protocol.load_protocol_from_manifest` lines 1641–1681: `stages` key list, else dict-of-stages → values with name injected). For each stage dict, build a GUI stage dict: assign `uuid.uuid4().hex[:8]` id, map `name`, `stage_role`→`role`, each kind, and `gaps`→flat (`gaps["expected"]`→`expected_gap_ps`, `gaps["tolerance"]`→`gap_tolerance_ps`), `notes`→list (coerce str→[str]). Paths are left exactly as in the manifest (relative or absolute — they resolve against base_directory at validate/metadata time).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gui_core_bridge.py
import os
from ambermeta.gui.api import core_bridge
from ambermeta.manifest import write_manifest, load_manifest


def _stage(**kw):
    base = {"id": "deadbeef", "name": "s", "role": "", "prmtop": None,
            "mdin": None, "mdout": None, "mdcrd": None, "inpcrd": None,
            "expected_gap_ps": None, "gap_tolerance_ps": None, "notes": []}
    base.update(kw)
    return base


def _settings(**kw):
    base = {"global_prmtop": None, "hmr_prmtop": None, "initial_coordinates": None,
            "auto_link_restarts": True, "strict_validation": True,
            "allow_gaps": False, "use_relative_paths": True}
    base.update(kw)
    return base


def test_resolve_format_prefers_explicit_then_extension_then_default():
    assert core_bridge.resolve_format("x.csv", "toml") == "toml"
    assert core_bridge.resolve_format("x.yml", None) == "yaml"
    assert core_bridge.resolve_format("x.json", None) == "json"
    assert core_bridge.resolve_format(None, None) == "yaml"


def test_document_to_payload_omits_empties_and_strips_id(tmp_path):
    stages = [_stage(name="prod_001", role="production", mdin="prod_001.in")]
    payload = core_bridge.document_to_payload(stages, _settings(global_prmtop="sys.prmtop"),
                                              str(tmp_path))
    assert payload["global_prmtop"] == "sys.prmtop"
    assert payload["stages"] == [{"name": "prod_001", "stage_role": "production",
                                  "mdin": "prod_001.in"}]
    assert "id" not in payload["stages"][0]
    assert "hmr_prmtop" not in payload


def test_document_to_payload_keeps_absolute_when_relative_disabled(tmp_path):
    abs_in = str(tmp_path / "prod.in")
    stages = [_stage(name="prod", role="production", mdin=abs_in)]
    payload = core_bridge.document_to_payload(
        stages, _settings(use_relative_paths=False), str(tmp_path))
    assert payload["stages"][0]["mdin"] == abs_in


def test_save_document_byte_identical_to_write_manifest(tmp_path):
    stages = [_stage(name="min", role="minimization", mdin="min.in"),
              _stage(name="prod", role="production", mdin="prod.in",
                     expected_gap_ps=2.0, gap_tolerance_ps=0.5)]
    settings = _settings(global_prmtop="sys.prmtop")
    gui_path = tmp_path / "gui.yaml"
    warnings = core_bridge.save_document(stages, settings, str(tmp_path),
                                         str(gui_path), "yaml")
    assert warnings == []
    # Build the same payload independently and write via the core writer.
    payload = core_bridge.document_to_payload(stages, settings, str(tmp_path))
    ref_path = tmp_path / "ref.yaml"
    write_manifest(payload, str(ref_path), "yaml")
    assert gui_path.read_text(encoding="utf-8") == ref_path.read_text(encoding="utf-8")


def test_save_document_warns_csv_hmr(tmp_path):
    stages = [_stage(name="prod", mdin="prod.in")]
    settings = _settings(global_prmtop="sys.prmtop", hmr_prmtop="sys_hmr.prmtop")
    warnings = core_bridge.save_document(stages, settings, str(tmp_path),
                                         str(tmp_path / "p.csv"), "csv")
    assert any("HMR" in w for w in warnings)


def test_open_manifest_round_trips_globals_and_gaps(tmp_path):
    payload = {"global_prmtop": "sys.prmtop", "hmr_prmtop": "sys_hmr.prmtop",
               "stages": [{"name": "prod", "stage_role": "production",
                           "mdin": "prod.in",
                           "gaps": {"expected": 2.0, "tolerance": 0.5}}]}
    p = tmp_path / "m.yaml"
    write_manifest(payload, str(p), "yaml")
    result = core_bridge.open_manifest(str(p), str(tmp_path))
    assert result["settings_patch"]["global_prmtop"] == "sys.prmtop"
    assert result["settings_patch"]["hmr_prmtop"] == "sys_hmr.prmtop"
    assert len(result["stages"]) == 1
    s = result["stages"][0]
    assert s["name"] == "prod"
    assert s["role"] == "production"
    assert s["mdin"] == "prod.in"
    assert s["expected_gap_ps"] == 2.0
    assert s["gap_tolerance_ps"] == 0.5
    assert len(s["id"]) == 8


def test_preview_matches_save(tmp_path):
    stages = [_stage(name="prod", role="production", mdin="prod.in")]
    settings = _settings(global_prmtop="sys.prmtop")
    preview = core_bridge.preview_document(stages, settings, str(tmp_path), "json")
    saved = tmp_path / "p.json"
    core_bridge.save_document(stages, settings, str(tmp_path), str(saved), "json")
    assert preview["content"] == saved.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_core_bridge.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ambermeta.gui.api.core_bridge'`.

- [ ] **Step 3: Implement the serialize/format/save/preview/open portion of `core_bridge.py`**

```python
# ambermeta/gui/api/core_bridge.py
"""The single delegation surface from the GUI to the AmberMeta core.

Every manifest/validation/discovery/restart/metadata concern routes through
here so the GUI re-implements no engine logic. This module is the only place
in ambermeta/gui that imports ambermeta.manifest / ambermeta.protocol /
ambermeta.parsers.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from typing import Any, Dict, List, Optional

from ambermeta.manifest import (
    STAGE_FILE_KINDS,
    load_manifest,
    write_manifest,
)

_EXT_FORMAT = {"yml": "yaml", "yaml": "yaml", "json": "json", "toml": "toml", "csv": "csv"}


def resolve_format(path: Optional[str], explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    if path:
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        return _EXT_FORMAT.get(ext, "yaml")
    return "yaml"


def _relativize(path: Optional[str], base_directory: str,
                relative: bool = True) -> Optional[str]:
    if not path:
        return path
    if not relative or not os.path.isabs(path):
        return path
    try:
        rel = os.path.relpath(path, base_directory)
    except ValueError:
        return path  # different drive on Windows
    if rel.startswith("..") or os.path.isabs(rel):
        return path
    return rel.replace(os.sep, "/")


def document_to_payload(stages: List[Dict[str, Any]], settings: Dict[str, Any],
                        base_directory: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    relative = settings.get("use_relative_paths", True)
    g = _relativize(settings.get("global_prmtop"), base_directory, relative)
    if g:
        payload["global_prmtop"] = g
    h = _relativize(settings.get("hmr_prmtop"), base_directory, relative)
    if h:
        payload["hmr_prmtop"] = h

    out_stages: List[Dict[str, Any]] = []
    for s in stages:
        entry: Dict[str, Any] = {"name": s.get("name", "")}
        role = s.get("role")
        if role:
            entry["stage_role"] = role
        for kind in STAGE_FILE_KINDS:
            val = _relativize(s.get(kind), base_directory, relative)
            if val:
                entry[kind] = val
        gaps: Dict[str, Any] = {}
        if s.get("expected_gap_ps") is not None:
            gaps["expected"] = s["expected_gap_ps"]
        if s.get("gap_tolerance_ps") is not None:
            gaps["tolerance"] = s["gap_tolerance_ps"]
        if gaps:
            entry["gaps"] = gaps
        notes = s.get("notes") or []
        if notes:
            entry["notes"] = list(notes)
        out_stages.append(entry)
    payload["stages"] = out_stages
    return payload


def _save_warnings(settings: Dict[str, Any], fmt: str) -> List[str]:
    warnings: List[str] = []
    if fmt == "csv" and settings.get("hmr_prmtop"):
        warnings.append(
            "CSV format cannot represent a separate HMR topology; hmr_prmtop "
            "was folded into each stage's prmtop column."
        )
    return warnings


def save_document(stages: List[Dict[str, Any]], settings: Dict[str, Any],
                  base_directory: str, path: str, fmt: str) -> List[str]:
    payload = document_to_payload(stages, settings, base_directory)
    warnings = _save_warnings(settings, fmt)
    write_manifest(payload, path, fmt)
    return warnings


def preview_document(stages: List[Dict[str, Any]], settings: Dict[str, Any],
                     base_directory: str, fmt: str) -> Dict[str, Any]:
    payload = document_to_payload(stages, settings, base_directory)
    warnings = _save_warnings(settings, fmt)
    suffix = "." + ("yaml" if fmt == "yaml" else fmt)
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.close()  # close the handle so write_manifest can write by path (Windows-safe)
    try:
        write_manifest(payload, tmp.name, fmt)
        with open(tmp.name, "r", encoding="utf-8") as fh:
            content = fh.read()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return {"content": content, "warnings": warnings}


def _stages_list_from_raw(raw: Any) -> List[Dict[str, Any]]:
    """Mirror protocol.load_protocol_from_manifest stage-extraction."""
    if isinstance(raw, dict):
        if isinstance(raw.get("stages"), list):
            return [e for e in raw["stages"] if isinstance(e, dict)]
        out: List[Dict[str, Any]] = []
        for name, entry in raw.items():
            if isinstance(entry, dict):
                e = dict(entry)
                e.setdefault("name", name)
                out.append(e)
        return out
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    return []


def _gui_stage_from_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    gaps = entry.get("gaps") or {}
    notes = entry.get("notes")
    if isinstance(notes, str):
        notes = [notes]
    return {
        "id": uuid.uuid4().hex[:8],
        "name": entry.get("name", ""),
        "role": entry.get("stage_role") or "",
        "prmtop": entry.get("prmtop"),
        "mdin": entry.get("mdin"),
        "mdout": entry.get("mdout"),
        "mdcrd": entry.get("mdcrd"),
        "inpcrd": entry.get("inpcrd"),
        "expected_gap_ps": gaps.get("expected") if isinstance(gaps, dict) else None,
        "gap_tolerance_ps": gaps.get("tolerance") if isinstance(gaps, dict) else None,
        "notes": list(notes) if notes else [],
    }


def open_manifest(path: str, base_directory: str) -> Dict[str, Any]:
    raw = load_manifest(path)  # tolerant reader; entries already key-normalized
    settings_patch: Dict[str, Any] = {}
    if isinstance(raw, dict):
        g = raw.get("global_prmtop")
        if g is None:
            g = raw.get("prmtop")  # legacy GUI export compatibility
        if g is not None:
            settings_patch["global_prmtop"] = g
        if raw.get("hmr_prmtop") is not None:
            settings_patch["hmr_prmtop"] = raw["hmr_prmtop"]
        block = raw.get("settings")
        if isinstance(block, dict):
            if "strict_validation" in block:
                settings_patch["strict_validation"] = bool(block["strict_validation"])
            if "allow_gaps" in block:
                settings_patch["allow_gaps"] = bool(block["allow_gaps"])
    stages = [_gui_stage_from_entry(e) for e in _stages_list_from_raw(raw)]
    return {"stages": stages, "settings_patch": settings_patch}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gui_core_bridge.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/core_bridge.py tests/test_gui_core_bridge.py
git commit -m "feat(gui): core_bridge serialize/save/preview/open via canonical manifest (B1 Task 2)"
```

---

## Task 3: core_bridge — discovery + HMR/normal topology split

**Files:**
- Modify: `ambermeta/gui/api/core_bridge.py`
- Test: `tests/test_gui_core_bridge.py` (add to existing file)

**Interfaces:**
- Consumes: `ambermeta.protocol.smart_group_files`, `ambermeta.protocol._ordered_stems`, `ambermeta.protocol.infer_stage_role_from_path`, `ambermeta.legacy_extractors.prmtop.extract_prmtop_metadata`.
- Produces:
  - `core_bridge.classify_topologies(directory: str, prmtops: List[str]) -> Dict[str, Any]` — `{"global_prmtop": Optional[str], "hmr_prmtop": Optional[str], "warnings": List[str]}`. Mirrors `cli._classify_topologies` but returns warnings as data instead of printing.
  - `core_bridge.discover(directory: str, recursive: bool = True, pattern: Optional[str] = None) -> Dict[str, Any]` — `{"stages": List[Dict] (GUI stage dicts), "settings_patch": Dict (global/hmr prmtop), "warnings": List[str]}`. One GUI stage per discovered file group, identical for every role (Bug-1 parity); topology split (Bug-2 parity).

**Design notes:**
- `classify_topologies`: `prmtops = sorted(prmtops)`; for each rel path, `extract_prmtop_metadata(os.path.join(directory, rel))`; `.hmr_active` → hmr list else normal; on `(IOError, OSError, ValueError, LookupError)` treat as normal. `global_prmtop = normal[0] if normal else (prmtops[0] if prmtops else None)`; `hmr_prmtop = hmr[0] if hmr else None`. If `len(prmtops) > 1`, append a warning string `f"{len(prmtops)} topology files found; normal={normal or '-'}, HMR={hmr or '-'}."`.
- `discover`: `grouped = smart_group_files(directory, pattern=pattern, recursive=recursive)`. Collect `prmtops = sorted({v for g in grouped.values() for k, v in g.items() if k == 'prmtop'})` made **relative** to `directory`. Call `classify_topologies(directory, prmtops_rel)`. Build stages: for `stem in _ordered_stems(grouped)`: take only the four non-prmtop kinds (`mdin/mdout/mdcrd/inpcrd`) present, relativized to `directory`; **skip groups with no such files** (prmtop-only groups are not stages — matches `cli._build_stage_candidates`). Role via `infer_stage_role_from_path(stem) or ""`. Build a GUI stage dict (new id, name=stem, role, the file fields, gaps None, notes []). Return stages + `settings_patch={"global_prmtop":…, "hmr_prmtop":…}` (omit keys that are None) + warnings.
- Use `_gui_stage_from_entry`-style construction but here from kinds; create a small local helper or inline. Keep prmtop **out** of per-stage fields (topology is global), matching CLI.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_gui_core_bridge.py
from ambermeta.gui.api import core_bridge as cb


def _touch(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")


def test_discover_one_stage_per_numbered_file(tmp_path):
    # Bug-1 parity: numbered production runs must NOT collapse to the last file.
    for i in (1, 2, 3):
        _touch(tmp_path / f"prod_{i:03d}.mdin")
        _touch(tmp_path / f"prod_{i:03d}.mdout")
    result = cb.discover(str(tmp_path), recursive=False)
    names = sorted(s["name"] for s in result["stages"])
    assert names == ["prod_001", "prod_002", "prod_003"]
    for s in result["stages"]:
        assert s["mdin"] is not None and s["mdout"] is not None
        assert len(s["id"]) == 8


def test_discover_skips_prmtop_only_groups(tmp_path):
    _touch(tmp_path / "system.prmtop")
    _touch(tmp_path / "min.mdin")
    result = cb.discover(str(tmp_path), recursive=False)
    names = [s["name"] for s in result["stages"]]
    assert names == ["min"]  # system.prmtop alone is not a stage
    assert all(s["prmtop"] is None for s in result["stages"])  # topology is global


def test_classify_topologies_warns_on_multiple(tmp_path):
    _touch(tmp_path / "a.prmtop")
    _touch(tmp_path / "b.prmtop")
    out = cb.classify_topologies(str(tmp_path), ["a.prmtop", "b.prmtop"])
    assert out["global_prmtop"] in ("a.prmtop", "b.prmtop")
    assert any("topology files found" in w for w in out["warnings"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_core_bridge.py -k "discover or classify" -q`
Expected: FAIL — `AttributeError: module 'ambermeta.gui.api.core_bridge' has no attribute 'discover'`.

- [ ] **Step 3: Implement discovery in `core_bridge.py`**

Add these imports near the top (with the other core imports) and the functions at the end of the module:

```python
from ambermeta.protocol import (
    _ordered_stems,
    infer_stage_role_from_path,
    smart_group_files,
)
from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata

_NON_TOPOLOGY_KINDS = ("mdin", "mdout", "mdcrd", "inpcrd")


def classify_topologies(directory: str, prmtops: List[str]) -> Dict[str, Any]:
    ordered = sorted(prmtops)
    normal: List[str] = []
    hmr: List[str] = []
    for rel in ordered:
        try:
            md = extract_prmtop_metadata(os.path.join(directory, rel))
            (hmr if md.hmr_active else normal).append(rel)
        except (IOError, OSError, ValueError, LookupError):
            normal.append(rel)
    warnings: List[str] = []
    if len(ordered) > 1:
        warnings.append(
            f"{len(ordered)} topology files found; "
            f"normal={normal or '-'}, HMR={hmr or '-'}."
        )
    global_prmtop = normal[0] if normal else (ordered[0] if ordered else None)
    hmr_prmtop = hmr[0] if hmr else None
    return {"global_prmtop": global_prmtop, "hmr_prmtop": hmr_prmtop,
            "warnings": warnings}


def discover(directory: str, recursive: bool = True,
             pattern: Optional[str] = None) -> Dict[str, Any]:
    grouped = smart_group_files(directory, pattern=pattern, recursive=recursive)

    prmtop_rel = sorted({
        _relativize(v, directory)
        for g in grouped.values()
        for k, v in g.items()
        if k == "prmtop"
    })
    topo = classify_topologies(directory, [p for p in prmtop_rel if p])

    stages: List[Dict[str, Any]] = []
    for stem in _ordered_stems(grouped):
        kinds = grouped[stem]
        files = {k: _relativize(v, directory)
                 for k, v in kinds.items() if k in _NON_TOPOLOGY_KINDS}
        if not files:
            continue  # prmtop-only / metadata-only group is not a stage
        stage = {
            "id": uuid.uuid4().hex[:8],
            "name": stem,
            "role": infer_stage_role_from_path(stem) or "",
            "prmtop": None,
            "mdin": files.get("mdin"),
            "mdout": files.get("mdout"),
            "mdcrd": files.get("mdcrd"),
            "inpcrd": files.get("inpcrd"),
            "expected_gap_ps": None,
            "gap_tolerance_ps": None,
            "notes": [],
        }
        stages.append(stage)

    settings_patch: Dict[str, Any] = {}
    if topo["global_prmtop"]:
        settings_patch["global_prmtop"] = topo["global_prmtop"]
    if topo["hmr_prmtop"]:
        settings_patch["hmr_prmtop"] = topo["hmr_prmtop"]
    return {"stages": stages, "settings_patch": settings_patch,
            "warnings": topo["warnings"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gui_core_bridge.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/core_bridge.py tests/test_gui_core_bridge.py
git commit -m "feat(gui): core_bridge discovery + HMR/normal topology split (B1 Task 3)"
```

---

## Task 4: core_bridge — validation report, file metadata, restart chain

**Files:**
- Modify: `ambermeta/gui/api/core_bridge.py`
- Test: `tests/test_gui_core_bridge.py` (add)

**Interfaces:**
- Consumes: `ambermeta.protocol.auto_discover`, `ambermeta.protocol._serialize_metadata`, `ambermeta.manifest.STAGE_FILE_KINDS`, `ambermeta.parsers.{PrmtopParser, MdinParser, MdoutParser, MdcrdParser, InpcrdParser}`.
- Produces:
  - `core_bridge.build_validation_report(stages, settings, base_directory) -> Dict[str, Any]` — `{ok, totals, protocol_issues, stage_issues}` (see shape below). Built by running `auto_discover` over the document payload (full CLI-parity engine) plus an explicit per-file existence pass.
  - `core_bridge.file_metadata(path: str) -> Dict[str, Any]` — `{"details": {...}|None, "warnings": [str], "kind": str}` via the matching parser's `.details` (fixes the broken endpoint).
  - `core_bridge.restart_chain(stages, settings, base_directory, recursive: bool = False) -> Dict[str, str]` — `{stage_name: relative_inpcrd_path}` via `auto_discover(..., auto_detect_restarts=True)`.

**`build_validation_report` shape:**
```
{ "ok": bool,
  "totals": {"steps": float, "time_ps": float, "stage_count": int},
  "protocol_issues": [str],         # non-INFO cross-stage continuity notes
  "stage_issues": [
    {"name": str, "ok": bool, "degraded": bool,
     "errors": [str], "warnings": [str], "info": [str],
     "missing_files": [{"kind": str, "path": str}]} ] }
```

**Design notes:**
- `build_validation_report`:
  - `payload = document_to_payload(stages, settings, base_directory)`.
  - `protocol = auto_discover(base_directory, manifest=payload["stages"], global_prmtop=payload.get("global_prmtop"), hmr_prmtop=payload.get("hmr_prmtop"), skip_cross_stage_validation=not settings.get("strict_validation", True), allow_unexpected_gaps=settings.get("allow_gaps", False), strict=False)`. `strict=False` ⇒ graceful (missing files become `load_errors`, no raise).
  - For each `stage` in `protocol.stages` (use `stage.to_dict()`): split `validation` list into `info` (starts with `"INFO:"`) and `warnings` (the rest). `errors` = one string per `load_error` (`e["kind"]: e["message"]` or `str(e)`) **plus** explicit missing-file strings. `degraded = stage_dict["degraded"]`.
  - Missing files: independently of the core, for the matching document stage, resolve each set file kind against `base_directory` and check `os.path.exists`; collect `{"kind", "path"}` for missing ones (also resolve `global_prmtop`/`hmr_prmtop` as a synthetic prmtop check per stage when the stage has no own prmtop). Add an error string `f"missing {kind}: {path}"` for each.
  - `ok` per stage = `not errors`. Report `ok` = all stage ok **and** no `protocol_issues` that read as failures. Keep it simple: `ok = all(s["ok"] for s in stage_issues)`.
  - `protocol_issues`: collect, across stages, the `continuity` notes that are non-INFO (these are the gap/overlap/continuity failures). Deduplicate preserving order.
  - `totals`: from `protocol.totals()` plus `stage_count = len(protocol.stages)`.
- `file_metadata`: pick parser by extension using the same kind map the core uses (reuse `detect_file_type` from `files.py` is a cross-task import; to avoid coupling, do a local extension→parser map here). Parse, then `meta = _serialize_metadata(parsed)` → `{"filename", "warnings", "details"}`. Return `{"details": meta["details"], "warnings": meta["warnings"], "kind": kind}`. On parse exception, return `{"details": None, "warnings": [f"Could not parse file: {e}"], "kind": kind}`.
- `restart_chain`: `payload = document_to_payload(...)`; `protocol = auto_discover(base_directory, manifest=payload["stages"], global_prmtop=…, hmr_prmtop=…, auto_detect_restarts=True, recursive=recursive, skip_cross_stage_validation=True, strict=False)`. Return `{s.name: _relativize(s.restart_path, base_directory) for s in protocol.stages if s.restart_path}`.

- [ ] **Step 1: Write the failing tests** (uses the real sample data dir fixture)

```python
# append to tests/test_gui_core_bridge.py
_MDIN = "prod\n&cntrl\n  imin=0, nstlim=1000, dt=0.002, ntb=2,\n/\n"


def test_file_metadata_returns_real_details(tmp_path):
    # mdin is plain text and always parseable — no binary sample file needed.
    mdin = tmp_path / "prod.mdin"
    mdin.write_text(_MDIN, encoding="utf-8")
    out = cb.file_metadata(str(mdin))
    assert out["kind"] == "mdin"
    assert isinstance(out["details"], dict)
    assert "dt" in out["details"]  # real parsed field, not a dataclass-as-dict crash


def test_build_validation_report_flags_missing_file(tmp_path):
    stages = [{"id": "a1", "name": "min", "role": "minimization",
               "prmtop": None, "mdin": "does_not_exist.in", "mdout": None,
               "mdcrd": None, "inpcrd": None, "expected_gap_ps": None,
               "gap_tolerance_ps": None, "notes": []}]
    settings = _settings(strict_validation=True)
    report = cb.build_validation_report(stages, settings, str(tmp_path))
    assert report["ok"] is False
    issue = report["stage_issues"][0]
    assert issue["name"] == "min"
    assert any("does_not_exist.in" in e for e in issue["errors"])
    assert report["totals"]["stage_count"] == 1


def test_build_validation_report_ok_when_no_files(tmp_path):
    # An empty stage with no referenced files has no missing-file errors.
    stages = [{"id": "a1", "name": "s", "role": "", "prmtop": None, "mdin": None,
               "mdout": None, "mdcrd": None, "inpcrd": None, "expected_gap_ps": None,
               "gap_tolerance_ps": None, "notes": []}]
    report = cb.build_validation_report(stages, _settings(), str(tmp_path))
    assert report["stage_issues"][0]["ok"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_core_bridge.py -k "metadata or validation_report" -q`
Expected: FAIL — `AttributeError: ... has no attribute 'file_metadata'`.

- [ ] **Step 3: Implement validation/metadata/restart in `core_bridge.py`**

Add imports and functions:

```python
from ambermeta.protocol import auto_discover, _serialize_metadata
from ambermeta.parsers import (
    PrmtopParser, MdinParser, MdoutParser, MdcrdParser, InpcrdParser,
)

_EXT_KIND = {
    ".prmtop": "prmtop", ".top": "prmtop", ".parm7": "prmtop",
    ".mdin": "mdin", ".in": "mdin",
    ".mdout": "mdout", ".out": "mdout",
    ".mdcrd": "mdcrd", ".nc": "mdcrd", ".crd": "mdcrd", ".x": "mdcrd",
    ".inpcrd": "inpcrd", ".rst": "inpcrd", ".rst7": "inpcrd",
    ".ncrst": "inpcrd", ".restrt": "inpcrd",
}
_KIND_PARSER = {
    "prmtop": PrmtopParser, "mdin": MdinParser, "mdout": MdoutParser,
    "mdcrd": MdcrdParser, "inpcrd": InpcrdParser,
}


def file_metadata(path: str) -> Dict[str, Any]:
    ext = os.path.splitext(path)[1].lower()
    kind = _EXT_KIND.get(ext, "other")
    parser_cls = _KIND_PARSER.get(kind)
    if parser_cls is None:
        return {"details": None, "warnings": ["Unsupported file type"], "kind": kind}
    try:
        parsed = parser_cls(path).parse()
    except Exception as exc:  # parser raises a variety of errors; surface, don't crash
        return {"details": None, "warnings": [f"Could not parse file: {exc}"],
                "kind": kind}
    meta = _serialize_metadata(parsed)
    return {"details": meta["details"], "warnings": meta["warnings"], "kind": kind}


def _resolve(path: Optional[str], base_directory: str) -> Optional[str]:
    if not path:
        return None
    return path if os.path.isabs(path) else os.path.normpath(
        os.path.join(base_directory, path))


def build_validation_report(stages: List[Dict[str, Any]], settings: Dict[str, Any],
                            base_directory: str) -> Dict[str, Any]:
    payload = document_to_payload(stages, settings, base_directory)
    protocol = auto_discover(
        base_directory,
        manifest=payload["stages"],
        global_prmtop=payload.get("global_prmtop"),
        hmr_prmtop=payload.get("hmr_prmtop"),
        skip_cross_stage_validation=not settings.get("strict_validation", True),
        allow_unexpected_gaps=settings.get("allow_gaps", False),
        strict=False,
    )

    # Per-document missing-file pass (resolved against base_directory).
    missing_by_name: Dict[str, List[Dict[str, str]]] = {}
    global_prmtop = settings.get("global_prmtop")
    for s in stages:
        miss: List[Dict[str, str]] = []
        own_prmtop = s.get("prmtop")
        effective_prmtop = own_prmtop or global_prmtop
        checks = []
        if effective_prmtop:
            checks.append(("prmtop", effective_prmtop))
        for kind in ("mdin", "mdout", "mdcrd", "inpcrd"):
            if s.get(kind):
                checks.append((kind, s[kind]))
        for kind, rel in checks:
            full = _resolve(rel, base_directory)
            if full and not os.path.exists(full):
                miss.append({"kind": kind, "path": rel})
        if miss:
            missing_by_name[s.get("name", "")] = miss

    stage_issues: List[Dict[str, Any]] = []
    protocol_issues: List[str] = []
    seen_protocol: set = set()
    for stage in protocol.stages:
        sd = stage.to_dict()
        info = [m for m in sd["validation"] if str(m).startswith("INFO:")]
        warns = [m for m in sd["validation"] if not str(m).startswith("INFO:")]
        errors: List[str] = []
        for le in sd.get("load_errors", []):
            if isinstance(le, dict):
                errors.append(le.get("message") or le.get("kind") or str(le))
            else:
                errors.append(str(le))
        miss = missing_by_name.get(sd["name"], [])
        for m in miss:
            errors.append("missing {kind}: {path}".format(**m))
        for note in sd.get("continuity", []):
            if not str(note).startswith("INFO:") and note not in seen_protocol:
                seen_protocol.add(note)
                protocol_issues.append(note)
        stage_issues.append({
            "name": sd["name"],
            "ok": not errors,
            "degraded": bool(sd.get("degraded")),
            "errors": errors,
            "warnings": warns,
            "info": info,
            "missing_files": miss,
        })

    totals = protocol.totals()
    totals["stage_count"] = len(protocol.stages)
    return {
        "ok": all(s["ok"] for s in stage_issues),
        "totals": totals,
        "protocol_issues": protocol_issues,
        "stage_issues": stage_issues,
    }


def restart_chain(stages: List[Dict[str, Any]], settings: Dict[str, Any],
                  base_directory: str, recursive: bool = False) -> Dict[str, str]:
    payload = document_to_payload(stages, settings, base_directory)
    protocol = auto_discover(
        base_directory,
        manifest=payload["stages"],
        global_prmtop=payload.get("global_prmtop"),
        hmr_prmtop=payload.get("hmr_prmtop"),
        auto_detect_restarts=True,
        recursive=recursive,
        skip_cross_stage_validation=True,
        strict=False,
    )
    out: Dict[str, str] = {}
    for s in protocol.stages:
        if s.restart_path:
            rel = _relativize(s.restart_path, base_directory)
            if rel:
                out[s.name] = rel
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gui_core_bridge.py -q`
Expected: PASS (all core_bridge tests).

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/core_bridge.py tests/test_gui_core_bridge.py
git commit -m "feat(gui): core_bridge validation report, metadata, restart chain (B1 Task 4)"
```

---

## Task 5: files.py — file tree, type detection, path containment

**Files:**
- Create: `ambermeta/gui/api/files.py`
- Test: `tests/test_gui_files.py`

**Interfaces:**
- Consumes: `schemas.FileInfo`, `schemas.FileType`.
- Produces:
  - `files.resolve_within_base(path: str, base_directory: str) -> str` — returns the realpath if within base; raises `ValueError` otherwise. (Routes translate `ValueError`→HTTP 403.)
  - `files.detect_file_type(path: str) -> "FileType"` — extension/name → `FileType` (moved verbatim from `routes._get_file_type`).
  - `files.build_file_tree(directory: str, recursive: bool = True, include_all: bool = False, max_depth: int = 5) -> List["FileInfo"]` — ported from `routes._scan_directory`; when `include_all` is True, non-simulation files are included with `file_type=FileType.OTHER` (so any path is pickable).

**Design notes:**
- `resolve_within_base`: `resolved = os.path.realpath(path)`, `base = os.path.realpath(base_directory)`; ok if `resolved == base` or `resolved.startswith(base + os.sep)`; else `raise ValueError("path outside base directory")`.
- `build_file_tree`: same structure as `_scan_directory` but add the `include_all` branch: when a file's type is `OTHER` and `include_all`, still append a `FileInfo`. Keep skipping hidden files and `__pycache__`/`node_modules`/`.git`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gui_files.py
import os
import pytest
from ambermeta.gui.api import files
from ambermeta.gui.api.schemas import FileType


def test_resolve_within_base_accepts_inside(tmp_path):
    inside = tmp_path / "sub" / "f.mdin"
    inside.parent.mkdir(parents=True)
    inside.write_text("x", encoding="utf-8")
    assert files.resolve_within_base(str(inside), str(tmp_path)) == os.path.realpath(str(inside))


def test_resolve_within_base_rejects_traversal(tmp_path):
    outside = tmp_path.parent / "secret.txt"
    with pytest.raises(ValueError):
        files.resolve_within_base(str(outside), str(tmp_path))


def test_detect_file_type():
    assert files.detect_file_type("a.prmtop") == FileType.PRMTOP
    assert files.detect_file_type("a.mdin") == FileType.MDIN
    assert files.detect_file_type("a.rst7") == FileType.INPCRD
    assert files.detect_file_type("a.txt") == FileType.OTHER


def test_build_file_tree_filters_and_include_all(tmp_path):
    (tmp_path / "min.mdin").write_text("x", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    tree = files.build_file_tree(str(tmp_path), recursive=False, include_all=False)
    names = {f.name for f in tree if not f.is_directory}
    assert "min.mdin" in names and "notes.txt" not in names
    tree_all = files.build_file_tree(str(tmp_path), recursive=False, include_all=True)
    names_all = {f.name for f in tree_all if not f.is_directory}
    assert "notes.txt" in names_all
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_files.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ambermeta.gui.api.files'`.

- [ ] **Step 3: Implement `files.py`**

```python
# ambermeta/gui/api/files.py
"""Filesystem scanning and path containment for the GUI API."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from .schemas import FileInfo, FileType


def resolve_within_base(path: str, base_directory: str) -> str:
    resolved = os.path.realpath(path)
    base = os.path.realpath(base_directory)
    if resolved == base or resolved.startswith(base + os.sep):
        return resolved
    raise ValueError("path outside base directory")


def detect_file_type(path: str) -> FileType:
    ext = Path(path).suffix.lower().lstrip(".")
    name = Path(path).name.lower()
    if ext in ("prmtop", "parm7", "top") or name.endswith(".prmtop"):
        return FileType.PRMTOP
    if ext in ("mdin", "in") or name.endswith(".mdin"):
        return FileType.MDIN
    if ext in ("mdout", "out") or name.endswith(".mdout"):
        return FileType.MDOUT
    if ext in ("mdcrd", "nc", "netcdf", "crd", "trj") or name.endswith(".mdcrd"):
        return FileType.MDCRD
    if ext in ("inpcrd", "rst", "rst7", "restrt", "ncrst") or name.endswith(".inpcrd"):
        return FileType.INPCRD
    return FileType.OTHER


def build_file_tree(directory: str, recursive: bool = True, include_all: bool = False,
                    max_depth: int = 5, _depth: int = 0) -> List[FileInfo]:
    results: List[FileInfo] = []
    try:
        entries = sorted(os.listdir(directory))
    except (PermissionError, OSError):
        return results

    for entry in entries:
        if entry.startswith(".") or entry in ("__pycache__", "node_modules", ".git"):
            continue
        full = os.path.join(directory, entry)
        if os.path.isdir(full):
            children = None
            if recursive and _depth < max_depth:
                children = build_file_tree(full, recursive=recursive,
                                           include_all=include_all, max_depth=max_depth,
                                           _depth=_depth + 1)
            results.append(FileInfo(path=full, name=entry, file_type=FileType.FOLDER,
                                    is_directory=True, parent=directory,
                                    children=children))
        else:
            ftype = detect_file_type(full)
            if ftype == FileType.OTHER and not include_all:
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                size = None
            results.append(FileInfo(path=full, name=entry, file_type=ftype,
                                    is_directory=False, size=size,
                                    extension=Path(full).suffix, parent=directory))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gui_files.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/files.py tests/test_gui_files.py
git commit -m "feat(gui): files module — tree scan, type detection, path containment (B1 Task 5)"
```

---

## Task 6: routes — document lifecycle endpoints + store wiring

**Files:**
- Modify: `ambermeta/gui/api/routes.py` (begin the rewrite: replace module state + add lifecycle routes)
- Modify: `ambermeta/gui/api/schemas.py` (add `OpenRequest`, `SaveRequest`, `SaveResult`, `DiscoverRequest`, `PreviewRequest`, `PreviewResponse`)
- Modify: `ambermeta/gui/server.py` (`set_base_directory` resets the store)
- Modify: `pyproject.toml` (add `httpx` to the `tests` extra)
- Test: `tests/test_gui_api.py`

**Interfaces:**
- Consumes: `document.DocumentStore`, all `core_bridge.*`, `files.resolve_within_base`.
- Produces (new schemas):
  - `OpenRequest`: `path: str`
  - `SaveRequest`: `path: Optional[str]=None`, `format: Optional[str]=None`
  - `SaveResult`: `document: DocumentResponse`, `warnings: List[str]=[]`
  - `DiscoverRequest`: `recursive: bool=True`, `pattern: Optional[str]=None`
  - `PreviewRequest`: `format: str="yaml"`
  - `PreviewResponse`: `content: str`, `warnings: List[str]=[]`, `format: str`
- Produces (routes module): `routes._store: DocumentStore`, `routes.set_base_directory(directory: str) -> None`, `routes.get_store() -> DocumentStore`.

**Design notes:**
- **All handlers in the rewritten `routes.py` are `def` (sync), not `async def`** — Starlette runs them in its threadpool, keeping blocking FS/core work off the event loop and making the `RLock` safe. (This is the project's "threadpool offloading" mechanism; do not reintroduce `async def` for FS/core handlers.)
- Module state: replace `_protocol_state`/`_base_directory` with a single `_store: Optional[DocumentStore] = None`. `set_base_directory(directory)` sets `_store = DocumentStore(os.path.abspath(directory))` (or `_store.reset(...)` if already created). `get_store()` lazily creates with cwd if unset.
- Each lifecycle handler acquires `store.lock` only inside the store methods (they self-lock); the route reads `doc = store.get()` to snapshot the current `stages`/`settings`/`base_directory` for passing to `core_bridge`, then applies results via store methods. Because the store's RLock is re-entrant and held briefly, tab races can't interleave.
- Containment: `open`/`save`/`discover`/`preview` paths and dirs validated via `files.resolve_within_base(...)`, translating `ValueError`→`HTTPException(403)`.
- `open`: validate path within base + exists; `result = core_bridge.open_manifest(resolved, base)`; merge `settings_patch` onto a default settings dict; `store.replace(stages=result["stages"], settings=merged_settings, manifest_path=resolved, dirty=False, reset_history=True)`; return `store.to_response()`. On `(FileNotFoundError, ValueError, TypeError, ImportError)` from the reader → `HTTPException(400, detail=...)` (clean 4xx, not 500).
- `save`: determine target path = `req.path` (validated within base) or `doc.manifest_path`; if neither → `HTTPException(400, "no path to save to")`. `fmt = core_bridge.resolve_format(target, req.format)`. `warnings = core_bridge.save_document(doc.stages, doc.settings, doc.base_directory, target, fmt)`. `store.mark_saved(target)`. Return `SaveResult(document=store.to_response(), warnings=warnings)`.
- `preview`: `out = core_bridge.preview_document(doc.stages, doc.settings, doc.base_directory, req.format)`; return `PreviewResponse(content=out["content"], warnings=out["warnings"], format=req.format)`.
- `discover`: validate base dir; `result = core_bridge.discover(base, recursive=req.recursive, pattern=req.pattern)`; merge `settings_patch` into current settings (copy then update); `store.replace(stages=result["stages"], settings=merged, manifest_path=doc.manifest_path, dirty=True, reset_history=False)`. Return `store.to_response()`. (Discovery warnings: include via response? Keep on response by returning a `DiscoverResult`? To stay minimal, log discovery warnings into the first stage's notes is wrong; instead return `DocumentResponse` and surface warnings through a response header is overkill. **Decision:** discover returns `store.to_response()`; warnings are recomputed and surfaced by the subsequent `/validate` call and by topology being visible in settings. Keep discover response as `DocumentResponse`.)
- `GET /document`: return `store.to_response()`.

- [ ] **Step 1: Write the failing tests** (TestClient against a real temp dir)

```python
# tests/test_gui_api.py
import json
import pytest

from ambermeta.gui.server import create_app
from ambermeta.manifest import write_manifest


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient
    app = create_app(str(tmp_path))
    return TestClient(app), tmp_path


def test_get_document_initial_empty(client):
    c, base = client
    r = c.get("/api/document")
    assert r.status_code == 200
    body = r.json()
    assert body["stages"] == []
    assert body["dirty"] is False
    assert body["manifest_path"] is None


def test_open_then_get_document(client):
    c, base = client
    payload = {"global_prmtop": "sys.prmtop",
               "stages": [{"name": "prod", "stage_role": "production",
                           "mdin": "prod.in"}]}
    mpath = base / "protocol.yaml"
    write_manifest(payload, str(mpath), "yaml")
    r = c.post("/api/document/open", json={"path": str(mpath)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"]["global_prmtop"] == "sys.prmtop"
    assert [s["name"] for s in body["stages"]] == ["prod"]
    assert body["manifest_path"] == __import__("os").path.realpath(str(mpath))


def test_open_bad_path_is_4xx_not_500(client):
    c, base = client
    r = c.post("/api/document/open", json={"path": str(base / "missing.yaml")})
    assert r.status_code in (400, 404)


def test_open_outside_base_is_403(client):
    c, base = client
    r = c.post("/api/document/open", json={"path": str(base.parent / "evil.yaml")})
    assert r.status_code == 403


def test_save_is_byte_identical_to_write_manifest(client):
    c, base = client
    # open a known manifest, then save it back out
    payload = {"global_prmtop": "sys.prmtop",
               "stages": [{"name": "min", "stage_role": "minimization",
                           "mdin": "min.in"},
                          {"name": "prod", "stage_role": "production",
                           "mdin": "prod.in"}]}
    src = base / "src.yaml"
    write_manifest(payload, str(src), "yaml")
    c.post("/api/document/open", json={"path": str(src)})
    out = base / "out.yaml"
    r = c.post("/api/document/save", json={"path": str(out), "format": "yaml"})
    assert r.status_code == 200, r.text
    assert r.json()["document"]["dirty"] is False
    # Independently regenerate the reference via the core writer.
    ref = base / "ref.yaml"
    write_manifest(payload, str(ref), "yaml")
    assert out.read_text(encoding="utf-8") == ref.read_text(encoding="utf-8")


def test_discover_populates_stages(client):
    c, base = client
    for i in (1, 2):
        (base / f"prod_{i:03d}.mdin").write_text("x", encoding="utf-8")
        (base / f"prod_{i:03d}.mdout").write_text("x", encoding="utf-8")
    r = c.post("/api/document/discover", json={"recursive": False})
    assert r.status_code == 200, r.text
    names = sorted(s["name"] for s in r.json()["stages"])
    assert names == ["prod_001", "prod_002"]
    assert r.json()["dirty"] is True


def test_preview_matches_core_writer(client):
    c, base = client
    payload = {"stages": [{"name": "prod", "stage_role": "production"}]}
    src = base / "src.json"
    write_manifest(payload, str(src), "json")
    c.post("/api/document/open", json={"path": str(src)})
    r = c.post("/api/document/preview", json={"format": "json"})
    assert r.status_code == 200
    ref = base / "ref.json"
    write_manifest(payload, str(ref), "json")
    assert r.json()["content"] == ref.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_api.py -q`
Expected: FAIL — endpoints 404 / `set_base_directory` store wiring absent (current routes return old shapes / lack `/document`).

- [ ] **Step 3: Add the lifecycle request/response schemas**

In `ambermeta/gui/api/schemas.py`, add after `DocumentResponse`:

```python
class OpenRequest(BaseModel):
    path: str


class SaveRequest(BaseModel):
    path: Optional[str] = None
    format: Optional[str] = None


class SaveResult(BaseModel):
    document: DocumentResponse
    warnings: List[str] = Field(default_factory=list)


class DiscoverRequest(BaseModel):
    recursive: bool = True
    pattern: Optional[str] = None


class PreviewRequest(BaseModel):
    format: str = "yaml"


class PreviewResponse(BaseModel):
    content: str
    warnings: List[str] = Field(default_factory=list)
    format: str
```

- [ ] **Step 4: Begin the routes rewrite — store wiring + lifecycle handlers**

Replace the top of `ambermeta/gui/api/routes.py` (imports + module state + `get_state`/`set_base_directory` + `_validate_path_within_base`) with the following, and **delete** the old `get_state`, `_protocol_state`, `_base_directory`, and `_validate_path_within_base`. Keep the file-type / scan / sequence / validate helpers for now (Tasks 7–9 remove the dead ones). Add the lifecycle routes immediately after the router definition.

```python
"""FastAPI routes for the AmberMeta GUI API (server-authoritative document)."""
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from . import core_bridge, files
from .document import DocumentStore
from .schemas import (
    DocumentResponse, OpenRequest, SaveRequest, SaveResult,
    DiscoverRequest, PreviewRequest, PreviewResponse,
)

router = APIRouter()

_store: Optional[DocumentStore] = None


def set_base_directory(directory: str) -> None:
    global _store
    absolute = os.path.abspath(directory)
    if _store is None:
        _store = DocumentStore(absolute)
    else:
        _store.reset(absolute)


def get_store() -> DocumentStore:
    global _store
    if _store is None:
        _store = DocumentStore(os.path.abspath("."))
    return _store


def _within_base(path: str, base: str) -> str:
    try:
        return files.resolve_within_base(path, base)
    except ValueError:
        raise HTTPException(status_code=403,
                            detail="Access denied: path outside base directory")


@router.get("/document", response_model=DocumentResponse)
def get_document() -> DocumentResponse:
    return get_store().to_response()


@router.post("/document/open", response_model=DocumentResponse)
def open_document(req: OpenRequest) -> DocumentResponse:
    store = get_store()
    doc = store.get()
    resolved = _within_base(req.path, doc.base_directory)
    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail=f"Manifest not found: {req.path}")
    try:
        result = core_bridge.open_manifest(resolved, doc.base_directory)
    except (FileNotFoundError, ValueError, TypeError, ImportError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read manifest: {exc}")
    merged = dict(doc.settings)
    merged.update(result["settings_patch"])
    store.replace(stages=result["stages"], settings=merged,
                  manifest_path=resolved, dirty=False, reset_history=True)
    return store.to_response()


@router.post("/document/save", response_model=SaveResult)
def save_document(req: SaveRequest) -> SaveResult:
    store = get_store()
    doc = store.get()
    target = req.path
    if target:
        target = _within_base(target, doc.base_directory)
    else:
        target = doc.manifest_path
    if not target:
        raise HTTPException(status_code=400, detail="No path to save to (provide 'path').")
    fmt = core_bridge.resolve_format(target, req.format)
    try:
        warnings = core_bridge.save_document(doc.stages, doc.settings,
                                             doc.base_directory, target, fmt)
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not save manifest: {exc}")
    store.mark_saved(target)
    return SaveResult(document=store.to_response(), warnings=warnings)


@router.post("/document/preview", response_model=PreviewResponse)
def preview_document(req: PreviewRequest) -> PreviewResponse:
    store = get_store()
    doc = store.get()
    try:
        out = core_bridge.preview_document(doc.stages, doc.settings,
                                           doc.base_directory, req.format)
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not render preview: {exc}")
    return PreviewResponse(content=out["content"], warnings=out["warnings"],
                           format=req.format)


@router.post("/document/discover", response_model=DocumentResponse)
def discover_document(req: DiscoverRequest) -> DocumentResponse:
    store = get_store()
    doc = store.get()
    _within_base(doc.base_directory, doc.base_directory)
    result = core_bridge.discover(doc.base_directory, recursive=req.recursive,
                                  pattern=req.pattern)
    merged = dict(doc.settings)
    merged.update(result["settings_patch"])
    store.replace(stages=result["stages"], settings=merged,
                  manifest_path=doc.manifest_path, dirty=True, reset_history=False)
    return store.to_response()
```

The remaining legacy handlers (stages, settings, validate, files, session, etc.) stay in the file below this point untouched in this task; they will be replaced/removed in Tasks 7–9. They still reference the deleted `get_state`/`_validate_path_within_base`, so to keep the suite importable, **comment out or delete** the legacy `@router` blocks that reference them now and reintroduce the real ones in Tasks 7–8. Simplest: delete every legacy `@router` route and its helper functions except the lifecycle routes above; Tasks 7–8 add the rest. (If you prefer smaller diffs, Task 9 does the final purge; but the module must import cleanly — so remove anything referencing `get_state`/`_validate_path_within_base` now.)

- [ ] **Step 5: Wire the store reset in `server.py`**

`server.py` already calls `from .api.routes import router, set_base_directory` and `set_base_directory(directory)` inside `create_app`. No change needed beyond confirming the import still resolves. Verify `create_app` imports succeed:

Run: `python -c "from ambermeta.gui.server import create_app; create_app('.')"`
Expected: no error (prints nothing).

- [ ] **Step 6: Add `httpx` to the tests extra in `pyproject.toml`**

In `pyproject.toml`, change the `tests` extra:

```toml
tests = [
    "pytest>=7",
    "pytest-cov>=4.0",
    "httpx>=0.24",
]
```

- [ ] **Step 7: Run lifecycle tests**

Run: `python -m pytest tests/test_gui_api.py -q`
Expected: PASS (8 tests). If `TestClient` import fails, confirm `httpx` is installed in the env (`python -c "import httpx"`).

- [ ] **Step 8: Commit**

```bash
git add ambermeta/gui/api/routes.py ambermeta/gui/api/schemas.py ambermeta/gui/server.py pyproject.toml tests/test_gui_api.py
git commit -m "feat(gui): document lifecycle endpoints (get/open/save/preview/discover) over store (B1 Task 6)"
```

---

## Task 7: routes — stage CRUD, reorder, bulk, settings, undo/redo

**Files:**
- Modify: `ambermeta/gui/api/routes.py` (add these routes)
- Modify: `ambermeta/gui/api/schemas.py` (add `SettingsPatch`; reuse `StageCreate`/`StageUpdate`/`StageReorderRequest`/`BulkStageUpdate`)
- Test: `tests/test_gui_api.py` (add)

**Interfaces:**
- Consumes: `DocumentStore` mutation methods, `DocumentResponse`.
- Produces (schema): `SettingsPatch` — all `GlobalSettings` fields but every one `Optional` (a partial patch):
  ```python
  class SettingsPatch(BaseModel):
      global_prmtop: Optional[str] = None
      hmr_prmtop: Optional[str] = None
      initial_coordinates: Optional[str] = None
      auto_link_restarts: Optional[bool] = None
      strict_validation: Optional[bool] = None
      allow_gaps: Optional[bool] = None
      use_relative_paths: Optional[bool] = None
  ```
- Produces (routes): `POST /stages`, `PUT /stages/{id}`, `DELETE /stages/{id}`, `POST /stages/reorder`, `PUT /stages/bulk`, `GET /settings`, `PUT /settings`, `POST /undo`, `POST /redo` — all return `DocumentResponse` (except `GET /settings` → `GlobalSettings`).

**Design notes:**
- All handlers `def` (sync). Each maps store exceptions to HTTP: `KeyError`→404, `ValueError`→400.
- `POST /stages` body = `StageCreate` (existing schema: name, role, files (StageFiles), expected_gap_ps, gap_tolerance_ps, notes). Flatten into a fields dict: `{"name", "role": role-value, "mdin"/... from files, "expected_gap_ps", "gap_tolerance_ps", "notes"}` and call `store.add_stage(fields)`. `role` may be a `StageRole`; store its `.value` (string). Return `store.to_response()`.
- `PUT /stages/{id}` body = `StageUpdate`. Build a patch dict only from provided (non-None) fields; for `files`, merge per-kind where the sub-field is not None (empty string clears → store `None`). Call `store.update_stage(id, patch)`; `KeyError`→404.
- `DELETE /stages/{id}` → `store.delete_stage`; `KeyError`→404.
- `POST /stages/reorder` body `StageReorderRequest` → `store.reorder(req.stage_ids)`; `ValueError`→400.
- `PUT /stages/bulk` body `BulkStageUpdate` → build patch from `req.update` like PUT; `store.bulk_update(req.stage_ids, patch)`; `KeyError`→400.
- `GET /settings` → `GlobalSettings(**store.get().settings)`.
- `PUT /settings` body `SettingsPatch` → `patch = req.model_dump(exclude_none=True)`; `store.patch_settings(patch)`; return `store.to_response()`.
- `POST /undo` → `store.undo()`; `POST /redo` → `store.redo()`; return `store.to_response()`.
- Helper to convert a `StageFiles`/`StageUpdate.files` into per-kind patch entries (empty string → None, None → skip). Implement a small local `_files_patch(files) -> Dict[str, Optional[str]]`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_gui_api.py
def test_stage_crud_and_dirty(client):
    c, base = client
    r = c.post("/api/stages", json={"name": "min", "role": "minimization"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dirty"] is True
    sid = body["stages"][0]["id"]

    r = c.put(f"/api/stages/{sid}", json={"files": {"mdin": "min.in"}})
    assert r.json()["stages"][0]["mdin"] == "min.in"

    r = c.put(f"/api/stages/{sid}", json={"files": {"mdin": ""}})  # clear
    assert r.json()["stages"][0]["mdin"] is None

    r = c.delete(f"/api/stages/{sid}")
    assert r.json()["stages"] == []

    r = c.delete(f"/api/stages/{sid}")  # already gone
    assert r.status_code == 404


def test_reorder_and_bulk(client):
    c, base = client
    a = c.post("/api/stages", json={"name": "a"}).json()["stages"][0]["id"]
    b = c.post("/api/stages", json={"name": "b"}).json()["stages"][-1]["id"]
    r = c.post("/api/stages/reorder", json={"stage_ids": [b, a]})
    assert [s["name"] for s in r.json()["stages"]] == ["b", "a"]
    r = c.put("/api/stages/bulk", json={"stage_ids": [a, b],
                                        "update": {"role": "production"}})
    assert all(s["role"] == "production" for s in r.json()["stages"])


def test_settings_patch_and_undo_redo(client):
    c, base = client
    c.post("/api/stages", json={"name": "a"})
    r = c.put("/api/settings", json={"global_prmtop": "sys.prmtop"})
    assert r.json()["settings"]["global_prmtop"] == "sys.prmtop"
    # GET settings reflects it
    assert c.get("/api/settings").json()["global_prmtop"] == "sys.prmtop"
    # undo reverts the settings patch, keeps the stage
    r = c.post("/api/undo")
    assert r.json()["settings"]["global_prmtop"] is None
    assert len(r.json()["stages"]) == 1
    # redo re-applies
    r = c.post("/api/redo")
    assert r.json()["settings"]["global_prmtop"] == "sys.prmtop"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_api.py -k "crud or reorder or settings_patch" -q`
Expected: FAIL (routes not yet added / old shapes).

- [ ] **Step 3: Add `SettingsPatch` schema** (in `schemas.py`, after `GlobalSettings`), exactly as in the Interfaces block above.

- [ ] **Step 4: Add the CRUD/settings/undo routes** to `routes.py` (after the lifecycle routes):

```python
from .schemas import (
    GlobalSettings, StageCreate, StageUpdate, StageReorderRequest,
    BulkStageUpdate, SettingsPatch,
)


def _role_value(role) -> str:
    return role.value if hasattr(role, "value") else (role or "")


def _files_patch(files) -> dict:
    patch = {}
    if files is None:
        return patch
    for kind in ("prmtop", "mdin", "mdout", "mdcrd", "inpcrd"):
        val = getattr(files, kind, None)
        if val is not None:
            patch[kind] = val if val else None  # "" clears
    return patch


@router.post("/stages", response_model=DocumentResponse)
def create_stage(stage: StageCreate) -> DocumentResponse:
    store = get_store()
    fields = {"name": stage.name, "role": _role_value(stage.role),
              "expected_gap_ps": stage.expected_gap_ps,
              "gap_tolerance_ps": stage.gap_tolerance_ps,
              "notes": list(stage.notes)}
    fields.update(_files_patch(stage.files))
    store.add_stage(fields)
    return store.to_response()


@router.put("/stages/{stage_id}", response_model=DocumentResponse)
def update_stage(stage_id: str, update: StageUpdate) -> DocumentResponse:
    store = get_store()
    patch = {}
    if update.name is not None:
        patch["name"] = update.name
    if update.role is not None:
        patch["role"] = _role_value(update.role)
    if update.expected_gap_ps is not None:
        patch["expected_gap_ps"] = update.expected_gap_ps
    if update.gap_tolerance_ps is not None:
        patch["gap_tolerance_ps"] = update.gap_tolerance_ps
    if update.notes is not None:
        patch["notes"] = list(update.notes)
    patch.update(_files_patch(update.files))
    try:
        store.update_stage(stage_id, patch)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Stage not found: {stage_id}")
    return store.to_response()


@router.delete("/stages/{stage_id}", response_model=DocumentResponse)
def delete_stage(stage_id: str) -> DocumentResponse:
    store = get_store()
    try:
        store.delete_stage(stage_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Stage not found: {stage_id}")
    return store.to_response()


@router.post("/stages/reorder", response_model=DocumentResponse)
def reorder_stages(req: StageReorderRequest) -> DocumentResponse:
    store = get_store()
    try:
        store.reorder(req.stage_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return store.to_response()


@router.put("/stages/bulk", response_model=DocumentResponse)
def bulk_update_stages(req: BulkStageUpdate) -> DocumentResponse:
    store = get_store()
    upd = req.update
    patch = {}
    if upd.name is not None:
        patch["name"] = upd.name
    if upd.role is not None:
        patch["role"] = _role_value(upd.role)
    if upd.expected_gap_ps is not None:
        patch["expected_gap_ps"] = upd.expected_gap_ps
    if upd.gap_tolerance_ps is not None:
        patch["gap_tolerance_ps"] = upd.gap_tolerance_ps
    if upd.notes is not None:
        patch["notes"] = list(upd.notes)
    patch.update(_files_patch(upd.files))
    try:
        store.bulk_update(req.stage_ids, patch)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown stage ID: {exc}")
    return store.to_response()


@router.get("/settings", response_model=GlobalSettings)
def get_settings() -> GlobalSettings:
    return GlobalSettings(**get_store().get().settings)


@router.put("/settings", response_model=DocumentResponse)
def update_settings(req: SettingsPatch) -> DocumentResponse:
    store = get_store()
    store.patch_settings(req.model_dump(exclude_none=True))
    return store.to_response()


@router.post("/undo", response_model=DocumentResponse)
def undo() -> DocumentResponse:
    store = get_store()
    store.undo()
    return store.to_response()


@router.post("/redo", response_model=DocumentResponse)
def redo() -> DocumentResponse:
    store = get_store()
    store.redo()
    return store.to_response()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_gui_api.py -q`
Expected: PASS (all prior + 3 new).

- [ ] **Step 6: Commit**

```bash
git add ambermeta/gui/api/routes.py ambermeta/gui/api/schemas.py tests/test_gui_api.py
git commit -m "feat(gui): stage CRUD, reorder, bulk, settings patch, undo/redo routes (B1 Task 7)"
```

---

## Task 8: routes — validate, files (list/metadata/related), link-restarts

**Files:**
- Modify: `ambermeta/gui/api/routes.py`
- Modify: `ambermeta/gui/api/schemas.py` (add `ValidationReport`, `StageIssue`, `MissingFile`; replace/keep `FileMetadata`)
- Test: `tests/test_gui_api.py` (add)

**Interfaces:**
- Consumes: `core_bridge.build_validation_report`, `core_bridge.file_metadata`, `core_bridge.restart_chain`, `core_bridge.detect_sequences`, `files.build_file_tree`, `files.resolve_within_base`, `ambermeta.protocol.detect_numeric_sequences`.
- Produces (schemas):
  ```python
  class MissingFile(BaseModel):
      kind: str
      path: str

  class StageIssue(BaseModel):
      name: str
      ok: bool
      degraded: bool = False
      errors: List[str] = Field(default_factory=list)
      warnings: List[str] = Field(default_factory=list)
      info: List[str] = Field(default_factory=list)
      missing_files: List[MissingFile] = Field(default_factory=list)

  class ValidationReport(BaseModel):
      ok: bool
      totals: Dict[str, float] = Field(default_factory=dict)
      protocol_issues: List[str] = Field(default_factory=list)
      stage_issues: List[StageIssue] = Field(default_factory=list)
  ```
  Keep `FileMetadata` but its `metadata` field now carries `core_bridge.file_metadata` output (`details`/`warnings`/`kind`).
- Produces (routes): `POST /validate`→`ValidationReport`; `GET /files`→`List[FileInfo]`; `GET /files/metadata`→`FileMetadata`; `GET /files/related/{stem}`→`Dict[str,str]`; `POST /link-restarts`→`DocumentResponse`; `GET /sequences`→`Dict[str, List[str]]` (base name → ordered stage **ids**).
- Produces (core_bridge): `core_bridge.detect_sequences(stage_names: List[str]) -> Dict[str, List[str]]` — thin wrapper over `ambermeta.protocol.detect_numeric_sequences` (keeps numbered-run grouping in the core; the frontend must NOT re-implement it).

**Design notes:**
- `POST /validate`: `doc = store.get()`; `report = core_bridge.build_validation_report(doc.stages, doc.settings, doc.base_directory)`; build `ValidationReport(**report)` (Pydantic coerces nested dicts). `totals` is `Dict[str,float]` — `stage_count` is int but fits float; keep `Dict[str, float]`.
- `GET /files`: `path = query path or base`; `_within_base`; 404 if not a dir; `files.build_file_tree(resolved, recursive, include_all)`. Add `include_all: bool = Query(False)`.
- `GET /files/metadata`: `_within_base`; 404 if not a file; `meta = core_bridge.file_metadata(resolved)`; return `FileMetadata(file_path=resolved, file_type=files.detect_file_type(resolved), metadata=meta, warnings=meta["warnings"])`.
- `GET /files/related/{stem:path}`: keep the existing behavior but route the directory through `_within_base` and reuse the existing extension map. (This endpoint is small and core-agnostic — it's pure FS grouping for drag-assist. Port it as-is, swapping `_validate_path_within_base`→`_within_base` and `state.base_directory`→`get_store().get().base_directory`.)
- `POST /link-restarts`: `doc = store.get()`; `mapping = core_bridge.restart_chain(doc.stages, doc.settings, doc.base_directory, recursive=doc.settings.get("auto_link_restarts") and False)` — recursion off by default (match core default); apply: for each stage in doc whose `name` in mapping and current `inpcrd` differs, `store.update_stage(stage_id, {"inpcrd": mapping[name]})`. To apply atomically under one history frame, add a store method? Simpler: collect `{id: inpcrd}` then call a single `store.bulk_apply_inpcrd`. To avoid adding a store method, call `store.update_stage` per change (each its own undo frame) — acceptable but noisy. **Decision:** add a focused store method `apply_restarts(self, mapping_by_name: Dict[str,str]) -> int` in this task (one snapshot, set inpcrd for matching names, return count). Document it.

- `GET /sequences`: keeps numbered-run grouping in the core (spec delegation table). `doc = store.get()`; map names→ids (`names_to_ids` dict, preserving order, tolerant of duplicate names); `groups = core_bridge.detect_sequences([s["name"] for s in doc.stages])` (returns `{base: [names_in_order]}`); translate each group's names to ids; return only groups with `len(ids) > 1`. The B2 frontend consumes this for collapsible sequence groups — it does **not** reimplement the regex (that would re-create the triplication the spec forbids).
- `core_bridge.detect_sequences` is a one-line wrapper: `return detect_numeric_sequences(list(stage_names))`. Add `from ambermeta.protocol import detect_numeric_sequences` to core_bridge's protocol import group.

**Add to `document.py` (`DocumentStore`):**
```python
    def apply_restarts(self, mapping_by_name: Dict[str, str]) -> int:
        with self.lock:
            self._snapshot()
            count = 0
            for s in self._doc.stages:
                new = mapping_by_name.get(s["name"])
                if new is not None and s.get("inpcrd") != new:
                    s["inpcrd"] = new
                    count += 1
            if count:
                self._doc.dirty = True
            else:
                self._undo.pop()  # nothing changed; drop the snapshot
            return count
```

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_gui_api.py
def test_validate_flags_missing_file(client):
    c, base = client
    c.post("/api/stages", json={"name": "min", "role": "minimization",
                                "files": {"mdin": "nope.in"}})
    r = c.post("/api/validate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["stage_issues"][0]["name"] == "min"
    assert any("nope.in" in e for e in body["stage_issues"][0]["errors"])


def test_files_list_and_metadata(client):
    c, base = client
    (base / "prod.mdin").write_text(
        "prod\n&cntrl\n  imin=0, nstlim=1000, dt=0.002, ntb=2,\n/\n", encoding="utf-8")
    r = c.get("/api/files", params={"recursive": False})
    assert r.status_code == 200
    assert any(f["name"] == "prod.mdin" for f in r.json())
    r = c.get("/api/files/metadata", params={"path": str(base / "prod.mdin")})
    assert r.status_code == 200, r.text
    assert r.json()["metadata"]["details"] is not None


def test_files_metadata_outside_base_403(client):
    c, base = client
    r = c.get("/api/files/metadata", params={"path": str(base.parent / "x.prmtop")})
    assert r.status_code == 403


def test_sequences_groups_numbered_runs(client):
    c, base = client
    ids = []
    for i in (1, 2, 3):
        body = c.post("/api/stages", json={"name": f"prod_{i:03d}"}).json()
        ids.append(body["stages"][-1]["id"])
    c.post("/api/stages", json={"name": "minimize"})  # singleton, not a sequence
    r = c.get("/api/sequences")
    assert r.status_code == 200, r.text
    groups = r.json()
    # exactly one detected sequence, holding the three prod ids in order
    assert len(groups) == 1
    only = list(groups.values())[0]
    assert only == ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_api.py -k "validate or files_list or metadata_outside or sequences" -q`
Expected: FAIL.

- [ ] **Step 3: Add validation/file schemas** (`schemas.py`) exactly as in the Interfaces block.

- [ ] **Step 4: Add `apply_restarts` to `DocumentStore`** (as specified above) and a unit test in `tests/test_gui_document.py`:

```python
def test_apply_restarts_sets_inpcrd_once():
    store = _new()
    a = store.add_stage({"name": "prod_001"})
    b = store.add_stage({"name": "prod_002"})
    n = store.apply_restarts({"prod_002": "prod_001.rst"})
    assert n == 1
    assert store.get().stages[1]["inpcrd"] == "prod_001.rst"
    n2 = store.apply_restarts({"prod_002": "prod_001.rst"})  # no change
    assert n2 == 0
```

- [ ] **Step 5: Add the routes** (`routes.py`):

```python
from fastapi import Query
from typing import Dict
from pathlib import Path
from .schemas import ValidationReport, FileMetadata, FileInfo
from typing import List


@router.post("/validate", response_model=ValidationReport)
def validate_protocol() -> ValidationReport:
    doc = get_store().get()
    report = core_bridge.build_validation_report(doc.stages, doc.settings,
                                                 doc.base_directory)
    return ValidationReport(**report)


@router.get("/files", response_model=List[FileInfo])
def list_files(path: Optional[str] = Query(None), recursive: bool = Query(True),
               include_all: bool = Query(False)) -> List[FileInfo]:
    doc = get_store().get()
    directory = _within_base(path or doc.base_directory, doc.base_directory)
    if not os.path.isdir(directory):
        raise HTTPException(status_code=404, detail=f"Directory not found: {directory}")
    return files.build_file_tree(directory, recursive=recursive, include_all=include_all)


@router.get("/files/metadata", response_model=FileMetadata)
def get_file_metadata(path: str = Query(...)) -> FileMetadata:
    doc = get_store().get()
    resolved = _within_base(path, doc.base_directory)
    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    meta = core_bridge.file_metadata(resolved)
    return FileMetadata(file_path=resolved, file_type=files.detect_file_type(resolved),
                        metadata=meta, warnings=meta["warnings"])


@router.get("/files/related/{stem:path}")
def get_related_files(stem: str) -> Dict[str, str]:
    doc = get_store().get()
    base_dir = doc.base_directory
    stem_path = stem
    suffixes = {".mdin", ".mdout", ".nc", ".rst", ".rst7", ".prmtop", ".in", ".out",
                ".crd", ".x", ".ncrst", ".restrt", ".inpcrd", ".mdcrd", ".parm7", ".top"}
    if Path(stem).suffix.lower() in suffixes:
        stem_path = str(Path(stem).with_suffix(""))
    if "/" in stem_path or os.sep in stem_path:
        stem_dir = Path(base_dir) / Path(stem_path).parent
        stem_name = Path(stem_path).name
    else:
        stem_dir = Path(base_dir)
        stem_name = stem_path
    file_type_extensions = {
        "mdin": {".mdin", ".in"}, "mdout": {".mdout", ".out"},
        "mdcrd": {".mdcrd", ".nc", ".crd", ".x"},
        "inpcrd": {".rst", ".rst7", ".ncrst", ".restrt", ".inpcrd"},
    }
    _within_base(str(stem_dir), base_dir)
    related: Dict[str, str] = {}
    try:
        if stem_dir.exists():
            for entry in stem_dir.iterdir():
                if entry.is_file() and entry.stem == stem_name:
                    for ftype, exts in file_type_extensions.items():
                        if entry.suffix.lower() in exts and ftype not in related:
                            related[ftype] = str(entry)
                            break
    except OSError:
        pass
    return related


@router.post("/link-restarts", response_model=DocumentResponse)
def link_restarts() -> DocumentResponse:
    store = get_store()
    doc = store.get()
    mapping = core_bridge.restart_chain(doc.stages, doc.settings,
                                        doc.base_directory, recursive=False)
    store.apply_restarts(mapping)
    return store.to_response()


@router.get("/sequences")
def get_sequences() -> Dict[str, List[str]]:
    doc = get_store().get()
    names_to_ids: Dict[str, List[str]] = {}
    for s in doc.stages:
        names_to_ids.setdefault(s["name"], []).append(s["id"])
    groups = core_bridge.detect_sequences([s["name"] for s in doc.stages])
    out: Dict[str, List[str]] = {}
    for base, names in groups.items():
        ids: List[str] = []
        for n in names:
            ids.extend(names_to_ids.get(n, []))
        if len(ids) > 1:
            out[base] = ids
    return out
```

Also add `core_bridge.detect_sequences` (in `core_bridge.py`, alongside the discovery functions; extend the protocol import group with `detect_numeric_sequences`):

```python
def detect_sequences(stage_names: List[str]) -> Dict[str, List[str]]:
    """Numbered-run grouping, delegated to the core (no GUI re-implementation)."""
    return detect_numeric_sequences(list(stage_names))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_gui_api.py tests/test_gui_document.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ambermeta/gui/api/routes.py ambermeta/gui/api/schemas.py ambermeta/gui/api/document.py ambermeta/gui/api/core_bridge.py tests/test_gui_api.py tests/test_gui_document.py
git commit -m "feat(gui): validate, files, link-restarts, sequences routes (B1 Task 8)"
```

---

## Task 9: Purge dead endpoints & re-implementations; delegation tests; full-suite green

**Files:**
- Modify: `ambermeta/gui/api/routes.py` (remove all legacy helpers/routes; final clean file)
- Modify: `ambermeta/gui/api/schemas.py` (remove now-unused `SessionSaveRequest`, `SessionLoadRequest`, `ProtocolState`, `ExportRequest`, `ExportResponse`, `ExportFormat`, `SequenceInfo`, `StageValidation`, `StageResponse`, `ValidationResult` **only if** nothing else imports them — grep first)
- Test: `tests/test_gui_api.py` (add delegation + removed-endpoint tests)

**Interfaces:**
- Consumes: everything above.
- Produces: a `routes.py` whose only engine touch-points are `core_bridge.*` calls; no hand-rolled serializer/validator/sequence/restart/role code remains.

**Design notes:**
- Remove these legacy items from `routes.py` if any remnant survived earlier tasks: `_get_file_type`, `_scan_directory`, the **old hand-rolled** `_detect_sequences`, `_suggest_stage_role`, `_validate_stage`, `export_protocol`, the old `validate_protocol`, `save_session`, `load_session`, `get_protocol`, `_find_initial_coordinates`, `_get_discovered_inpcrd_for_stem`, `_link_restart_files`, the old `link_restart_files` route, `import re`, `import uuid`, `import json` if now unused. (Do NOT remove the new core-backed `get_sequences` route added in Task 8.)
- Endpoints intentionally **removed** (return 404 now): `/api/protocol`, `/api/export`, `/api/session/save`, `/api/session/load`. Protocol/export are superseded by `/document` + `/document/save`. **`/api/sequences` is kept** but re-backed by the core (`detect_numeric_sequences`) so the B2 frontend consumes grouping rather than re-implementing it.
- Delegation tests use `monkeypatch` to assert routes call the core bridge (not a local re-implementation):
  - patch `core_bridge.save_document` → assert called by `POST /document/save`.
  - patch `core_bridge.build_validation_report` → assert called by `POST /validate`.
  - patch `core_bridge.discover` → assert called by `POST /document/discover`.
- Static guard test: read `ambermeta/gui/api/routes.py` source and assert it does **not** contain `import yaml`, `toml.dumps`, `json.dump(`, or `def _validate_stage` (proves serializers/validators were removed). Also assert `core_bridge` is imported.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_gui_api.py
from pathlib import Path as _Path
import ambermeta.gui.api.core_bridge as _cb


def test_removed_endpoints_are_gone(client):
    c, base = client
    assert c.get("/api/protocol").status_code == 404
    assert c.post("/api/export", json={"format": "yaml"}).status_code == 404
    assert c.post("/api/session/save", json={"filename": "x"}).status_code == 404
    # /api/sequences is NOT removed — it is re-backed by the core (Task 8).
    assert c.get("/api/sequences").status_code == 200


def test_save_delegates_to_core_bridge(client, monkeypatch):
    c, base = client
    called = {}

    def fake_save(stages, settings, base_directory, path, fmt):
        called["yes"] = (path, fmt)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("stages: []\n")
        return []

    monkeypatch.setattr(_cb, "save_document", fake_save)
    out = base / "p.yaml"
    r = c.post("/api/document/save", json={"path": str(out), "format": "yaml"})
    assert r.status_code == 200
    assert called["yes"][1] == "yaml"


def test_validate_delegates_to_core_bridge(client, monkeypatch):
    c, base = client
    sentinel = {"ok": True, "totals": {"steps": 0.0, "time_ps": 0.0, "stage_count": 0},
                "protocol_issues": [], "stage_issues": []}
    monkeypatch.setattr(_cb, "build_validation_report", lambda *a, **k: sentinel)
    r = c.post("/api/validate")
    assert r.json()["ok"] is True


def test_routes_have_no_local_engine_code():
    src = _Path("ambermeta/gui/api/routes.py").read_text(encoding="utf-8")
    assert "import yaml" not in src
    assert "toml.dumps" not in src
    assert "def _validate_stage" not in src
    assert "def _detect_sequences" not in src
    assert "from . import core_bridge" in src or "import core_bridge" in src


def test_large_protocol_roundtrips(client):
    # Acceptance criterion 6 (backend level): a large protocol round-trips
    # through create -> save -> open without error. (UI virtualization is B2.)
    c, base = client
    for i in range(150):
        r = c.post("/api/stages", json={"name": f"prod_{i:03d}", "role": "production"})
        assert r.status_code == 200
    assert len(c.get("/api/document").json()["stages"]) == 150
    out = base / "big.yaml"
    assert c.post("/api/document/save", json={"path": str(out), "format": "yaml"}).status_code == 200
    reopened = c.post("/api/document/open", json={"path": str(out)})
    assert reopened.status_code == 200
    assert len(reopened.json()["stages"]) == 150
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_api.py -k "removed or delegates or no_local_engine" -q`
Expected: FAIL (legacy endpoints still 200; engine strings still present).

- [ ] **Step 3: Purge legacy code from `routes.py`**

Delete every legacy helper/route listed in Design notes. The final `routes.py` should contain only: the header docstring, imports (`os`, `typing`, `pathlib.Path`, FastAPI `APIRouter/HTTPException/Query`, `core_bridge`, `files`, `document.DocumentStore`, the schema models actually used), module store state + `set_base_directory`/`get_store`/`_within_base`, and the route handlers from Tasks 6–8. Confirm no remaining reference to removed names.

- [ ] **Step 4: Prune `schemas.py`** — grep the repo for each candidate-for-removal model; delete only those with zero remaining importers:

Run: `python -m pytest -q` is not the check here; first:
```bash
grep -rn "ProtocolState\|ExportRequest\|ExportResponse\|ExportFormat\|SessionSaveRequest\|SessionLoadRequest\|SequenceInfo\|ValidationResult\|StageValidation\|StageResponse" ambermeta tests
```
Remove from `schemas.py` only the names that appear **nowhere else** after Tasks 1–8. (Keep `FileType`, `StageRole`, `FileInfo`, `StageFiles`, `StageCreate`, `StageUpdate`, `StageReorderRequest`, `BulkStageUpdate`, `GlobalSettings`, `FileMetadata`, and all B1-added models.)

- [ ] **Step 5: Run the full suite + import smoke test**

Run:
```bash
python -c "from ambermeta.gui.server import create_app; create_app('.')"
python -m pytest -q
```
Expected: import OK; entire suite PASS (pre-existing tests + all new GUI tests). Investigate any failure with systematic-debugging before proceeding.

- [ ] **Step 6: Commit**

```bash
git add ambermeta/gui/api/routes.py ambermeta/gui/api/schemas.py tests/test_gui_api.py
git commit -m "refactor(gui): purge triplicated backend; delegation tests; single-engine API (B1 Task 9)"
```

---

## Self-Review (completed by plan author)

**Spec coverage (B1 section of `2026-06-23-gui-redesign-design.md`):**
- Core delegation table (export/open/validation/sequence/restart/role/metadata/HMR) → Tasks 2,3,4 (`core_bridge`) + delegation tests (Task 9). Sequence detection stays in the core via `core_bridge.detect_sequences` + `GET /sequences` (Task 8) — the B2 frontend consumes grouping rather than re-implementing the regex (avoids re-introducing triplication).
- API surface (`GET /document`, open/save/discover, stage CRUD, validate, files, files/metadata, files/related, settings, undo/redo, remove session JSON) → Tasks 6,7,8,9. `preview` added (supports acceptance #1 testing + B2 copy/export). Save covers "Save As" via optional path/format (Export = Save-As).
- State & safety (single Document behind a lock; FS off event loop; open/save containment) → Task 1 (lock + store), sync handlers (Task 6 design note), Task 5 (containment), enforced in 6/8.
- Testing strategy (open/save round-trip == write_manifest; validation matches core; /files/metadata real details; discover splits HMR/normal; reorder/CRUD under lock; containment; delegation tests) → Tasks 2,3,4,6,7,8,9.
- Acceptance #1 (byte-identical export) → Task 2 + Task 6 tests. #2 (validation parity) → Task 4 + Task 8. #3 (open→edit→save round-trip) → Task 6. #4 (server-authoritative undo incl settings) → Task 1 + Task 7. #5 (metadata real details) → Task 4 + Task 8. #6 (large protocols) — backend smoke test `test_large_protocol_roundtrips` (150 stages create→save→open) in Task 9; UI virtualization is B2. #7 (offline) — backend has no CDN; B2 bundles assets. #8 (one engine, delegation tests) → Task 9. #9 (full suite green) → Task 9 Step 5.

**Placeholder scan:** No TBD/"add error handling"/"similar to Task N" — every code step has complete code; every test step has runnable assertions.

**Type consistency:** `StageModel`/`GlobalSettings`/`DocumentResponse` field names consistent across document.py ↔ schemas.py ↔ routes. `document_to_payload`/`save_document`/`open_manifest`/`discover`/`build_validation_report`/`restart_chain`/`file_metadata` signatures referenced identically in their defining task and consuming routes. Store method names (`add_stage`, `update_stage`, `delete_stage`, `reorder`, `bulk_update`, `patch_settings`, `replace`, `mark_saved`, `undo`, `redo`, `apply_restarts`, `to_response`, `get`, `can_undo`, `can_redo`) consistent between Task 1/8 definitions and Task 6/7/8 callers.

**Known deviations from spec (intentional, low-risk):** (1) `preview` endpoint added (supports acceptance #1 testing + B2 copy/export). (2) Stage CRUD returns full `DocumentResponse` instead of a single stage (server-authoritative; the B2 frontend is new so no compatibility cost). (3) FS offloading via sync handlers rather than explicit `run_in_threadpool` (equivalent; idiomatic FastAPI). (`/sequences` is retained and core-backed — not a deviation.)
