"""FastAPI routes for the AmberMeta GUI API (server-authoritative document)."""
import os
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from . import core_bridge, files
from .document import DocumentStore
from .schemas import (
    DocumentResponse, GlobalSettings, OpenRequest, SaveRequest, SaveResult,
    DiscoverRequest, PreviewRequest, PreviewResponse,
    StageCreate, StageUpdate, StageReorderRequest, BulkStageUpdate, SettingsPatch,
    ValidationReport, FileMetadata, FileInfo,
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


# Static sub-paths must come BEFORE parameterised routes to avoid shadowing.
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
