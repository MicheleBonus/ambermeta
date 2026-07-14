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
