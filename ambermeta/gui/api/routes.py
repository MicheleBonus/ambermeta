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
