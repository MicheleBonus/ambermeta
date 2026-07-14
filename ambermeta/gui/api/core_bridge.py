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
from typing import Any, Dict, List, Optional

from ambermeta.manifest import (
    STAGE_FILE_KINDS,
)
from ambermeta.protocol import (
    _serialize_metadata,
    auto_discover,
)
from ambermeta.parsers import (
    PrmtopParser, MdinParser, MdoutParser, MdcrdParser, InpcrdParser,
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


# ---------------------------------------------------------------------------
# Task 4: validation report, file metadata, restart chain
# ---------------------------------------------------------------------------

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
        meta = _serialize_metadata(parsed)
    except Exception as exc:  # parser raises a variety of errors; surface, don't crash
        return {"details": None, "warnings": [f"Could not parse file: {exc}"],
                "kind": kind}
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


def read_file_head(path, max_bytes=4096):
    with open(path, "rb") as fh:
        data = fh.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    return {"content": data[:max_bytes].decode("utf-8", errors="replace"),
            "truncated": truncated}


# ---------------------------------------------------------------------------
# Task C1: open / save / preview via P1's simulation module (v2 manifests)
# ---------------------------------------------------------------------------


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


def _flatten_simulation(sim):
    """Flatten a Simulation into the flat stage dicts the validation engine expects."""
    topo_by_id = {t.id: t.path for t in sim.topologies}
    flat = []
    for p in sim.phases:
        for s in p.steps:
            if s.input_coords.path:                # explicit path OR a resolved chained restart
                inpcrd = s.input_coords.path
            elif s.input_coords.source == "starting_structure":
                inpcrd = sim.starting_structure
            else:                                  # "step" with no resolved restart path
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
    prev_restart = None   # previous run's output restart (its stem group's inpcrd/.rst)
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
            # chained: input coords ARE the previous run's output restart —
            # store the resolved path so continuity can read its time.
            ic = InputCoords(source="step", ref=prev_step_id,
                             path=_relativize(prev_restart, base_directory) if prev_restart else None)
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
        prev_restart = kinds.get("inpcrd")   # this run's output restart, for the next step

    warnings = []
    if len(sim.topologies) > 1:
        warnings.append(f"{len(sim.topologies)} topologies found; confirm normal vs HMR.")
    return {"simulation": sim, "suggestions": build_suggestions(sim, base_directory),
            "warnings": warnings}
