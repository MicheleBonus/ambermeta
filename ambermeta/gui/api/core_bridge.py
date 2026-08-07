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
        # This whitelist is the gate: a key that is not copied out here never reaches
        # _manifest_to_stages, so tagging the step and flattening the tag would both be
        # silent no-ops without these four lines. `lineage` and `status` are really
        # conditional — `step_id` is set on every step and `parent_id` on every chained
        # one, so every document's engine payload carries those two. That is deliberate
        # rather than sloppy: they are how a lineage head is measured against its real
        # producer, and withholding them from untagged documents would only mean
        # recomputing them the moment one tag appeared. This payload is in-memory input to
        # `auto_discover` and is never serialised, so it is not part of any on-disk shape.
        #
        # `status`'s own truthiness guard is what keeps
        # test_an_untagged_step_adds_no_key_to_the_engine_payload green: the default is
        # `None`, which is falsy, so an ordinary step contributes no `status` key here
        # either — the same emit-when-set rule `_step_payload` enforces on the document.
        for provenance in ("lineage", "step_id", "parent_id", "status"):
            val = s.get(provenance)
            if val:
                entry[provenance] = val
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


# ---------------------------------------------------------------------------
# Task 4: validation report, file metadata, restart chain
# ---------------------------------------------------------------------------

_EXT_KIND = {
    ".prmtop": "prmtop", ".top": "prmtop", ".parm7": "prmtop",
    ".mdin": "mdin", ".in": "mdin",
    ".mdout": "mdout", ".out": "mdout",
    ".mdcrd": "mdcrd", ".nc": "mdcrd", ".crd": "mdcrd", ".x": "mdcrd", ".trj": "mdcrd",
    ".inpcrd": "inpcrd", ".rst": "inpcrd", ".rst7": "inpcrd",
    ".ncrst": "inpcrd", ".restrt": "inpcrd",
}
_KIND_PARSER = {
    "prmtop": PrmtopParser, "mdin": MdinParser, "mdout": MdoutParser,
    "mdcrd": MdcrdParser, "inpcrd": InpcrdParser,
}
_DEFAULT_BASENAME_KIND = {
    "prmtop": "prmtop", "parm7": "prmtop",
    "mdin": "mdin", "mdout": "mdout", "mdcrd": "mdcrd",
    "inpcrd": "inpcrd", "restrt": "inpcrd",
}


def file_metadata(path: str) -> Dict[str, Any]:
    ext = os.path.splitext(path)[1].lower()
    kind = _EXT_KIND.get(ext, "other")
    if kind == "other" and not ext:
        kind = _DEFAULT_BASENAME_KIND.get(os.path.basename(path).lower(), "other")
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


def build_protocol(stages: List[Dict[str, Any]], settings: Dict[str, Any],
                   base_directory: str):
    """The engine's SimulationProtocol for the current document.

    The same object the CLI's ``plan`` builds, so the GUI's validation report and its
    written summaries come from one parse of the run files rather than two that could
    disagree.
    """
    payload = document_to_payload(stages, settings, base_directory)
    return auto_discover(
        base_directory,
        manifest=payload["stages"],
        global_prmtop=payload.get("global_prmtop"),
        hmr_prmtop=payload.get("hmr_prmtop"),
        skip_cross_stage_validation=not settings.get("strict_validation", True),
        allow_unexpected_gaps=settings.get("allow_gaps", False),
        auto_detect_restarts=bool(settings.get("auto_detect_restarts", False)),
        strict=bool(settings.get("strict", False)),
    )


def build_validation_report(stages: List[Dict[str, Any]], settings: Dict[str, Any],
                            base_directory: str, protocol=None) -> Dict[str, Any]:
    if protocol is None:
        protocol = build_protocol(stages, settings, base_directory)

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
            # Genuine (non-INFO) continuity problems for this stage, kept separate from
            # the general warnings so continuity_gap suggestions are driven by the
            # engine's own healthy/problem categorization, not by fuzzy text matching.
            "continuity": [c for c in sd.get("continuity", []) if not str(c).startswith("INFO:")],
            "missing_files": miss,
        })

    from ambermeta.lineages import coherence

    totals = protocol.totals()
    totals["stage_count"] = len(protocol.stages)
    findings = [{"severity": f.severity, "kind": f.kind, "message": f.message}
                for f in coherence(protocol.stages)]
    return {
        # A category error means the members are not runs of the same thing, which is not
        # a per-stage problem and so has nowhere to go in `stage_issues` — and `ok` read
        # only that. A document whose members hold different atom counts reported
        # "All checks passed".
        "ok": all(s["ok"] for s in stage_issues)
        and not any(f["severity"] == "error" for f in findings),
        "coherence": findings,
        "totals": totals,
        # None rather than {} for a single-member document: the field is Optional on the
        # model and "the document declares no members" and "every member is empty" are
        # different answers.
        "lineages": protocol.lineage_totals() or None,
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
    from ambermeta.lineages import lineages
    from ambermeta.protocol import sequence_findings

    steps = [s for p in sim.phases for s in p.steps]
    # Shared with the `plan --recursive` path, which has stages rather than a document and
    # so cannot come through here at all. One producer, one wording.
    out = sequence_findings([s.name for s in steps], [s.lineage for s in steps])

    def _sug(kind, severity, title, evidence, actions):
        return {"id": f"sug_{len(out) + 1}", "kind": kind, "severity": severity,
                "title": title, "evidence": evidence, "actions": actions}

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

    # Decision 7: the grouping is reported, never performed silently. `[applied]` and not
    # `needs_you` because there is nothing to accept — the tag is on the steps and visible
    # in the manifest, so the evidence names each member and how many runs it holds and
    # the user can read the claim back off the document.
    #
    # It says what the document declares, not where the tags came from. This function also
    # runs from validate_simulation for any open document, so a manifest whose lineages
    # were typed by hand would be told they had been read off its directories — and after
    # the fact nothing here can tell an inferred tag from a hand-written one. `discover`
    # announces its own inference by running on the draft it just built.
    #
    # The untagged runs are counted beside the declared members because the count is of
    # declared members only: left unsaid, "3 lineages" reads as covering all nine runs of
    # a campaign whose shared prep — three of those nine — carries no tag at all.
    declared = lineages(sim)
    if declared:
        untagged = [s for s in steps if not s.lineage]
        evidence = [f"{tag}: {len(runs)} run(s)" for tag, runs in declared.items()]
        if untagged:
            evidence.append(f"no lineage: {len(untagged)} run(s)")
        out.append(_sug("lineage_group", "applied",
                        f"Runs carry {len(declared)} declared lineage(s)",
                        "; ".join(evidence),
                        ["Undo"]))
    return out


def _flatten_simulation(sim):
    """Flatten a Simulation into the flat stage dicts the validation engine expects."""
    from ambermeta.simulation import resolve_input_coords

    topo_by_id = {t.id: t.path for t in sim.topologies}
    flat = []
    for p in sim.phases:
        for s in p.steps:
            # One resolver for the whole codebase: a chained step reads the restart
            # recorded on the step it continues from, so continuity still gets a real
            # file to read the time out of.
            inpcrd = resolve_input_coords(sim, s)
            flat.append({
                "name": s.name, "role": p.role, "step_id": s.id,
                # The producing step, carried as an id. `inpcrd` above is that producer's
                # restart *path*, which several steps can share, so the edge itself cannot
                # be recovered from it downstream.
                "lineage": s.lineage,
                "status": s.status,
                "parent_id": s.input_coords.ref if s.input_coords.source == "step" else None,
                "prmtop": topo_by_id.get(s.topology) if s.topology else None,
                "mdin": s.mdin, "mdout": s.mdout, "mdcrd": s.mdcrd, "inpcrd": inpcrd,
                "expected_gap_ps": s.expected_gap_ps, "gap_tolerance_ps": s.gap_tolerance_ps,
                "notes": list(s.notes),
            })
    return flat


def _continuity_gap_suggestions(flat, stage_issues, start_index=0):
    """One continuity_gap suggestion per genuine (non-INFO) continuity note on a step.

    Driven by each stage's structured ``continuity`` list — the engine already decides
    healthy vs. problem (healthy/informational notes are INFO-prefixed at the source and
    excluded upstream). This is deliberately NOT fuzzy warning-text matching: a satisfied
    "within expected window" transition is never flagged, and a real gap whose note happens
    to lack the substring "ps" (e.g. "Gap detected without stated expectation…") is never
    missed.

    flat: the _flatten_simulation output (each dict has 'step_id', same order as stage_issues).
    stage_issues: report['stage_issues'] (same order; each carries a 'continuity' list)."""
    out = []
    seen = set()
    for step, si in zip(flat, stage_issues):
        step_id = step.get("step_id")
        for note in si.get("continuity", []):
            if str(note).startswith("INFO:"):        # defensive; upstream already excludes INFO
                continue
            key = (step_id, str(note))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "id": f"sug_c_{start_index + len(out) + 1}", "kind": "continuity_gap",
                "severity": "needs_you", "title": "Continuity note", "evidence": str(note),
                "actions": ["Set as expected", "Investigate"], "step_id": step_id,
            })
    return out


def validate_simulation(sim, settings, base_directory, protocol=None):
    flat = _flatten_simulation(sim)
    report = build_validation_report(flat, dict(settings), base_directory, protocol=protocol)
    suggestions = build_suggestions(sim, base_directory)
    suggestions.extend(_continuity_gap_suggestions(flat, report.get("stage_issues", []), start_index=len(suggestions)))
    report["suggestions"] = suggestions
    return report


# ---------------------------------------------------------------------------
# plan outputs: the artifacts `ambermeta plan` writes, from the GUI's document
# ---------------------------------------------------------------------------


def write_plan_outputs(sim, settings, base_directory, targets: Dict[str, str],
                       summary_format: str = "json") -> Dict[str, Any]:
    """Build the protocol for `sim`, then write the requested artifacts.

    The writing half lives in ambermeta.protocol so the CLI shares it; keeping a
    second copy here is how the CLI ended up without mkdir and without per-artifact
    failure capture.
    """
    from ambermeta.protocol import write_protocol_outputs

    protocol = build_protocol(_flatten_simulation(sim), dict(settings), base_directory)
    result = write_protocol_outputs(protocol, targets, summary_format=summary_format)
    result["totals"] = protocol.totals()
    result["lineages"] = protocol.lineage_totals() or None
    result["stage_count"] = len(protocol.stages)
    # The response says what the artifacts say. The GUI ends up with these anyway, via the
    # revalidate its document-changed effect fires after a plan — but "the client happens
    # to ask again" is not the same as the plan result being honest about what it found.
    result["suggestions"] = build_suggestions(sim, base_directory)
    return result


def discover_draft(base_directory, recursive=True, pattern=None):
    from ambermeta.simulation import Simulation, Phase, Step, Topology, InputCoords
    from ambermeta.lineages import UNTAGGED, infer_lineages_from_layout
    from ambermeta.roles import classify_role
    from ambermeta.topology_pool import classify_topology_pool, implies_hmr
    from ambermeta.coords import sniff_coordinate_kind
    from ambermeta.protocol import smart_group_files, _run_stems, _looks_queued
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

    # The runs, collected before the loop because the tags have to exist before the chain
    # does. `_run_stems` is replica-major, so a chain threaded as the scan goes joins rep1's
    # last run to rep2's first — the false continuation this feature exists to remove — and
    # tagging the steps afterwards cannot unmake an edge already recorded.
    run_stems = _run_stems(grouped)
    tags = infer_lineages_from_layout(run_stems)
    # `members()`' rule applied to stems instead of steps: every untagged run shares one
    # bucket, and that bucket counts. A tree the inference refused therefore has exactly
    # one member and takes the single flat chain and contiguous phases it always had.
    multi_lineage = len({tags.get(stem) or UNTAGGED for stem in run_stems}) >= 2

    prev_by_lineage = {}
    # Where each member's previous step landed. A phase lookup that may only start here
    # can never move a member backwards, which is what keeps its steps in order.
    phase_index_by_lineage = {}
    for stem in run_stems:
        kinds = grouped[stem]
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
        tag = tags.get(stem)
        member = tag or UNTAGGED
        prev_step_id = prev_by_lineage.get(member)
        if prev_step_id is None:
            # The first run of each member reads what tLEaP wrote alongside the topology.
            # Which member is the point: one flat "is this the first run at all?" test is
            # what chained replica 2 onto replica 1.
            ic = InputCoords(source="starting_structure")
        else:
            # Chained: this run's input coords ARE the previous run's output restart.
            # The path lives on that producing step's `rst`, so the link is the ref alone
            # and the file is named once rather than copied onto every consumer.
            ic = InputCoords(source="step", ref=prev_step_id)
        # Same rule the engine uses (`_looks_queued`), reused rather than reimplemented: an
        # mdin declared with no mdout beside it, EXCEPT a same-extension file that never
        # was a real AMBER input (`sys021_tree`'s stray `cpptraj.in`) -- `mdin_details`
        # above is already the parse this needs, so no second file read is spent on it.
        status = "queued" if _looks_queued(
            mdin_details, bool(kinds.get("mdin")), bool(kinds.get("mdout"))) else None
        step = Step(
            id=uuid.uuid4().hex[:8], name=stem, topology=topology, input_coords=ic,
            mdin=_relativize(kinds.get("mdin"), base_directory),
            mdout=_relativize(kinds.get("mdout"), base_directory),
            mdcrd=_relativize(kinds.get("mdcrd"), base_directory),
            # A run's single-frame coordinate sibling is the restart it wrote (-r restrt),
            # which is exactly what the next run reads.
            rst=_relativize(kinds.get("inpcrd"), base_directory),
            lineage=tag, status=status,
        )
        if multi_lineage:
            # One phase per role, shared by every member. Left contiguous, the replica-major
            # ordering opens a phase per role PER member — nine phases for three replicas of
            # three roles, three of them named "Minimization" — which is not a grouping of
            # anything and leaves the canvas no place to show a member.
            #
            # Searched forward from where this member last landed rather than looked up by
            # role, because a role can recur: a member running min -> heat -> min has a
            # second minimisation that belongs after its heating, and a plain role->phase
            # map hoists it back into the first "Minimization". That reorders the member's
            # steps inside the document, which both breaks the chain — a step then reads a
            # restart written by a step that follows it — and changes which consecutive
            # pairs continuity compares. Starting the search AT the last index, not after
            # it, is what still lets a genuinely contiguous repeat (prod_0001, prod_0002)
            # share one phase.
            start = phase_index_by_lineage.get(member, 0)
            index = next((i for i in range(start, len(sim.phases))
                          if sim.phases[i].role == role), None)
            if index is None:
                index = len(sim.phases)
                sim.phases.append(Phase(id=uuid.uuid4().hex[:8],
                                        name=(role.title() if role else "Stage"), role=role))
            phase = sim.phases[index]
            phase_index_by_lineage[member] = index
        else:
            if not sim.phases or sim.phases[-1].role != role:
                sim.phases.append(Phase(id=uuid.uuid4().hex[:8],
                                        name=(role.title() if role else "Stage"), role=role))
            phase = sim.phases[-1]
        phase.steps.append(step)
        prev_by_lineage[member] = step.id

    warnings = []
    if len(sim.topologies) > 1:
        warnings.append(f"{len(sim.topologies)} topologies found; confirm normal vs HMR.")
    return {"simulation": sim, "suggestions": build_suggestions(sim, base_directory),
            "warnings": warnings}
