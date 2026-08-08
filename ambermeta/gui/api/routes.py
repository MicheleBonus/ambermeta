"""FastAPI routes for the AmberMeta GUI API (Simulation model)."""
import os
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from ambermeta.errors import AmberMetaError
from ambermeta.simulation import InputCoords, crosses_lineage, iter_steps

from . import core_bridge, files
from .document import DocumentStore
from .schemas import (
    DocumentResponse, RuntimeSettings, SettingsPatch, OpenRequest, SaveRequest, SaveResult,
    DiscoverRequest, DiscoverResult, PreviewRequest, PreviewResponse,
    AddTopology, UpdateTopology, SetStartingStructure, PhaseCreate, PhaseUpdate, PhaseReorder,
    StepCreate, StepUpdate, StepMove, StepReorder, StepsLineage, AssignRequest,
    ValidationReport,
    FileMetadata, FileInfo, RawFile, Suggestion, PlanRequest, PlanResult,
    LineageProposal, InferLineagesRequest, LineageProposalResponse,
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
    except (FileNotFoundError, ValueError, TypeError, ImportError, AmberMetaError) as exc:
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
    """Scan the base directory into a fresh draft. Proposes a lineage grouping; writes none
    of it. `discover_draft(..., apply_tags=False)` is what makes that true here — the CLI's
    own `discover` calls the same function with the opposite default and writes it straight
    onto the steps, because a manifest it writes with `--write` is the user's confirmation
    and the GUI's PATCH /steps/lineage is the GUI's.
    """
    store = get_store()
    sim0, settings, manifest_path, base_directory = store.snapshot()
    _within_base(base_directory, base_directory)
    out = core_bridge.discover_draft(base_directory, recursive=req.recursive,
                                     pattern=req.pattern, apply_tags=False)

    # Discover replaces the document wholesale, so re-running it -- the natural reflex
    # after adding files to a campaign, and the most prominent button in the top bar --
    # silently discarded every tag the user had declared. Recoverable with Ctrl+Z because
    # reset_history=False, but nothing in the UI said so.
    #
    # Matched on Step.name, the path-prefixed run stem: step ids are freshly generated on
    # every scan (core_bridge.discover_draft mints a new uuid4 per step), so they cannot
    # identify anything across one. Re-applied to the fresh scan's OWN Simulation object,
    # in memory, before it is ever handed to `store.replace` -- so the whole operation
    # still costs the single undo frame Discover always cost. Doing this afterwards through
    # a loop of `PATCH /steps/lineage`-style writes would push one snapshot per tag and
    # evict the very Discover result being annotated (`set_lineages`' docstring records
    # this same trap for the bulk-tag route).
    previous = {step.name: step.lineage for _, step in iter_steps(sim0) if step.lineage}
    for _, step in iter_steps(out["simulation"]):
        tag = previous.pop(step.name, None)
        if tag is not None:
            step.lineage = tag
    # Whatever is left in `previous` names a run that carried a tag last scan and did not
    # come back this time -- moved, renamed, or deleted out from under it. Reported below
    # rather than silently dropped.
    dropped = sorted(previous)

    # The tags were carried; the ACCEPTED HANDOFFS were not, and they were the other half
    # of the same declaration. A user who accepted the proposal strip's five
    # `equil/NN -> prod/NN` edges and then re-Discovered got all five deleted, with
    # `warnings: []` -- verified end to end: 3 cross-directory edges after Accept, 0 after
    # re-Discover, nothing said. The fresh draft cannot rebuild them, and that is
    # deliberate rather than an oversight to route around: `discover_draft` chains WITHIN a
    # run directory only, because a restart sitting in another directory is not evidence
    # that this run read it. The mdout's File Assignments block is that evidence, and the
    # handoff proposal is where it is offered -- as a PROPOSAL, accepted by hand. So the
    # edge exists in the document for exactly one reason: the user put it there.
    #
    # Scoped to CROSS-DIRECTORY edges on purpose. Within one directory the fresh scan
    # rebuilds the chunked chain itself, and carrying those forward would fight it: an
    # edge the user deliberately removed (or rerouted around a run that turned out not to
    # have produced anything) would be reinstated by this loop over the top of the scan's
    # own, better-informed answer. Cross-directory is precisely the set the scan never
    # asserts, so carrying it can only restore, never contradict.
    #
    # Matched on Step.name for the same reason the tags are: ids are freshly minted per
    # scan. Applied to the fresh scan's own objects before `store.replace`, so this still
    # costs the one undo frame Discover has always cost.
    steps0 = {step.name: step for _, step in iter_steps(sim0)}
    by_name0 = {step.id: step.name for _, step in iter_steps(sim0)}
    carried_edges: Dict[str, str] = {}
    for name, step in steps0.items():
        ic = step.input_coords
        if ic is None or ic.source != "step" or not ic.ref:
            continue
        producer_name = by_name0.get(ic.ref)
        if producer_name is None:
            continue
        if producer_name.rpartition("/")[0] != name.rpartition("/")[0]:
            carried_edges[name] = producer_name

    fresh_by_name = {step.name: step for _, step in iter_steps(out["simulation"])}
    lost_edges: List[str] = []
    for consumer_name, producer_name in sorted(carried_edges.items()):
        consumer = fresh_by_name.get(consumer_name)
        producer = fresh_by_name.get(producer_name)
        if consumer is None or producer is None:
            # One end of the edge is not in this scan. Nothing to re-point at, and the
            # user's declaration is being discarded either way -- so it is REPORTED. A
            # silently dropped declaration is the one outcome that is not acceptable here.
            lost_edges.append(f"{consumer_name} <- {producer_name}")
            continue
        consumer.input_coords = InputCoords(source="step", ref=producer.id)

    # Carrying a tag back onto the fresh scan can turn one of discovery's own directory-wide
    # chain edges into a claim that one member continues another -- the exact cross-lineage
    # restart edge `DocumentStore._sever_crossed_refs` exists to remove, and which a bare
    # `store.replace` below does NOT run (it only clears warnings and swaps the document).
    # Without this pass, re-Discovering after `PATCH /steps/lineage` had just severed such an
    # edge and warned about it would silently re-create precisely that edge and stamp the
    # carried tags on top -- the one fact simulation.py's module docstring forbids any
    # automatic operation from inventing. No "was this already crossing before" check is
    # needed here (contrast `_sever_crossed_refs`, which keeps a pre-existing declared
    # branch): every step in a fresh `apply_tags=False` scan starts untagged, so nothing can
    # be crossing before the loop above runs, and anything crossing after it is new.
    #
    # Runs AFTER the carried handoff edges above, not just after the carried tags, and that
    # ordering is load-bearing. A carried edge lands on the fresh scan's own objects and is
    # then subject to exactly the same rule as one the scan built: if the tags now say its
    # two ends are different members, it is severed and reported, rather than surviving into
    # a grouping that forbids it because it happened to arrive by a different route.
    #
    # Applied unconditionally, which does cost one thing worth naming: a deliberately
    # DECLARED cross-lineage branch (`_check_continues_from` accepts one, and
    # `_sever_crossed_refs` protects it by comparing against what was crossing before) is
    # severed by a re-Discover rather than preserved. That is still strictly better than
    # what happened before this carry-forward existed -- the edge was deleted outright with
    # `warnings: []` -- because it is now severed WITH the "no longer continues ... Set its
    # input coordinates if that is wrong" line, which is exactly the sentence that tells a
    # user to put it back. Preserving it instead would mean reproducing `_sever_crossed_refs`'
    # before/after comparison here, and no Discover result may carry a cross-lineage step
    # ref: that invariant is what the whole partitioned continuity check rests on.
    by_id = {s.id: s for _, s in iter_steps(out["simulation"])}
    severed: List[str] = []
    for _, step in iter_steps(out["simulation"]):
        ic = step.input_coords
        if ic is None or ic.source != "step" or not ic.ref:
            continue
        producer = by_id.get(ic.ref)
        if producer is not None and crosses_lineage(producer, step):
            step.input_coords = InputCoords(source="starting_structure")
            severed.append(
                f"{step.name} no longer continues {producer.name}: they are "
                "different lineages. Set its input coordinates if that is wrong.")

    # This report cannot go through `DocumentResponse.warnings` -- `store.replace` below
    # clears that field first thing, and docs/gui.md states as a contract that Discover
    # always reports an empty list there. It goes in `DiscoverResult.warnings` instead,
    # the channel that already carries this route's own findings (e.g. the topology-count
    # note) back to the toasts `useDiscover` renders.
    warnings = list(out["warnings"])
    if dropped:
        warnings.append(
            f"{len(dropped)} run(s) carried a lineage tag that this scan did not find "
            f"again, so their tags were dropped: {', '.join(dropped[:5])}"
            + (" ..." if len(dropped) > 5 else ""))
    if lost_edges:
        warnings.append(
            f"{len(lost_edges)} declared cross-directory restart handoff(s) could not be "
            f"carried forward -- one end of each is not in this scan: "
            f"{', '.join(lost_edges[:5])}" + (" ..." if len(lost_edges) > 5 else ""))
    warnings.extend(severed)

    store.replace(simulation=out["simulation"], settings=settings,
                  manifest_path=manifest_path, dirty=True, reset_history=False)
    return DiscoverResult(
        document=store.to_response(),
        suggestions=[Suggestion(**s) for s in out["suggestions"]],
        # `out["proposal"]` is already the exact shape `LineageProposal` declares
        # (`core_bridge.build_lineage_proposal`'s return); `None` passes through as `None`
        # rather than as `LineageProposal(**None)`, which would raise.
        proposal=LineageProposal(**out["proposal"]) if out["proposal"] else None,
        warnings=warnings)


@router.post("/plan", response_model=PlanResult)
def plan_document(req: PlanRequest) -> PlanResult:
    """Write the artifacts `ambermeta plan` writes, from the document held in memory.

    Optionally saves the manifest in the same call, so "build it, then plan it" is one
    action in the GUI rather than a save followed by a trip to a terminal.
    """
    store = get_store()
    sim, settings, manifest_path, base_directory = store.snapshot()

    # --- validate everything before writing anything --------------------------
    targets: dict = {}
    for artifact, raw in (("summary", req.summary_path),
                          ("methods_summary", req.methods_summary_path),
                          ("stats_csv", req.stats_csv_path)):
        if raw:
            targets[artifact] = _within_base(raw, base_directory)
    resolved_manifest = (_within_base(req.save_manifest_path, base_directory)
                         if req.save_manifest_path else None)
    if not targets and resolved_manifest is None:
        raise HTTPException(status_code=400, detail="Nothing to write: choose at least one output.")
    if req.summary_format not in ("json", "yaml"):
        # Checked here, not inside the writer: a bad format used to be discovered after
        # the manifest had already been written and marked saved.
        raise HTTPException(status_code=400,
                            detail=f"summary format must be json or yaml, got: {req.summary_format}")

    # Two artifacts aimed at one file silently destroyed each other, and the survivor was
    # still reported as both. The manifest lost that race, leaving the document "saved" to
    # a summary that cannot be reopened.
    # normcase: a no-op on POSIX, lowercases (and normalizes slashes) on Windows, where
    # S.json and s.json name the same NTFS file — comparing the raw strings let two
    # artifacts "land" on distinct strings but one physical file. The message still names
    # the paths the caller actually asked for.
    all_paths = list(targets.values()) + ([resolved_manifest] if resolved_manifest else [])
    normed = [os.path.normcase(p) for p in all_paths]
    dupe_keys = {k for k in normed if normed.count(k) > 1}
    duplicates = sorted({p for p in all_paths if os.path.normcase(p) in dupe_keys})
    if duplicates:
        raise HTTPException(
            status_code=400,
            detail="Each output needs its own file; more than one is aimed at "
                   + ", ".join(duplicates))

    # --- write ----------------------------------------------------------------
    warnings: List[str] = []
    written: List[dict] = []
    if resolved_manifest:
        fmt = core_bridge.resolve_format(resolved_manifest, None)
        try:
            warnings.extend(core_bridge.save_simulation(sim, base_directory, resolved_manifest, fmt))
        except (RuntimeError, ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=f"Could not save manifest: {exc}")
        store.mark_saved(resolved_manifest)
        written.append({"artifact": "manifest", "path": resolved_manifest})

    out = core_bridge.write_plan_outputs(sim, settings, base_directory, targets,
                                         summary_format=req.summary_format)
    written.extend(out["written"])
    return PlanResult(written=written, failed=out["failed"],
                      warnings=warnings + out["warnings"],
                      stage_count=out["stage_count"], totals=out["totals"],
                      suggestions=[Suggestion(**s) for s in out["suggestions"]],
                      lineages=out["lineages"],
                      document=store.to_response())


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
    if "topology" in req.model_fields_set:      # present (incl. null) => set/clear on every step
        patch["topology"] = req.topology
    try:
        store.update_phase(phase_id, patch)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {exc}")
    return store.to_response()


@router.delete("/phases/{phase_id}", response_model=DocumentResponse)
def delete_phase(phase_id: str, reassign_to: Optional[str] = Query(None)) -> DocumentResponse:
    store = get_store()
    try:
        store.delete_phase(phase_id, reassign_to=reassign_to)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Phase not found: {exc}")
    except ValueError as exc:               # e.g. reassign_to == the phase being deleted
        raise HTTPException(status_code=400, detail=str(exc))
    return store.to_response()


@router.post("/phases/{phase_id}/steps", response_model=DocumentResponse)
def create_step(phase_id: str, req: StepCreate) -> DocumentResponse:
    store = get_store()
    base_directory = store.get().base_directory
    _guard_path(req.mdin, base_directory)
    _guard_path(req.mdout, base_directory)
    _guard_path(req.mdcrd, base_directory)
    _guard_path(req.rst, base_directory)
    _guard_path(req.input_coords.path if req.input_coords else None, base_directory)
    fields = {
        "name": req.name, "topology": req.topology,
        "input_coords": req.input_coords.model_dump() if req.input_coords else None,
        "mdin": req.mdin, "mdout": req.mdout, "mdcrd": req.mdcrd, "rst": req.rst,
        "lineage": req.lineage,
        "expected_gap_ps": req.expected_gap_ps, "gap_tolerance_ps": req.gap_tolerance_ps,
        "notes": list(req.notes),
    }
    try:
        store.add_step(phase_id, fields, index=req.index)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Phase not found: {phase_id}")
    except ValueError as exc:       # the same impossible "continues from" PUT /steps refuses
        raise HTTPException(status_code=400, detail=str(exc))
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
        _guard_path(req.files.rst, base_directory)
    if req.input_coords is not None:
        _guard_path(req.input_coords.path, base_directory)
    patch = {}
    if req.name is not None:
        patch["name"] = req.name
    if "topology" in req.model_fields_set:      # present (incl. null) => set/clear
        patch["topology"] = req.topology
    if "lineage" in req.model_fields_set:       # present (incl. null) => set/clear
        patch["lineage"] = req.lineage
    if req.input_coords is not None:
        patch["input_coords"] = req.input_coords.model_dump()
    if req.files is not None:
        for slot in ("mdin", "mdout", "mdcrd", "rst"):
            val = getattr(req.files, slot, None)
            if val is not None:
                patch[slot] = val
    for gap in ("expected_gap_ps", "gap_tolerance_ps"):
        if gap in req.model_fields_set:         # present (incl. null) => set/clear
            patch[gap] = getattr(req, gap)
    if req.notes is not None:
        patch["notes"] = list(req.notes)
    try:
        store.update_step(step_id, patch)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Step not found: {step_id}")
    except ValueError as exc:       # a self-reference, or a "continues from" nobody holds
        raise HTTPException(status_code=400, detail=str(exc))
    return store.to_response()


@router.patch("/steps/lineage", response_model=DocumentResponse)
def set_step_lineages(req: StepsLineage) -> DocumentResponse:
    """Tag every step in `ids` in one edit and one undo entry.

    PATCH rather than PUT because the collection is not being replaced, and because it
    keeps this path from competing with `/steps/{step_id}`: `lineage` is a perfectly good
    step id as far as that pattern is concerned, and FastAPI resolves in declaration order
    within a method. Should a PATCH on a single step ever be added, it must be declared
    after this one.
    """
    store = get_store()
    try:
        store.set_lineages(req.ids, req.lineage)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Step not found: {exc.args[0]}")
    return store.to_response()


@router.post("/steps/infer-lineages", response_model=LineageProposalResponse)
def infer_lineages(req: InferLineagesRequest = InferLineagesRequest()) -> LineageProposalResponse:
    """Propose a grouping for the OPEN document. Writes nothing.

    Re-runs the layout inference — or, given `segment_index`, the picker's "try this
    column" — over the document's own step names, so this works whether the document came
    from a fresh scan, a reopened manifest, or steps built by hand; not just the tree
    `discover` last touched. Accepting what comes back is a separate step the caller takes
    explicitly, one `PATCH /steps/lineage` per member — this route never calls it.

    Reports through the same shape on both outcomes (a `LineageProposalResponse`, not a
    `DocumentResponse`) rather than through the general edit-warnings channel every other
    route uses: there is no edit here to report warnings ABOUT.

    `base_directory` is passed so the response carries `handoffs` too. Without it this
    route returned a proposal with none, and `ProposalStrip.pickSegment` replaces the shown
    proposal wholesale -- so a user who opened `Change`, glanced at another column and
    tapped back lost every handoff row with no message. Handoffs are member-scoped, so the
    right answer is to re-propose them against the grouping now being shown rather than to
    have the frontend hold the previous column's ones over the top of different members.
    """
    store = get_store()
    sim, _settings, _manifest_path, base_directory = store.snapshot()
    proposal = core_bridge.build_lineage_proposal(
        sim, segment_index=req.segment_index, base_directory=base_directory)
    if proposal is None:
        return LineageProposalResponse(proposal=None, warnings=[
            "No lineages inferred: the directory layout could not be resolved into one "
            "unambiguous set of members. Use Define replicas… to pick the segment "
            "yourself."])
    return LineageProposalResponse(proposal=LineageProposal(**proposal), warnings=[])


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
