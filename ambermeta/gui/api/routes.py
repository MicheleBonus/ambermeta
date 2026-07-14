"""FastAPI routes for the AmberMeta GUI API (Simulation model)."""
import os
from pathlib import Path
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


def _guard_path(path, base: str) -> None:
    """Reject a request-supplied path that escapes the base dir (403). No-op for empty/None."""
    if path:
        _within_base(path, base)


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
    _guard_path(req.path, doc.base_directory)
    store.add_topology(req.path, _enum_value(req.kind) or "normal")
    return store.to_response()


@router.put("/topologies/{topology_id}", response_model=DocumentResponse)
def update_topology(topology_id: str, req: UpdateTopology) -> DocumentResponse:
    store = get_store()
    _guard_path(req.path, store.get().base_directory)
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
    _guard_path(req.path, store.get().base_directory)
    store.set_starting_structure(req.path)
    return store.to_response()


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


@router.post("/phases/{phase_id}/steps", response_model=DocumentResponse)
def create_step(phase_id: str, req: StepCreate) -> DocumentResponse:
    store = get_store()
    base_directory = store.get().base_directory
    _guard_path(req.mdin, base_directory)
    _guard_path(req.mdout, base_directory)
    _guard_path(req.mdcrd, base_directory)
    _guard_path(req.input_coords.path if req.input_coords else None, base_directory)
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
    base_directory = store.get().base_directory
    if req.files is not None:
        _guard_path(req.files.mdin, base_directory)
        _guard_path(req.files.mdout, base_directory)
        _guard_path(req.files.mdcrd, base_directory)
    if req.input_coords is not None:
        _guard_path(req.input_coords.path, base_directory)
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


@router.post("/assign", response_model=DocumentResponse)
def assign(req: AssignRequest) -> DocumentResponse:
    store = get_store()
    _guard_path(req.path, store.get().base_directory)
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
