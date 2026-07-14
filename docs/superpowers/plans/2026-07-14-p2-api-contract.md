# P2 — API Contract (Simulation model) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pivot the GUI backend from the flat `StageModel` document to the three-level **Simulation → Phase → Step** model (P1's `ambermeta/simulation.py`) — a sim-owned topology pool + starting structure, per-step topology binding + input-coords source, draft-first discovery, and a data-driven suggestions surface — keeping the server-authoritative document + single mutation funnel + undo/redo.

**Architecture:** The `DocumentStore` now holds a P1 `Simulation` dataclass; undo/redo deep-copies `(simulation, settings, manifest_path, dirty)`. `schemas.py` mirrors the Simulation as Pydantic models. `core_bridge.py` delegates open/save/preview to P1's `load_simulation`/`write_simulation`, and gains `discover_draft` (builds a full best-guess `Simulation` from a directory using P1's `classify_role`/`classify_topology_pool`/`implies_hmr`/`sniff_coordinate_kind` + `detect_sequence_gaps`), `build_suggestions`, `validate_simulation` (flattens steps and reuses the existing validation engine), and `read_file_head`. `routes.py` replaces the flat `/stages*` surface with topology/phase/step/assign endpoints. The frontend is rebuilt against this in P3, so the old endpoints are removed, not kept.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pytest + FastAPI `TestClient`. No new third-party dependencies.

## Global Constraints

- **Canonical role tokens ONLY:** `minimization | heating | equilibration | production | ""` written to any role field (`StageRole` enum / `Phase.role`). Roles come from P1's `ambermeta.roles.classify_role` — never re-implement role inference here.
- **HMR rule:** `dt > 0.002` implies HMR, via `ambermeta.topology_pool.implies_hmr`. Never hardcode `0.003`.
- **Manifest v2 shape** (persisted by P1): `{version:2, simulation:{topologies, starting_structure}, phases, steps}`. Open/save/preview go through `ambermeta.simulation.load_simulation`/`write_simulation` (v2 = json/yaml; toml/csv v2 export is out of scope).
- **Server-authoritative + single mutation funnel + undo/redo:** every mutator snapshots first, validates ids before mutating (raise `KeyError`/`ValueError` before any state change), and returns the whole `DocumentResponse`. No client-side authority.
- **Security preserved:** every path from a request passes `files.resolve_within_base` (403 on escape). Static sub-paths declared before parameterised routes.
- **No new third-party dependencies.** Branch: `phase-step-redesign`.
- **Every task ends with the FULL `pytest -q` suite green**, not just the new test.

---

## File Structure

**Rewrite (full replacement of contents):**
- `ambermeta/gui/api/schemas.py` — Pydantic models mirroring the Simulation (Task A1).
- `ambermeta/gui/api/document.py` — `Document{simulation}` + `DocumentStore` with topology/phase/step mutators (Tasks B1–B5).
- `ambermeta/gui/api/routes.py` — the new endpoint surface (Tasks D1–D5).

**Modify (add functions, keep the reusable helpers):**
- `ambermeta/gui/api/core_bridge.py` — keep `resolve_format`, `_relativize`, `document_to_payload`, `build_validation_report`, `_resolve`, `file_metadata`, `_EXT_KIND`, `_KIND_PARSER`; ADD `open_simulation`, `save_simulation`, `preview_simulation`, `discover_draft`, `build_suggestions`, `_flatten_simulation`, `validate_simulation`, `read_file_head`; REMOVE the now-unused `open_manifest`, `save_document`, `preview_document`, `discover`, `restart_chain`, `detect_sequences`, `_gui_stage_from_entry`, `_stages_list_from_raw`, `classify_topologies`, `_NON_TOPOLOGY_KINDS` (Tasks C1–C5).

**Unchanged:** `ambermeta/gui/api/files.py` (P2 does not touch file-kind classification — that is P1-fixes). `ambermeta/gui/server.py` (mounts `routes.router`).

**Tests (new):** `tests/test_gui_document.py` is rewritten for the new store; add `tests/test_gui_core_bridge_sim.py` and `tests/test_gui_api_sim.py`. Existing `tests/test_gui_api.py`/`test_gui_core_bridge.py`/`test_gui_document.py` that assert the OLD flat contract are replaced/updated per task (each such change is called out in its task).

**Note on `_UNSET` / clearing a step's topology:** `StepUpdate.topology` uses Pydantic v2 `model_fields_set` in the route to distinguish "absent" (leave) from "null" (clear) — no sentinel value in the schema.

---

## Group A — Schemas

### Task A1: Rewrite `schemas.py` for the Simulation model

**Files:**
- Rewrite: `ambermeta/gui/api/schemas.py`
- Test: `tests/test_gui_schemas_sim.py`

**Interfaces:**
- Produces: `FileType`, `StageRole`, `TopologyKind` enums; `TopologyModel`, `InputCoordsModel`, `StepModel`, `PhaseModel`, `SimulationModel`, `RuntimeSettings`, `SettingsPatch`, `DocumentResponse`; request models `AddTopology`, `UpdateTopology`, `SetStartingStructure`, `PhaseCreate`, `PhaseUpdate`, `PhaseReorder`, `StepCreate`, `StepUpdate`, `StepMove`, `StepReorder`, `AssignRequest`, `StageFiles`; `Suggestion`, `MissingFile`, `StageIssue`, `ValidationReport` (with `suggestions`), `DiscoverResult`, `FileInfo`, `FileMetadata`, `RawFile`, `OpenRequest`, `SaveRequest`, `SaveResult`, `DiscoverRequest`, `PreviewRequest`, `PreviewResponse`, `ApiError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gui_schemas_sim.py
from ambermeta.gui.api.schemas import (
    SimulationModel, PhaseModel, StepModel, TopologyModel, InputCoordsModel,
    DocumentResponse, RuntimeSettings, AssignRequest, DiscoverResult, ValidationReport,
)


def test_simulation_model_nests_phases_and_steps():
    sim = SimulationModel(
        topologies=[TopologyModel(id="t0", path="wt.prmtop", kind="hmr")],
        starting_structure="wt.inpcrd",
        phases=[PhaseModel(id="p0", name="Min", role="minimization", steps=[
            StepModel(id="s0", name="min", topology="t0",
                      input_coords=InputCoordsModel(source="starting_structure"), mdin="min.in")])],
    )
    dumped = sim.model_dump()
    assert dumped["version"] == 2
    assert dumped["topologies"][0]["kind"] == "hmr"
    assert dumped["phases"][0]["role"] == "minimization"
    assert dumped["phases"][0]["steps"][0]["input_coords"]["source"] == "starting_structure"


def test_document_response_defaults():
    doc = DocumentResponse(base_directory="/x")
    assert doc.simulation.version == 2 and doc.simulation.phases == []
    assert doc.settings.strict_validation is True


def test_assign_request_and_reports():
    a = AssignRequest(path="wt.prmtop", target_type="pool", kind="normal")
    assert a.target_type == "pool"
    r = ValidationReport(ok=True)
    assert r.suggestions == []
    d = DiscoverResult(document=DocumentResponse(base_directory="/x"))
    assert d.suggestions == [] and d.warnings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_schemas_sim.py -q`
Expected: FAIL with `ImportError` (new names not present).

- [ ] **Step 3: Rewrite `schemas.py`**

```python
"""Pydantic schemas for the AmberMeta GUI API (v2: Simulation -> Phase -> Step)."""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum


class FileType(str, Enum):
    PRMTOP = "prmtop"
    MDIN = "mdin"
    MDOUT = "mdout"
    MDCRD = "mdcrd"
    INPCRD = "inpcrd"
    FOLDER = "folder"
    OTHER = "other"


class StageRole(str, Enum):
    MINIMIZATION = "minimization"
    HEATING = "heating"
    EQUILIBRATION = "equilibration"
    PRODUCTION = "production"
    UNKNOWN = ""


class TopologyKind(str, Enum):
    NORMAL = "normal"
    HMR = "hmr"


class FileInfo(BaseModel):
    path: str
    name: str
    file_type: FileType
    is_directory: bool = False
    size: Optional[int] = None
    extension: Optional[str] = None
    parent: Optional[str] = None
    children: Optional[List["FileInfo"]] = None

    class Config:
        use_enum_values = True


# ---- Simulation model (mirrors ambermeta.simulation dataclasses) ----

class TopologyModel(BaseModel):
    id: str
    path: str
    kind: TopologyKind = TopologyKind.NORMAL

    class Config:
        use_enum_values = True


class InputCoordsModel(BaseModel):
    source: str = "starting_structure"   # starting_structure | step | path
    ref: Optional[str] = None
    path: Optional[str] = None


class StepModel(BaseModel):
    id: str
    name: str
    topology: Optional[str] = None
    input_coords: InputCoordsModel = Field(default_factory=InputCoordsModel)
    mdin: Optional[str] = None
    mdout: Optional[str] = None
    mdcrd: Optional[str] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: List[str] = Field(default_factory=list)


class PhaseModel(BaseModel):
    id: str
    name: str
    role: StageRole = StageRole.UNKNOWN
    steps: List[StepModel] = Field(default_factory=list)

    class Config:
        use_enum_values = True


class SimulationModel(BaseModel):
    version: int = 2
    topologies: List[TopologyModel] = Field(default_factory=list)
    starting_structure: Optional[str] = None
    phases: List[PhaseModel] = Field(default_factory=list)


class RuntimeSettings(BaseModel):
    """Runtime-only flags (topology/coords now live in the Simulation)."""
    auto_link_restarts: bool = True
    strict_validation: bool = True
    allow_gaps: bool = False
    use_relative_paths: bool = True


class SettingsPatch(BaseModel):
    auto_link_restarts: Optional[bool] = None
    strict_validation: Optional[bool] = None
    allow_gaps: Optional[bool] = None
    use_relative_paths: Optional[bool] = None


class DocumentResponse(BaseModel):
    base_directory: str
    manifest_path: Optional[str] = None
    dirty: bool = False
    can_undo: bool = False
    can_redo: bool = False
    settings: RuntimeSettings = Field(default_factory=RuntimeSettings)
    simulation: SimulationModel = Field(default_factory=SimulationModel)


# ---- request models ----

class StageFiles(BaseModel):
    """Per-step run files (topology/coords are handled separately)."""
    mdin: Optional[str] = None
    mdout: Optional[str] = None
    mdcrd: Optional[str] = None


class AddTopology(BaseModel):
    path: str
    kind: TopologyKind = TopologyKind.NORMAL


class UpdateTopology(BaseModel):
    path: Optional[str] = None
    kind: Optional[TopologyKind] = None


class SetStartingStructure(BaseModel):
    path: Optional[str] = None


class PhaseCreate(BaseModel):
    name: str
    role: StageRole = StageRole.UNKNOWN


class PhaseUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[StageRole] = None


class PhaseReorder(BaseModel):
    phase_ids: List[str]


class StepCreate(BaseModel):
    name: str
    topology: Optional[str] = None
    input_coords: Optional[InputCoordsModel] = None
    mdin: Optional[str] = None
    mdout: Optional[str] = None
    mdcrd: Optional[str] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: List[str] = Field(default_factory=list)


class StepUpdate(BaseModel):
    # `topology` uses model_fields_set in the route: absent = leave, null = clear.
    name: Optional[str] = None
    topology: Optional[str] = None
    input_coords: Optional[InputCoordsModel] = None
    files: Optional[StageFiles] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: Optional[List[str]] = None


class StepMove(BaseModel):
    phase_id: str
    index: int = -1   # -1 appends


class StepReorder(BaseModel):
    step_ids: List[str]


class AssignRequest(BaseModel):
    path: str
    target_type: str   # pool | starting_structure | phase_topology | step_topology | step_slot
    target_id: Optional[str] = None
    kind: Optional[TopologyKind] = None   # for pool / *_topology
    slot: Optional[str] = None            # for step_slot: mdin|mdout|mdcrd


class Suggestion(BaseModel):
    id: str
    kind: str        # missing_run|continuity_gap|topology_confirm|restart_link|role_guess|starting_structure
    severity: str    # needs_you|applied|info
    title: str
    evidence: str
    actions: List[str] = Field(default_factory=list)


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
    suggestions: List[Suggestion] = Field(default_factory=list)


class FileMetadata(BaseModel):
    file_path: str
    file_type: FileType
    metadata: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)

    class Config:
        use_enum_values = True


class RawFile(BaseModel):
    path: str
    content: str
    truncated: bool = False


class ApiError(BaseModel):
    detail: str
    code: Optional[str] = None


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


class DiscoverResult(BaseModel):
    document: DocumentResponse
    suggestions: List[Suggestion] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class PreviewRequest(BaseModel):
    format: str = "yaml"


class PreviewResponse(BaseModel):
    content: str
    warnings: List[str] = Field(default_factory=list)
    format: str


FileInfo.model_rebuild()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_schemas_sim.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/schemas.py tests/test_gui_schemas_sim.py
git commit -m "feat(gui): rewrite API schemas for the Simulation->Phase->Step model"
```

---

## Group B — Document store

### Task B1: Store skeleton holding a `Simulation`

**Files:**
- Rewrite: `ambermeta/gui/api/document.py`
- Rewrite: `tests/test_gui_document.py` (the old flat-stage tests are replaced)

**Interfaces:**
- Consumes: `ambermeta.simulation.{Simulation, Phase, Step, Topology, InputCoords}`; `schemas` (lazily, in `to_response`).
- Produces: `Document`, `DocumentStore` with `reset`, `get`, `snapshot() -> (simulation, settings, manifest_path, base_directory)`, `can_undo`, `can_redo`, `to_response()`, `undo`, `redo`, `replace`, `patch_settings`, `mark_saved`, and helpers `_find_phase`, `_find_step`, `_find_topology`, `_sim_to_model`. (Mutators land in B2–B5.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gui_document.py
from ambermeta.gui.api.document import DocumentStore
from ambermeta.simulation import Simulation, Phase, Step, Topology, InputCoords


def _store():
    return DocumentStore("/base")


def test_empty_document_response():
    resp = _store().to_response()
    assert resp.base_directory == "/base"
    assert resp.simulation.version == 2 and resp.simulation.phases == []
    assert resp.can_undo is False and resp.dirty is False


def test_replace_and_snapshot_round_trip():
    st = _store()
    sim = Simulation(
        topologies=[Topology(id="t0", path="wt.prmtop", kind="hmr")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="p0", name="Prod", role="production", steps=[
            Step(id="s0", name="prod", topology="t0",
                 input_coords=InputCoords(source="starting_structure"), mdin="prod.in")])],
    )
    st.replace(simulation=sim, settings=st.get().settings, manifest_path=None,
               dirty=True, reset_history=True)
    resp = st.to_response()
    assert resp.simulation.topologies[0].kind == "hmr"
    assert resp.simulation.phases[0].steps[0].name == "prod"
    got_sim, settings, mp, base = st.snapshot()
    assert got_sim.phases[0].steps[0].topology == "t0" and base == "/base"


def test_undo_redo_noop_when_empty():
    st = _store()
    st.undo(); st.redo()   # no error, no change
    assert st.to_response().can_undo is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_document.py -q`
Expected: FAIL (old `document.py` has no `simulation`; new API differs).

- [ ] **Step 3: Rewrite `document.py` (skeleton)**

```python
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_document.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/document.py tests/test_gui_document.py
git commit -m "feat(gui): DocumentStore holds a Simulation; state/undo/redo/to_response"
```

### Task B2: Topology mutators

**Files:**
- Modify: `ambermeta/gui/api/document.py` (add methods to `DocumentStore`)
- Modify: `tests/test_gui_document.py`

**Interfaces:**
- Produces: `add_topology(path, kind) -> str`, `update_topology(id, patch)`, `remove_topology(id)` (clears any step binding referencing it), `set_starting_structure(path)`, and internal `_topology_id_for_path(path, kind) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gui_document.py
def test_topology_pool_mutators_and_undo():
    st = _store()
    tid = st.add_topology("wt.prmtop", "normal")
    hid = st.add_topology("wt_hmr.prmtop", "hmr")
    st.set_starting_structure("wt.inpcrd")
    sim = st.get().simulation
    assert [t.path for t in sim.topologies] == ["wt.prmtop", "wt_hmr.prmtop"]
    assert sim.starting_structure == "wt.inpcrd"

    st.update_topology(hid, {"kind": "normal"})
    assert st._find_topology(hid).kind == "normal"

    st.remove_topology(tid)
    assert [t.id for t in st.get().simulation.topologies] == [hid]

    st.undo()   # undo the remove
    assert len(st.get().simulation.topologies) == 2
```

(The `remove_topology` step-binding-clear behaviour is implemented here but *tested* in Task B4, once `add_phase`/`add_step` exist — so this task's suite stays green.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_document.py -q`
Expected: FAIL (`add_topology` not defined).

- [ ] **Step 3: Add the topology mutators**

Add these methods to the `DocumentStore` class (after `mark_saved`):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_document.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/document.py tests/test_gui_document.py
git commit -m "feat(gui): topology-pool + starting-structure mutators"
```

### Task B3: Phase mutators

**Files:**
- Modify: `ambermeta/gui/api/document.py`
- Modify: `tests/test_gui_document.py`

**Interfaces:**
- Produces: `add_phase(name, role) -> str`, `update_phase(id, patch)`, `reorder_phases(ids)`, `delete_phase(id, reassign_to=None)`. **Default policy:** `delete_phase` with `reassign_to=None` deletes the phase *and its steps*; with `reassign_to` set, its steps are appended to that phase before removal.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gui_document.py
def test_phase_mutators_reorder_update_delete():
    st = _store()
    p_min = st.add_phase("Min", "minimization")
    p_prod = st.add_phase("Prod", "production")

    st.reorder_phases([p_prod, p_min])
    assert [p.id for p in st.get().simulation.phases] == [p_prod, p_min]

    st.update_phase(p_min, {"name": "Minimization", "role": "minimization"})
    assert st._find_phase(p_min).name == "Minimization"

    # default delete (reassign_to=None) drops the phase and its steps
    st.delete_phase(p_min)
    assert [p.id for p in st.get().simulation.phases] == [p_prod]


def test_reorder_phases_rejects_mismatched_ids():
    st = _store()
    p = st.add_phase("A", "")
    import pytest
    with pytest.raises(ValueError):
        st.reorder_phases([p, "bogus"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_document.py -q -k phase`
Expected: FAIL (`add_phase` not defined).

- [ ] **Step 3: Add the phase mutators**

Add to `DocumentStore` (after the topology mutators):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_document.py -q -k phase`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/document.py tests/test_gui_document.py
git commit -m "feat(gui): phase mutators (create/update/reorder/delete with reassign policy)"
```

### Task B4: Step mutators

**Files:**
- Modify: `ambermeta/gui/api/document.py`
- Modify: `tests/test_gui_document.py`

**Interfaces:**
- Produces: `add_step(phase_id, fields) -> str`, `update_step(id, patch)` (patch key `"topology"` present ⇒ set incl. `None` to clear; `mdin/mdout/mdcrd` present ⇒ set, `""` clears), `delete_step(id)`, `move_step(id, phase_id, index)`, `reorder_steps(phase_id, ids)`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gui_document.py
def test_step_mutators_move_reorder_clear():
    st = _store()
    pa = st.add_phase("A", "equilibration")
    pb = st.add_phase("B", "production")
    s1 = st.add_step(pa, {"name": "eq1", "mdin": "eq1.in",
                          "input_coords": {"source": "starting_structure"}})
    s2 = st.add_step(pa, {"name": "eq2", "mdin": "eq2.in"})

    st.reorder_steps(pa, [s2, s1])
    assert [s.id for s in st._find_phase(pa).steps] == [s2, s1]

    st.move_step(s1, pb, 0)
    assert [s.id for s in st._find_phase(pa).steps] == [s2]
    assert [s.id for s in st._find_phase(pb).steps] == [s1]

    st.update_step(s1, {"topology": None, "mdout": "eq1.out", "mdin": ""})
    _, step = st._find_step(s1)
    assert step.topology is None and step.mdout == "eq1.out" and step.mdin is None

    st.delete_step(s2)
    assert st._find_phase(pa).steps == []


def test_add_step_sets_input_coords_source():
    st = _store()
    p = st.add_phase("P", "production")
    sid = st.add_step(p, {"name": "prod", "input_coords": {"source": "step", "ref": "prev"}})
    _, s = st._find_step(sid)
    assert s.input_coords.source == "step" and s.input_coords.ref == "prev"


def test_remove_topology_clears_step_binding():
    st = _store()
    tid = st.add_topology("wt.prmtop", "normal")
    pid = st.add_phase("Prod", "production")
    sid = st.add_step(pid, {"name": "prod", "topology": tid})
    st.remove_topology(tid)
    _, step = st._find_step(sid)
    assert step.topology is None


def test_delete_phase_reassigns_steps_to_neighbour():
    st = _store()
    p_min = st.add_phase("Min", "minimization")
    p_prod = st.add_phase("Prod", "production")
    st.add_step(p_min, {"name": "min"})
    st.add_step(p_prod, {"name": "prod_001"})
    st.delete_phase(p_min, reassign_to=p_prod)
    assert [p.id for p in st.get().simulation.phases] == [p_prod]
    assert [s.name for s in st._find_phase(p_prod).steps] == ["prod_001", "min"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_document.py -q -k step_mutators`
Expected: FAIL (`add_step` not defined).

- [ ] **Step 3: Add the step mutators**

Add to `DocumentStore` (after the phase mutators):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_document.py -q`
Expected: PASS (all document tests)

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/document.py tests/test_gui_document.py
git commit -m "feat(gui): step mutators (create/update/delete/move/reorder)"
```

### Task B5: Unified `assign_file`

**Files:**
- Modify: `ambermeta/gui/api/document.py`
- Modify: `tests/test_gui_document.py`

**Interfaces:**
- Produces: `assign_file(path, target_type, target_id=None, kind=None, slot=None)` routing to the pool/starting-structure/phase-topology/step-topology/step-slot primitives; internal `_assign_step_topology`, `_assign_phase_topology`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gui_document.py
def test_assign_file_all_targets():
    st = _store()
    pid = st.add_phase("Prod", "production")
    s1 = st.add_step(pid, {"name": "prod_001"})
    s2 = st.add_step(pid, {"name": "prod_002"})

    st.assign_file("wt.prmtop", "pool", kind="normal")
    assert st.get().simulation.topologies[0].path == "wt.prmtop"

    st.assign_file("wt.inpcrd", "starting_structure")
    assert st.get().simulation.starting_structure == "wt.inpcrd"

    st.assign_file("wt_hmr.prmtop", "phase_topology", target_id=pid, kind="hmr")
    tid = st._find_step(s1)[1].topology
    assert tid is not None and st._find_step(s2)[1].topology == tid   # cascaded to all steps

    st.assign_file("wt.prmtop", "step_topology", target_id=s2)
    assert st._find_step(s2)[1].topology == st.get().simulation.topologies[0].id

    st.assign_file("prod_001.in", "step_slot", target_id=s1, slot="mdin")
    assert st._find_step(s1)[1].mdin == "prod_001.in"


def test_assign_file_bad_target_raises():
    st = _store()
    import pytest
    with pytest.raises(ValueError):
        st.assign_file("x", "bogus")
    with pytest.raises(ValueError):
        st.assign_file("x", "step_slot", target_id=None, slot="mdin")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_document.py -q -k assign`
Expected: FAIL (`assign_file` not defined).

- [ ] **Step 3: Add `assign_file`**

Add to `DocumentStore` (after the step mutators):

```python
    # -- unified assignment -------------------------------------------------
    def _assign_step_topology(self, step_id: str, path: str, kind: Optional[str]) -> None:
        with self.lock:
            _, s = self._find_step(step_id)   # validate before mutating
            self._snapshot()
            s.topology = self._topology_id_for_path(path, kind)
            self._doc.dirty = True

    def _assign_phase_topology(self, phase_id: str, path: str, kind: Optional[str]) -> None:
        with self.lock:
            p = self._find_phase(phase_id)    # validate before mutating
            self._snapshot()
            tid = self._topology_id_for_path(path, kind)
            for s in p.steps:
                s.topology = tid
            self._doc.dirty = True

    def assign_file(self, path: str, target_type: str, target_id: Optional[str] = None,
                    kind: Optional[str] = None, slot: Optional[str] = None) -> None:
        if target_type == "pool":
            self.add_topology(path, kind or "normal")
        elif target_type == "starting_structure":
            self.set_starting_structure(path)
        elif target_type == "phase_topology":
            if not target_id:
                raise ValueError("phase_topology requires target_id (phase id)")
            self._assign_phase_topology(target_id, path, kind)
        elif target_type == "step_topology":
            if not target_id:
                raise ValueError("step_topology requires target_id (step id)")
            self._assign_step_topology(target_id, path, kind)
        elif target_type == "step_slot":
            if not target_id or slot not in _STEP_SLOTS:
                raise ValueError("step_slot requires target_id (step id) and a slot in mdin/mdout/mdcrd")
            self.update_step(target_id, {slot: path})
        else:
            raise ValueError(f"unknown target_type: {target_type}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_document.py -q`
Expected: PASS (whole document suite)

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/document.py tests/test_gui_document.py
git commit -m "feat(gui): unified assign_file routing (pool/start/phase/step/slot)"
```

---

## Group C — core_bridge (Simulation delegation)

### Task C1: open / save / preview via P1's simulation module

**Files:**
- Modify: `ambermeta/gui/api/core_bridge.py`
- Test: `tests/test_gui_core_bridge_sim.py`

**Interfaces:**
- Consumes: `ambermeta.simulation.{load_simulation, write_simulation}`.
- Produces: `open_simulation(path, base_directory) -> Simulation`, `save_simulation(sim, base_directory, path, fmt) -> List[str]`, `preview_simulation(sim, base_directory, fmt) -> {content, warnings}`. Keep the existing `resolve_format`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gui_core_bridge_sim.py
import json
from ambermeta.gui.api import core_bridge
from ambermeta.simulation import Simulation, Phase, Step, Topology


def _sim():
    return Simulation(
        topologies=[Topology(id="t0", path="wt.prmtop", kind="normal")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="p0", name="Min", role="minimization",
                      steps=[Step(id="s0", name="min", topology="t0", mdin="min.in")])],
    )


def test_open_v1_manifest_migrates(tmp_path):
    v1 = {"global_prmtop": "wt.prmtop",
          "stages": [{"name": "min", "stage_role": "minimization", "mdin": "min.in"},
                     {"name": "prod_001", "stage_role": "production", "mdin": "prod_001.in"}]}
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(v1))
    sim = core_bridge.open_simulation(str(path), str(tmp_path))
    assert sim.version == 2
    assert [p.role for p in sim.phases] == ["minimization", "production"]


def test_save_then_preview_round_trip(tmp_path):
    sim = _sim()
    target = tmp_path / "out.json"
    warnings = core_bridge.save_simulation(sim, str(tmp_path), str(target), "json")
    assert warnings == []
    reloaded = core_bridge.open_simulation(str(target), str(tmp_path))
    assert reloaded == sim
    out = core_bridge.preview_simulation(sim, str(tmp_path), "yaml")
    assert "phases" in out["content"] and out["warnings"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_core_bridge_sim.py -q`
Expected: FAIL (`open_simulation` not defined).

- [ ] **Step 3: Add the functions**

Add to `ambermeta/gui/api/core_bridge.py` (top-level functions; keep `import tempfile`, `import os` already present):

```python
def open_simulation(path, base_directory):
    from ambermeta.simulation import load_simulation
    return load_simulation(path)


def save_simulation(sim, base_directory, path, fmt):
    from ambermeta.simulation import write_simulation
    if fmt not in ("json", "yaml"):
        raise ValueError(f"v2 save supports json/yaml only, got: {fmt}")
    write_simulation(sim, path, fmt)
    return []


def preview_simulation(sim, base_directory, fmt):
    from ambermeta.simulation import write_simulation
    if fmt not in ("json", "yaml"):
        raise ValueError(f"v2 preview supports json/yaml only, got: {fmt}")
    tmp = tempfile.NamedTemporaryFile(suffix="." + fmt, delete=False)
    tmp.close()
    try:
        write_simulation(sim, tmp.name, fmt)
        with open(tmp.name, "r", encoding="utf-8") as fh:
            content = fh.read()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return {"content": content, "warnings": []}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_core_bridge_sim.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/core_bridge.py tests/test_gui_core_bridge_sim.py
git commit -m "feat(gui): open/save/preview via ambermeta.simulation (v2)"
```

### Task C2: `discover_draft` — build a best-guess Simulation from a directory

**Files:**
- Modify: `ambermeta/gui/api/core_bridge.py`
- Test: `tests/test_gui_core_bridge_sim.py`

**Interfaces:**
- Consumes: `ambermeta.protocol.{smart_group_files, _ordered_stems}`, `ambermeta.roles.classify_role`, `ambermeta.topology_pool.{classify_topology_pool, implies_hmr}`, `ambermeta.coords.sniff_coordinate_kind`, `ambermeta.parsers.MdinParser`, `build_suggestions` (Task C3).
- Produces: `discover_draft(base_directory, recursive=True, pattern=None) -> {"simulation": Simulation, "suggestions": list, "warnings": list}`.
- **Rules:** a stem group is a *run* iff it has `mdin` or `mdout`; a non-run coordinate group whose file sniffs single-frame (`inpcrd`) supplies the starting structure. Each run's role = `classify_role(stem, mdin_details=…)`; topology = the HMR pooled topology when `implies_hmr(dt)` and one exists, else the first normal (or first) topology. Contiguous same-role runs form one phase. First run's input source = `starting_structure`; later runs = `step` (ref = previous step id).

- [ ] **Step 1: Write the failing test (uses the real fixtures)**

```python
# append to tests/test_gui_core_bridge_sim.py
def test_discover_draft_on_real_fixtures(sample_md_data_dir):
    out = core_bridge.discover_draft(str(sample_md_data_dir), recursive=False)
    sim = out["simulation"]
    # the .top topology is in the pool
    assert any(t.path.endswith(".top") for t in sim.topologies)
    # ntp_prod_000X.mdin/.mdout runs became steps
    step_names = [s.name for p in sim.phases for s in p.steps]
    assert any(n.startswith("ntp_prod_000") for n in step_names)
    # the single-frame .crd is picked as the starting structure, not a run
    assert sim.starting_structure and sim.starting_structure.endswith(".crd")
    assert not any(n.endswith("6NAG") for n in step_names)
    # first step reads the starting structure; a later one chains from a step
    flat = [s for p in sim.phases for s in p.steps]
    assert flat[0].input_coords.source == "starting_structure"
    if len(flat) > 1:
        assert flat[1].input_coords.source == "step"
    assert isinstance(out["suggestions"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_core_bridge_sim.py -q -k discover_draft`
Expected: FAIL (`discover_draft` not defined).

- [ ] **Step 3: Add `discover_draft`**

```python
def discover_draft(base_directory, recursive=True, pattern=None):
    from ambermeta.simulation import Simulation, Phase, Step, Topology, InputCoords
    from ambermeta.roles import classify_role
    from ambermeta.topology_pool import classify_topology_pool, implies_hmr
    from ambermeta.coords import sniff_coordinate_kind
    from ambermeta.protocol import smart_group_files, _ordered_stems
    from ambermeta.parsers import MdinParser
    import uuid

    grouped = smart_group_files(base_directory, pattern=pattern, recursive=recursive)

    prmtop_rels = [p for p in sorted({
        _relativize(v, base_directory)
        for g in grouped.values() for k, v in g.items() if k == "prmtop" and v
    }) if p]
    pool = classify_topology_pool(base_directory, prmtop_rels)

    sim = Simulation()
    sim.topologies = [Topology(id=t.id, path=t.path, kind=t.kind) for t in pool.topologies]
    normals = [t.id for t in sim.topologies if t.kind == "normal"]
    hmrs = [t.id for t in sim.topologies if t.kind == "hmr"]
    default_topo = normals[0] if normals else (sim.topologies[0].id if sim.topologies else None)
    hmr_topo = hmrs[0] if hmrs else None

    # starting structure: a single-frame coordinate file in a NON-run group
    starting = None
    for kinds in grouped.values():
        if kinds.get("mdin") or kinds.get("mdout"):
            continue
        for k in ("inpcrd", "mdcrd"):
            cand = kinds.get(k)
            if cand and sniff_coordinate_kind(cand) == "inpcrd":
                starting = _relativize(cand, base_directory)
                break
        if starting:
            break
    sim.starting_structure = starting

    prev_step_id = None
    for stem in _ordered_stems(grouped):
        kinds = grouped[stem]
        if not (kinds.get("mdin") or kinds.get("mdout")):
            continue  # not a run (topology-only or a coordinate artifact)
        dt = None
        mdin_details = None
        if kinds.get("mdin"):
            try:
                mdin_details = getattr(MdinParser(kinds["mdin"]).parse(), "details", None)
                dt = getattr(mdin_details, "dt", None)
            except (IOError, OSError, ValueError, LookupError):
                pass
        role = classify_role(stem, mdin_details=mdin_details) or ""
        topology = hmr_topo if (hmr_topo and implies_hmr(dt)) else default_topo
        if prev_step_id is None:
            ic = InputCoords(source="starting_structure")
        else:
            ic = InputCoords(source="step", ref=prev_step_id)
        step = Step(
            id=uuid.uuid4().hex[:8], name=stem, topology=topology, input_coords=ic,
            mdin=_relativize(kinds.get("mdin"), base_directory),
            mdout=_relativize(kinds.get("mdout"), base_directory),
            mdcrd=_relativize(kinds.get("mdcrd"), base_directory),
        )
        if not sim.phases or sim.phases[-1].role != role:
            sim.phases.append(Phase(id=uuid.uuid4().hex[:8],
                                    name=(role.title() if role else "Stage"), role=role))
        sim.phases[-1].steps.append(step)
        prev_step_id = step.id

    warnings = []
    if len(sim.topologies) > 1:
        warnings.append(f"{len(sim.topologies)} topologies found; confirm normal vs HMR.")
    return {"simulation": sim, "suggestions": build_suggestions(sim, base_directory),
            "warnings": warnings}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_core_bridge_sim.py -q -k discover_draft`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/core_bridge.py tests/test_gui_core_bridge_sim.py
git commit -m "feat(gui): discover_draft builds a best-guess Simulation (pool+phases+steps+start)"
```

### Task C3: `build_suggestions`

**Files:**
- Modify: `ambermeta/gui/api/core_bridge.py`
- Test: `tests/test_gui_core_bridge_sim.py`

**Interfaces:**
- Consumes: `ambermeta.protocol.detect_sequence_gaps`.
- Produces: `build_suggestions(sim, base_directory) -> List[dict]` — dict shape matches `schemas.Suggestion` (`id, kind, severity, title, evidence, actions`). Covers missing sequence members, HMR topology confirmation, the starting-structure guess, and the role guesses. (Continuity-gap suggestions are appended by `validate_simulation`, Task C4, from `protocol_issues`.)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gui_core_bridge_sim.py
from ambermeta.simulation import InputCoords


def test_build_suggestions_flags_missing_run_and_hmr():
    sim = Simulation(
        topologies=[Topology(id="t0", path="wt.prmtop", kind="normal"),
                    Topology(id="t1", path="wt_hmr.prmtop", kind="hmr")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="p0", name="Production", role="production", steps=[
            Step(id="a", name="prod_0001", topology="t1"),
            Step(id="b", name="prod_0003", topology="t1")])],
    )
    sug = core_bridge.build_suggestions(sim, "/base")
    kinds = {s["kind"] for s in sug}
    assert "missing_run" in kinds        # prod_0002 absent
    assert "topology_confirm" in kinds   # two topologies, one HMR
    assert "starting_structure" in kinds and "role_guess" in kinds
    miss = next(s for s in sug if s["kind"] == "missing_run")
    assert "2" in miss["evidence"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_core_bridge_sim.py -q -k build_suggestions`
Expected: FAIL (`build_suggestions` not defined).

- [ ] **Step 3: Add `build_suggestions`**

```python
def build_suggestions(sim, base_directory):
    from ambermeta.protocol import detect_sequence_gaps
    out = []

    def _sug(kind, severity, title, evidence, actions):
        return {"id": f"sug_{len(out) + 1}", "kind": kind, "severity": severity,
                "title": title, "evidence": evidence, "actions": actions}

    step_names = [s.name for p in sim.phases for s in p.steps]
    for base, missing in detect_sequence_gaps(step_names).items():
        idxs = ", ".join(str(i) for i in missing)
        out.append(_sug("missing_run", "needs_you",
                        f"{base} sequence is missing member(s) {idxs}",
                        f"present members of '{base}' skip index(es) {idxs}",
                        ["Mark as expected gap", "Locate file", "Ignore"]))

    hmr = [t for t in sim.topologies if t.kind == "hmr"]
    if hmr and len(sim.topologies) > 1:
        out.append(_sug("topology_confirm", "needs_you", "Confirm the HMR topology",
                        f"{hmr[0].path} detected as HMR (repartitioned hydrogen mass)",
                        ["Confirm", "Reassign"]))

    if sim.starting_structure:
        out.append(_sug("starting_structure", "applied",
                        f"{sim.starting_structure} set as the starting structure",
                        "single-frame coordinates; feeds the first run", ["Undo"]))

    role_pairs = [f"{p.name}->{p.role}" for p in sim.phases if p.role]
    if role_pairs:
        out.append(_sug("role_guess", "applied", "Phase roles inferred from file content/names",
                        "; ".join(role_pairs), ["Undo"]))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_core_bridge_sim.py -q -k build_suggestions`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/core_bridge.py tests/test_gui_core_bridge_sim.py
git commit -m "feat(gui): build_suggestions (missing runs, HMR confirm, start, roles)"
```

### Task C4: `validate_simulation` (flatten + reuse the validation engine)

**Files:**
- Modify: `ambermeta/gui/api/core_bridge.py`
- Test: `tests/test_gui_core_bridge_sim.py`

**Interfaces:**
- Consumes: the existing `build_validation_report` (kept), `build_suggestions`.
- Produces: `_flatten_simulation(sim) -> List[dict]` (resolves each step's effective topology path + input-coords into a flat stage dict); `validate_simulation(sim, settings, base_directory) -> dict` shaped like `ValidationReport` plus a `suggestions` list (structural suggestions + one `continuity_gap` per `protocol_issue`).
- **Limitation (documented):** an `input_coords.source == "step"` resolves to `inpcrd=None` (the restart file is not stored on the step), so cross-step continuity shows "cannot verify" unless the step has an explicit `path` source. Missing-file, atom-count, and per-run checks are unaffected. Richer restart resolution is a follow-up.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gui_core_bridge_sim.py
def test_validate_simulation_reports_missing_files_and_suggestions(tmp_path):
    (tmp_path / "prod_0001.in").write_text("&cntrl\nimin=0, nstlim=1000, dt=0.002,\n/\n")
    sim = Simulation(
        topologies=[Topology(id="t0", path="wt.prmtop", kind="normal")],
        phases=[Phase(id="p0", name="Production", role="production", steps=[
            Step(id="a", name="prod_0001", topology="t0", mdin="prod_0001.in"),
            Step(id="b", name="prod_0003", topology="t0", mdin="prod_0003.in")])],
    )
    settings = {"strict_validation": True, "allow_gaps": False}
    report = core_bridge.validate_simulation(sim, settings, str(tmp_path))
    assert "stage_issues" in report and "suggestions" in report
    # prod_0003.in and the topology don't exist -> missing-file errors surface
    all_errors = [e for si in report["stage_issues"] for e in si["errors"]]
    assert any("missing" in e for e in all_errors)
    assert any(s["kind"] == "missing_run" for s in report["suggestions"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_core_bridge_sim.py -q -k validate_simulation`
Expected: FAIL (`validate_simulation` not defined).

- [ ] **Step 3: Add the functions**

```python
def _flatten_simulation(sim):
    """Flatten a Simulation into the flat stage dicts the validation engine expects."""
    topo_by_id = {t.id: t.path for t in sim.topologies}
    flat = []
    for p in sim.phases:
        for s in p.steps:
            if s.input_coords.source == "path":
                inpcrd = s.input_coords.path
            elif s.input_coords.source == "starting_structure":
                inpcrd = sim.starting_structure
            else:  # "step" — restart not stored on the step (documented limitation)
                inpcrd = None
            flat.append({
                "name": s.name, "role": p.role,
                "prmtop": topo_by_id.get(s.topology) if s.topology else None,
                "mdin": s.mdin, "mdout": s.mdout, "mdcrd": s.mdcrd, "inpcrd": inpcrd,
                "expected_gap_ps": s.expected_gap_ps, "gap_tolerance_ps": s.gap_tolerance_ps,
                "notes": list(s.notes),
            })
    return flat


def validate_simulation(sim, settings, base_directory):
    flat = _flatten_simulation(sim)
    report = build_validation_report(flat, dict(settings), base_directory)
    suggestions = build_suggestions(sim, base_directory)
    for issue in report.get("protocol_issues", []):
        suggestions.append({
            "id": f"sug_c_{len(suggestions) + 1}", "kind": "continuity_gap",
            "severity": "needs_you", "title": "Continuity note", "evidence": issue,
            "actions": ["Set as expected", "Investigate"],
        })
    report["suggestions"] = suggestions
    return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_core_bridge_sim.py -q -k validate_simulation`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/core_bridge.py tests/test_gui_core_bridge_sim.py
git commit -m "feat(gui): validate_simulation flattens steps + reuses validation engine + suggestions"
```

### Task C5: `read_file_head` + prune the dead flat-model bridge functions

**Files:**
- Modify: `ambermeta/gui/api/core_bridge.py`
- Test: `tests/test_gui_core_bridge_sim.py`

**Interfaces:**
- Produces: `read_file_head(path, max_bytes=4096) -> {"content": str, "truncated": bool}`.
- Removes the now-unused flat-model functions: `open_manifest`, `save_document`, `preview_document`, `discover`, `restart_chain`, `detect_sequences`, `_gui_stage_from_entry`, `_stages_list_from_raw`, `classify_topologies`, `_NON_TOPOLOGY_KINDS`. **Keep** `resolve_format`, `_relativize`, `document_to_payload`, `_save_warnings`, `build_validation_report`, `_resolve`, `file_metadata`, `_EXT_KIND`, `_KIND_PARSER`, `_serialize_metadata` import (still used by `validate_simulation`/`file_metadata`).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gui_core_bridge_sim.py
def test_read_file_head_truncates(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("A" * 10000)
    out = core_bridge.read_file_head(str(f), max_bytes=100)
    assert out["truncated"] is True and len(out["content"]) == 100


def test_dead_flat_functions_are_gone():
    assert not hasattr(core_bridge, "discover")          # replaced by discover_draft
    assert not hasattr(core_bridge, "classify_topologies")
    assert not hasattr(core_bridge, "open_manifest")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_core_bridge_sim.py -q -k "read_file_head or dead_flat"`
Expected: FAIL (`read_file_head` missing; dead functions still present).

- [ ] **Step 3: Add `read_file_head`, delete the dead functions**

Add:

```python
def read_file_head(path, max_bytes=4096):
    with open(path, "rb") as fh:
        data = fh.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    return {"content": data[:max_bytes].decode("utf-8", errors="replace"),
            "truncated": truncated}
```

Delete the function definitions `open_manifest`, `save_document`, `preview_document`, `discover`, `restart_chain`, `detect_sequences`, `_gui_stage_from_entry`, `_stages_list_from_raw`, `classify_topologies`, and the module constant `_NON_TOPOLOGY_KINDS`. Remove any imports that become unused as a result (e.g. `auto_discover` may still be used by `build_validation_report`/`restart`—verify with a grep before removing; `infer_stage_role_from_path` and `detect_numeric_sequences` are no longer used here → drop them from the `from ambermeta.protocol import (...)` block). Run `python -c "import ambermeta.gui.api.core_bridge"` to confirm no NameError.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_core_bridge_sim.py -q && pytest -q`
Expected: PASS (the whole suite — note: `tests/test_gui_core_bridge.py`, which tested the old `discover`/`classify_topologies`, will fail here; update/remove those specific old tests as part of THIS task and note it in the commit.)

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/core_bridge.py tests/test_gui_core_bridge_sim.py tests/test_gui_core_bridge.py
git commit -m "feat(gui): read_file_head; remove dead flat-model bridge functions"
```

---

## Group D — Routes

> All D-task routes use `store = get_store()` and return `store.to_response()` (or a wrapper). `_within_base` guards every request path. Add these imports to the top of the rewritten `routes.py`:
> ```python
> from .schemas import (DocumentResponse, RuntimeSettings, SettingsPatch, OpenRequest,
>     SaveRequest, SaveResult, DiscoverRequest, DiscoverResult, PreviewRequest, PreviewResponse,
>     AddTopology, UpdateTopology, SetStartingStructure, PhaseCreate, PhaseUpdate, PhaseReorder,
>     StepCreate, StepUpdate, StepMove, StepReorder, AssignRequest, ValidationReport,
>     FileMetadata, FileInfo, RawFile, Suggestion)
> ```

### Task D1: Document + open/save/preview/discover/validate/undo/redo routes

**Files:**
- Rewrite: `ambermeta/gui/api/routes.py`
- Test: `tests/test_gui_api_sim.py`

**Interfaces:**
- Consumes: `core_bridge.{open_simulation, save_simulation, preview_simulation, discover_draft, validate_simulation, resolve_format}`, `document.DocumentStore`.
- Produces: `router`, `set_base_directory`, `get_store`, `_within_base`, and routes `GET /document`, `POST /document/open`, `POST /document/save`, `POST /document/preview`, `POST /document/discover` (→`DiscoverResult`), `POST /validate` (→`ValidationReport`), `POST /undo`, `POST /redo`, `GET /settings`, `PUT /settings`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gui_api_sim.py
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ambermeta.gui.api import routes


def _client(base):
    routes.set_base_directory(str(base))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


def test_get_document_empty(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/document")
    assert r.status_code == 200
    body = r.json()
    assert body["simulation"]["version"] == 2 and body["simulation"]["phases"] == []


def test_open_v1_migrates_and_undo_redo(tmp_path):
    v1 = {"global_prmtop": "wt.prmtop",
          "stages": [{"name": "min", "stage_role": "minimization", "mdin": "min.in"},
                     {"name": "prod_001", "stage_role": "production", "mdin": "prod_001.in"}]}
    (tmp_path / "legacy.json").write_text(json.dumps(v1))
    c = _client(tmp_path)
    r = c.post("/api/document/open", json={"path": "legacy.json"})
    assert r.status_code == 200
    roles = [p["role"] for p in r.json()["simulation"]["phases"]]
    assert roles == ["minimization", "production"]


def test_discover_returns_result_with_suggestions(sample_md_data_dir):
    c = _client(sample_md_data_dir)
    r = c.post("/api/document/discover", json={"recursive": False})
    assert r.status_code == 200
    body = r.json()
    assert "document" in body and "suggestions" in body
    assert body["document"]["simulation"]["phases"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_api_sim.py -q`
Expected: FAIL (routes not yet rewritten / new response shapes).

- [ ] **Step 3: Rewrite `routes.py` header + these routes**

```python
"""FastAPI routes for the AmberMeta GUI API (Simulation model)."""
import os
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from . import core_bridge, files
from .document import DocumentStore
from .schemas import (
    DocumentResponse, RuntimeSettings, SettingsPatch, OpenRequest, SaveRequest, SaveResult,
    DiscoverRequest, DiscoverResult, PreviewRequest, PreviewResponse,
    AddTopology, UpdateTopology, SetStartingStructure, PhaseCreate, PhaseUpdate, PhaseReorder,
    StepCreate, StepUpdate, StepMove, StepReorder, AssignRequest, ValidationReport,
    FileMetadata, FileInfo, RawFile, Suggestion,
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
        sim = core_bridge.open_simulation(resolved, doc.base_directory)
    except (FileNotFoundError, ValueError, TypeError, ImportError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read manifest: {exc}")
    store.replace(simulation=sim, settings=store.get().settings,
                  manifest_path=resolved, dirty=False, reset_history=True)
    return store.to_response()


@router.post("/document/save", response_model=SaveResult)
def save_document(req: SaveRequest) -> SaveResult:
    store = get_store()
    sim, settings, manifest_path, base_directory = store.snapshot()
    target = _within_base(req.path, base_directory) if req.path else manifest_path
    if not target:
        raise HTTPException(status_code=400, detail="No path to save to (provide 'path').")
    fmt = core_bridge.resolve_format(target, req.format)
    try:
        warnings = core_bridge.save_simulation(sim, base_directory, target, fmt)
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not save manifest: {exc}")
    store.mark_saved(target)
    return SaveResult(document=store.to_response(), warnings=warnings)


@router.post("/document/preview", response_model=PreviewResponse)
def preview_document(req: PreviewRequest) -> PreviewResponse:
    store = get_store()
    sim, settings, manifest_path, base_directory = store.snapshot()
    try:
        out = core_bridge.preview_simulation(sim, base_directory, req.format)
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not render preview: {exc}")
    return PreviewResponse(content=out["content"], warnings=out["warnings"], format=req.format)


@router.post("/document/discover", response_model=DiscoverResult)
def discover_document(req: DiscoverRequest) -> DiscoverResult:
    store = get_store()
    sim0, settings, manifest_path, base_directory = store.snapshot()
    _within_base(base_directory, base_directory)
    out = core_bridge.discover_draft(base_directory, recursive=req.recursive, pattern=req.pattern)
    store.replace(simulation=out["simulation"], settings=settings,
                  manifest_path=manifest_path, dirty=True, reset_history=False)
    return DiscoverResult(document=store.to_response(),
                          suggestions=[Suggestion(**s) for s in out["suggestions"]],
                          warnings=out["warnings"])


@router.post("/validate", response_model=ValidationReport)
def validate_protocol() -> ValidationReport:
    store = get_store()
    sim, settings, manifest_path, base_directory = store.snapshot()
    report = core_bridge.validate_simulation(sim, settings, base_directory)
    return ValidationReport(**report)


@router.post("/undo", response_model=DocumentResponse)
def undo() -> DocumentResponse:
    get_store().undo()
    return get_store().to_response()


@router.post("/redo", response_model=DocumentResponse)
def redo() -> DocumentResponse:
    get_store().redo()
    return get_store().to_response()


@router.get("/settings", response_model=RuntimeSettings)
def get_settings() -> RuntimeSettings:
    return RuntimeSettings(**get_store().get().settings)


@router.put("/settings", response_model=DocumentResponse)
def update_settings(req: SettingsPatch) -> DocumentResponse:
    store = get_store()
    store.patch_settings(req.model_dump(exclude_none=True))
    return store.to_response()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_api_sim.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/routes.py tests/test_gui_api_sim.py
git commit -m "feat(gui): document/open/save/preview/discover/validate/undo/redo routes"
```

### Task D2: Topology + starting-structure routes

**Files:**
- Modify: `ambermeta/gui/api/routes.py`
- Modify: `tests/test_gui_api_sim.py`

**Interfaces:**
- Produces: `POST /topologies`, `PUT /topologies/{topology_id}`, `DELETE /topologies/{topology_id}`, `PUT /simulation/starting-structure`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gui_api_sim.py
def test_topology_routes(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/topologies", json={"path": "wt.prmtop", "kind": "hmr"})
    assert r.status_code == 200
    tid = r.json()["simulation"]["topologies"][0]["id"]
    assert r.json()["simulation"]["topologies"][0]["kind"] == "hmr"

    r = c.put(f"/api/topologies/{tid}", json={"kind": "normal"})
    assert r.json()["simulation"]["topologies"][0]["kind"] == "normal"

    r = c.put("/api/simulation/starting-structure", json={"path": "wt.inpcrd"})
    assert r.json()["simulation"]["starting_structure"] == "wt.inpcrd"

    r = c.delete(f"/api/topologies/{tid}")
    assert r.json()["simulation"]["topologies"] == []

    assert c.put("/api/topologies/bogus", json={"kind": "hmr"}).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_api_sim.py -q -k topology_routes`
Expected: FAIL (routes missing).

- [ ] **Step 3: Add the routes**

Add to `routes.py` (after `update_settings`). Note `_role_or_kind` helper for enum→str:

```python
def _enum_value(v) -> Optional[str]:
    if v is None:
        return None
    return v.value if hasattr(v, "value") else v


@router.post("/topologies", response_model=DocumentResponse)
def add_topology(req: AddTopology) -> DocumentResponse:
    store = get_store()
    doc = store.get()
    _within_base(req.path, doc.base_directory) if os.path.isabs(req.path) else None
    store.add_topology(req.path, _enum_value(req.kind) or "normal")
    return store.to_response()


@router.put("/topologies/{topology_id}", response_model=DocumentResponse)
def update_topology(topology_id: str, req: UpdateTopology) -> DocumentResponse:
    store = get_store()
    patch = {"path": req.path, "kind": _enum_value(req.kind)}
    try:
        store.update_topology(topology_id, patch)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Topology not found: {topology_id}")
    return store.to_response()


@router.delete("/topologies/{topology_id}", response_model=DocumentResponse)
def remove_topology(topology_id: str) -> DocumentResponse:
    store = get_store()
    try:
        store.remove_topology(topology_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Topology not found: {topology_id}")
    return store.to_response()


@router.put("/simulation/starting-structure", response_model=DocumentResponse)
def set_starting_structure(req: SetStartingStructure) -> DocumentResponse:
    store = get_store()
    store.set_starting_structure(req.path)
    return store.to_response()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_api_sim.py -q -k topology_routes`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/routes.py tests/test_gui_api_sim.py
git commit -m "feat(gui): topology-pool + starting-structure routes"
```

### Task D3: Phase routes

**Files:**
- Modify: `ambermeta/gui/api/routes.py`
- Modify: `tests/test_gui_api_sim.py`

**Interfaces:**
- Produces: `POST /phases`, `POST /phases/reorder` (declared BEFORE `/phases/{id}`), `PUT /phases/{phase_id}`, `DELETE /phases/{phase_id}` (query `reassign_to`).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gui_api_sim.py
def test_phase_routes(tmp_path):
    c = _client(tmp_path)
    a = c.post("/api/phases", json={"name": "Min", "role": "minimization"}).json()
    pa = a["simulation"]["phases"][0]["id"]
    b = c.post("/api/phases", json={"name": "Prod", "role": "production"}).json()
    pb = b["simulation"]["phases"][1]["id"]

    r = c.post("/api/phases/reorder", json={"phase_ids": [pb, pa]})
    assert [p["id"] for p in r.json()["simulation"]["phases"]] == [pb, pa]

    r = c.put(f"/api/phases/{pa}", json={"name": "Minimization"})
    names = {p["id"]: p["name"] for p in r.json()["simulation"]["phases"]}
    assert names[pa] == "Minimization"

    r = c.delete(f"/api/phases/{pa}")
    assert [p["id"] for p in r.json()["simulation"]["phases"]] == [pb]
    assert c.put("/api/phases/bogus", json={"name": "x"}).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_api_sim.py -q -k phase_routes`
Expected: FAIL.

- [ ] **Step 3: Add the routes**

```python
@router.post("/phases", response_model=DocumentResponse)
def create_phase(req: PhaseCreate) -> DocumentResponse:
    store = get_store()
    store.add_phase(req.name, _enum_value(req.role) or "")
    return store.to_response()


# Static sub-path BEFORE the parameterised route.
@router.post("/phases/reorder", response_model=DocumentResponse)
def reorder_phases(req: PhaseReorder) -> DocumentResponse:
    store = get_store()
    try:
        store.reorder_phases(req.phase_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return store.to_response()


@router.put("/phases/{phase_id}", response_model=DocumentResponse)
def update_phase(phase_id: str, req: PhaseUpdate) -> DocumentResponse:
    store = get_store()
    patch = {"name": req.name, "role": _enum_value(req.role)}
    try:
        store.update_phase(phase_id, patch)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Phase not found: {phase_id}")
    return store.to_response()


@router.delete("/phases/{phase_id}", response_model=DocumentResponse)
def delete_phase(phase_id: str, reassign_to: Optional[str] = Query(None)) -> DocumentResponse:
    store = get_store()
    try:
        store.delete_phase(phase_id, reassign_to=reassign_to)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Phase not found: {exc}")
    return store.to_response()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_api_sim.py -q -k phase_routes`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/routes.py tests/test_gui_api_sim.py
git commit -m "feat(gui): phase routes (create/reorder/update/delete)"
```

### Task D4: Step routes

**Files:**
- Modify: `ambermeta/gui/api/routes.py`
- Modify: `tests/test_gui_api_sim.py`

**Interfaces:**
- Produces: `POST /phases/{phase_id}/steps`, `POST /phases/{phase_id}/steps/reorder`, `PUT /steps/{step_id}` (topology clear via `model_fields_set`), `DELETE /steps/{step_id}`, `POST /steps/{step_id}/move`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gui_api_sim.py
def test_step_routes_and_topology_clear(tmp_path):
    c = _client(tmp_path)
    p = c.post("/api/phases", json={"name": "Prod", "role": "production"}).json()["simulation"]["phases"][0]["id"]
    r = c.post(f"/api/phases/{p}/steps", json={"name": "prod_001", "mdin": "prod_001.in"})
    sid = r.json()["simulation"]["phases"][0]["steps"][0]["id"]

    # set then clear topology (explicit null must clear)
    c.put(f"/api/steps/{sid}", json={"topology": "t0"})
    assert _step(c, sid)["topology"] == "t0"
    c.put(f"/api/steps/{sid}", json={"topology": None})
    assert _step(c, sid)["topology"] is None
    # absent topology must NOT clear
    c.put(f"/api/steps/{sid}", json={"topology": "t9"})
    c.put(f"/api/steps/{sid}", json={"name": "prod_001b"})
    assert _step(c, sid)["topology"] == "t9" and _step(c, sid)["name"] == "prod_001b"

    r = c.request("DELETE", f"/api/steps/{sid}")
    assert r.json()["simulation"]["phases"][0]["steps"] == []


def _step(c, sid):
    doc = c.get("/api/document").json()
    for ph in doc["simulation"]["phases"]:
        for s in ph["steps"]:
            if s["id"] == sid:
                return s
    raise AssertionError("step not found")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_api_sim.py -q -k step_routes`
Expected: FAIL.

- [ ] **Step 3: Add the routes**

```python
@router.post("/phases/{phase_id}/steps", response_model=DocumentResponse)
def create_step(phase_id: str, req: StepCreate) -> DocumentResponse:
    store = get_store()
    fields = {
        "name": req.name, "topology": req.topology,
        "input_coords": req.input_coords.model_dump() if req.input_coords else None,
        "mdin": req.mdin, "mdout": req.mdout, "mdcrd": req.mdcrd,
        "expected_gap_ps": req.expected_gap_ps, "gap_tolerance_ps": req.gap_tolerance_ps,
        "notes": list(req.notes),
    }
    try:
        store.add_step(phase_id, fields)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Phase not found: {phase_id}")
    return store.to_response()


@router.post("/phases/{phase_id}/steps/reorder", response_model=DocumentResponse)
def reorder_steps(phase_id: str, req: StepReorder) -> DocumentResponse:
    store = get_store()
    try:
        store.reorder_steps(phase_id, req.step_ids)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Phase not found: {phase_id}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return store.to_response()


@router.put("/steps/{step_id}", response_model=DocumentResponse)
def update_step(step_id: str, req: StepUpdate) -> DocumentResponse:
    store = get_store()
    patch = {}
    if req.name is not None:
        patch["name"] = req.name
    if "topology" in req.model_fields_set:      # present (incl. null) => set/clear
        patch["topology"] = req.topology
    if req.input_coords is not None:
        patch["input_coords"] = req.input_coords.model_dump()
    if req.files is not None:
        for slot in ("mdin", "mdout", "mdcrd"):
            val = getattr(req.files, slot, None)
            if val is not None:
                patch[slot] = val
    if req.expected_gap_ps is not None:
        patch["expected_gap_ps"] = req.expected_gap_ps
    if req.gap_tolerance_ps is not None:
        patch["gap_tolerance_ps"] = req.gap_tolerance_ps
    if req.notes is not None:
        patch["notes"] = list(req.notes)
    try:
        store.update_step(step_id, patch)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Step not found: {step_id}")
    return store.to_response()


@router.delete("/steps/{step_id}", response_model=DocumentResponse)
def delete_step(step_id: str) -> DocumentResponse:
    store = get_store()
    try:
        store.delete_step(step_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Step not found: {step_id}")
    return store.to_response()


@router.post("/steps/{step_id}/move", response_model=DocumentResponse)
def move_step(step_id: str, req: StepMove) -> DocumentResponse:
    store = get_store()
    try:
        store.move_step(step_id, req.phase_id, req.index)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {exc}")
    return store.to_response()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_api_sim.py -q -k step_routes`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/routes.py tests/test_gui_api_sim.py
git commit -m "feat(gui): step routes (create/reorder/update-with-clear/delete/move)"
```

### Task D5: Unified `/assign` + file routes; delete stale `test_gui_api.py`

**Files:**
- Modify: `ambermeta/gui/api/routes.py`
- Modify: `tests/test_gui_api_sim.py`
- Delete/replace: `tests/test_gui_api.py` (asserts the removed flat `/stages` contract)

**Interfaces:**
- Produces: `POST /assign`, `GET /files`, `GET /files/metadata`, `GET /files/raw`, `GET /files/related/{stem:path}`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gui_api_sim.py
def test_assign_and_file_routes(tmp_path):
    (tmp_path / "wt.prmtop").write_text("dummy")
    (tmp_path / "min.in").write_text("&cntrl\nimin=1,\n/\n")
    c = _client(tmp_path)
    p = c.post("/api/phases", json={"name": "Min", "role": "minimization"}).json()["simulation"]["phases"][0]["id"]
    s = c.post(f"/api/phases/{p}/steps", json={"name": "min"}).json()["simulation"]["phases"][0]["steps"][0]["id"]

    r = c.post("/api/assign", json={"path": "wt.prmtop", "target_type": "step_topology", "target_id": s})
    assert r.status_code == 200
    assert c.get("/api/document").json()["simulation"]["topologies"][0]["path"] == "wt.prmtop"

    r = c.post("/api/assign", json={"path": "min.in", "target_type": "step_slot", "target_id": s, "slot": "mdin"})
    assert _step(c, s)["mdin"] == "min.in"

    r = c.get("/api/files")
    assert r.status_code == 200 and any(f["name"] == "wt.prmtop" for f in r.json())

    r = c.get("/api/files/raw", params={"path": "min.in"})
    assert r.status_code == 200 and "imin=1" in r.json()["content"]

    assert c.post("/api/assign", json={"path": "x", "target_type": "bogus"}).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_api_sim.py -q -k assign_and_file`
Expected: FAIL.

- [ ] **Step 3: Add the routes; delete the stale test file**

```python
@router.post("/assign", response_model=DocumentResponse)
def assign(req: AssignRequest) -> DocumentResponse:
    store = get_store()
    try:
        store.assign_file(req.path, req.target_type, target_id=req.target_id,
                          kind=_enum_value(req.kind), slot=req.slot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Target not found: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return store.to_response()


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


@router.get("/files/raw", response_model=RawFile)
def get_file_raw(path: str = Query(...), max_bytes: int = Query(4096)) -> RawFile:
    doc = get_store().get()
    resolved = _within_base(path, doc.base_directory)
    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    out = core_bridge.read_file_head(resolved, max_bytes=max_bytes)
    return RawFile(path=resolved, content=out["content"], truncated=out["truncated"])
```

Also port the existing `GET /files/related/{stem:path}` route from the old `routes.py` verbatim (it is model-agnostic — it scans the filesystem, not the document). Then delete `tests/test_gui_api.py` (it asserts the removed `/stages`, `/settings` topology fields, `/link-restarts`, `/sequences` surface; its coverage is replaced by `tests/test_gui_api_sim.py`). If any assertions there cover file-tree/security behavior still present, move those specific tests into `tests/test_gui_api_sim.py` instead of deleting them.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_api_sim.py -q && pytest -q`
Expected: PASS (whole suite green; confirm no remaining references to removed endpoints/functions).

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/routes.py tests/test_gui_api_sim.py
git rm tests/test_gui_api.py
git commit -m "feat(gui): unified /assign + file routes (raw head, metadata, related); drop flat API tests"
```

---

## Self-Review — spec §5 coverage

- **Topology pool CRUD + set starting structure** → B2 (store) + D2 (routes). ✓
- **Phases (CRUD, reorder)** → B3 + D3. ✓
- **Steps (CRUD, move-between-phases, reorder-within, topology binding, input-coords source)** → B4 + D4. ✓
- **Unified assignment op** → B5 (`assign_file`) + D5 (`POST /assign`). ✓
- **Discover-as-draft** → C2 (`discover_draft`) + D1 (`POST /document/discover` → `DiscoverResult`, applied draft-first). ✓
- **Suggestions surface (enrichment, not a separate endpoint)** → C3 (`build_suggestions`) + C4 (validation adds continuity-gap suggestions) surfaced on `DiscoverResult.suggestions` and `ValidationReport.suggestions`. ✓
- **Server-authoritative undo for all new mutations** → every store mutator `_snapshot()`s (B1–B5); `/undo`,`/redo` in D1. ✓
- **Open/save via v2 + migration** → C1 (`open_simulation`/`save_simulation`) + D1; migration exercised by the API test. ✓
- **File detail (full metadata + raw head)** → `file_metadata` kept; `read_file_head` (C5) + `GET /files/raw` (D5). ✓
- **Removed (each stated in its task):** `/stages*`, topology fields on `/settings`, `/link-restarts` (folded into discover/assign), `/sequences` (folded into suggestions). ✓

**Type consistency:** `Simulation`/`Phase`/`Step`/`Topology`/`InputCoords` dataclass field names match P1 exactly; `_sim_to_model` maps them 1:1 to the Pydantic `*Model`s; `assign_file` `target_type` values (`pool|starting_structure|phase_topology|step_topology|step_slot`) match `AssignRequest.target_type` and the D5 route; `_STEP_SLOTS = ("mdin","mdout","mdcrd")` is consistent across `document.py` and `StageFiles`; canonical `StageRole` values equal the `classify_role` tokens; `discover_draft`/`validate_simulation` return dict keys match the `Suggestion`/`ValidationReport`/`DiscoverResult` schema fields.

**Carry-forward (from P1, to address here or note again):** the P1 migration mislabels a stage-level HMR prmtop `normal` unless it was the declared HMR global — `discover_draft` avoids this by classifying the pool with `classify_topology_pool` (mass-based), so the draft path is correct; the manifest-open path still inherits P1's `migrate_v1_manifest` behavior. `validate_simulation` continuity for `source=="step"` is best-effort (documented in C4).

**Known limitation surfaced for P3/UX:** toml/csv are not valid v2 export formats (`save`/`preview` accept json/yaml only) — the P3 ExportModal must offer only those.
