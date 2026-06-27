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

from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
from ambermeta.manifest import (
    STAGE_FILE_KINDS,
    load_manifest,
    write_manifest,
)
from ambermeta.protocol import (
    _ordered_stems,
    infer_stage_role_from_path,
    smart_group_files,
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


# ---------------------------------------------------------------------------
# Task 3: discovery + HMR/normal topology split
# ---------------------------------------------------------------------------

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
