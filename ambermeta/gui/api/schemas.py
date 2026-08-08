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
    rst: Optional[str] = None            # the restart this step writes; the next step reads it
    # Which run lineage (replica, branch, pose) this step belongs to; null is the implicit
    # single member. Three routes write it -- POST /phases/{id}/steps (routes.py:391),
    # PUT /steps/{id} (routes.py:432-433) and PATCH /steps/lineage -- as does editing the
    # manifest. The CLI's `discover` applies inferred tags directly; the GUI's Discover only
    # *proposes* them and re-applies ones already declared, inventing none of its own.
    # Nothing about this field is display-only.
    lineage: Optional[str] = None
    # Whether this run produced output. The only value ever emitted is "queued": an mdin
    # that was set up and never executed. Written by discover's scan (core_bridge) and
    # read from the manifest; unlike `lineage` above, no route accepts it, so this one
    # really is read-only at the HTTP surface.
    status: Optional[str] = None
    # The coordinate file this step actually reads, resolved through the chain. Read-only:
    # the GUI shows it without re-implementing the resolution rules.
    resolved_input_coords: Optional[str] = None
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
    # What the last edit could not do without inventing a link the user never declared:
    # a shared parent deleted out from under several lineages, a hand-set "continues from"
    # that crosses one. Describes the edit, not the document, so the next edit clears it.
    warnings: List[str] = Field(default_factory=list)


# ---- request models ----

class StageFiles(BaseModel):
    """Per-step run files (topology/input coords are handled separately).

    ``rst`` is the restart the step writes, so it belongs with the run's other outputs.
    The empty string clears a slot; absent leaves it alone.
    """
    mdin: Optional[str] = None
    mdout: Optional[str] = None
    mdcrd: Optional[str] = None
    rst: Optional[str] = None


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
    # `topology` uses model_fields_set in the route: absent = leave, null = clear it on
    # every step of the phase. A phase has no topology of its own — it is the one control
    # that sets (or unsets) the topology of all its steps at once.
    name: Optional[str] = None
    role: Optional[StageRole] = None
    topology: Optional[str] = None


class PhaseReorder(BaseModel):
    phase_ids: List[str]


class StepCreate(BaseModel):
    name: str
    topology: Optional[str] = None
    input_coords: Optional[InputCoordsModel] = None
    mdin: Optional[str] = None
    mdout: Optional[str] = None
    mdcrd: Optional[str] = None
    rst: Optional[str] = None
    lineage: Optional[str] = None
    # Where in the phase the step lands. An index inside the phase places the step exactly
    # there, the same position StepMove's would, so the two ways of placing a step do not
    # disagree about what index 0 means. -1 — or any index outside the phase — appends,
    # and appends within the step's own lineage: after that lineage's last step in the
    # phase, or at the end when the phase holds none of it.
    index: int = -1
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: List[str] = Field(default_factory=list)


class StepUpdate(BaseModel):
    # `topology`, `expected_gap_ps` and `gap_tolerance_ps` use model_fields_set in the
    # route: absent = leave, null = clear. Without that an explicit null was silently
    # dropped, so a gap once set could never be removed — only overwritten with 0.
    name: Optional[str] = None
    topology: Optional[str] = None
    # `PUT /steps/{id}` writes this (routes.py:432-433, present-vs-absent like `topology`):
    # `tests/test_gui_bulk_lineage.py:59-65` drives it with {"lineage": "rep9"}. Declared as
    # a top-level field so it inherits `topology`'s presence semantics rather than `files`'
    # ""-clears rule — a lineage is a label, not a file slot. This comment used to say the
    # tag was read-only here — true when PR 2a wrote it, false since PR 2b gave this route
    # a write path and never came back to fix the comment — which is the likeliest reason
    # the frontend never grew a tagging control of its own.
    lineage: Optional[str] = None
    input_coords: Optional[InputCoordsModel] = None
    files: Optional[StageFiles] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: Optional[List[str]] = None


class StepsLineage(BaseModel):
    """Tag many steps at once. `lineage: null` clears the tag on all of them.

    An explicit id list, not a phase: `discover` groups same-role runs from every member
    into one phase, so a phase-scoped write would give every replica the same tag.
    """
    ids: List[str]
    lineage: Optional[str] = None


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
    slot: Optional[str] = None            # for step_slot: mdin|mdout|mdcrd|rst


class PlanRequest(BaseModel):
    """Which of `ambermeta plan`'s artifacts to write, and where.

    A path of `None` means "do not write this one", so the GUI sends the same shape
    whether one box or three are ticked.
    """
    summary_path: Optional[str] = None
    methods_summary_path: Optional[str] = None
    stats_csv_path: Optional[str] = None
    summary_format: str = "json"          # json | yaml; the methods summary is always JSON
    save_manifest_path: Optional[str] = None   # save the manifest in the same run


class WrittenFile(BaseModel):
    artifact: str
    path: str


class FailedFile(BaseModel):
    artifact: str
    path: str
    error: str


class Suggestion(BaseModel):
    id: str
    # missing_run|continuity_gap|topology_confirm|restart_link|role_guess|starting_structure
    # |lineage_group|lineage_needs_you — `lineage_needs_you` is the card a tree the layout
    # inference refuses gets, when the tree plausibly had members to declare (see
    # `discover_draft`'s `rival_dirs` gate). `needs_you` is never a `kind` — see `severity`.
    kind: str
    severity: str    # needs_you|applied|info
    title: str
    evidence: str
    actions: List[str] = Field(default_factory=list)
    step_id: Optional[str] = None       # the step a step-scoped suggestion (e.g. continuity_gap) refers to
    phase_id: Optional[str] = None
    base: Optional[str] = None          # missing_run: the numbered-sequence base
    missing: Optional[List[int]] = None # missing_run: the absent indices
    # missing_run: the member the finding is scoped to, null for the untagged bucket.
    # Declared, not incidental: pydantic's extra='ignore' would drop the key from
    # build_suggestions' dict silently, so the card would name no member and nothing
    # would say why.
    lineage: Optional[str] = None


class LineageTotals(BaseModel):
    """One declared member's share of the document.

    Its own model rather than a reuse of `totals`' `Dict[str, float]`: `step_count` is a
    count of steps and belongs as an int, and a nested dict raises inside a float map
    anyway — which is why the breakdown sits beside `totals` and not inside it.
    """
    steps: float = 0.0
    time_ps: float = 0.0
    step_count: int = 0


# ---- Lineage proposal: what Discover found, never what it wrote (P2.2) ----

class ProposedSource(BaseModel):
    """One directory a proposed member's runs came from, and how many of them."""
    directory: str
    run_count: int


class ProposedMember(BaseModel):
    """One member `core_bridge.build_lineage_proposal` proposes — NOT a declared lineage.

    Nothing here is on any step's `lineage` yet; `step_ids` is what a PATCH /steps/lineage
    accepting this member would tag, and `sources` is the evidence a reviewer reads before
    doing that — which directories fed it and how many runs each held.
    """
    tag: str
    step_ids: List[str] = Field(default_factory=list)
    sources: List[ProposedSource] = Field(default_factory=list)


class ProposedHandoff(BaseModel):
    """One cross-directory restart handoff read off AMBER's own File Assignments block.

    Populated starting with the handoff-proposal task (P2.4), not this one — declared now
    so `LineageProposal.handoffs` has a shape from the day the wire contract exists, and
    the field is never a silent extra='ignore' drop the moment it starts carrying data.
    """
    consumer_id: str
    producer_id: str
    consumer: str
    producer: str
    evidence: str


class LineageProposal(BaseModel):
    """What Discover — or the layout inference re-run on the open document — proposes.

    Never written: nothing in this model corresponds to a `Step.lineage` that has actually
    been set. See `core_bridge.build_lineage_proposal` for exactly what `segment_index` and
    `segments` count over and where the offered indices come from — a segment picker
    renders directly off `segments`, so the server, not the frontend, owns that math.
    """
    segment_index: int
    segments: List[List[str]] = Field(default_factory=list)
    members: List[ProposedMember] = Field(default_factory=list)
    # Always present, possibly empty, rather than omitted — so the wire shape does not
    # change the day the handoff-proposal task starts populating it.
    handoffs: List[ProposedHandoff] = Field(default_factory=list)


class PlanResult(BaseModel):
    written: List[WrittenFile] = Field(default_factory=list)
    # One unwritable path does not hide the artifacts that did land: the response names
    # both, so the user is never told "it failed" about a run that wrote three files.
    failed: List[FailedFile] = Field(default_factory=list)
    # Also the channel the TOTALS-DELTA report rides (`core_bridge.write_plan_outputs`):
    # "totals changed since the last summary.json (...)" is a caveat about a file this
    # call just overwrote, and this is the field the GUI already puts in front of the user
    # at that exact moment -- `PlanModal` renders each entry inline under the written-files
    # list, and `usePlan`'s onSuccess toasts it. Deliberately NOT a new key: an undeclared
    # one is dropped in silence by `extra='ignore'`, which has cost this file two findings
    # already (see `suggestions` below and `StageIssue.continuity`), and the delta is the
    # one sentence a researcher reads before quoting a number.
    warnings: List[str] = Field(default_factory=list)
    stage_count: int = 0
    totals: Dict[str, float] = Field(default_factory=dict)
    # Declared, not incidental: pydantic's extra='ignore' would drop the key silently and
    # the response would look correct while saying nothing about the replica that stopped
    # early. `StageIssue.continuity` is already lost that way.
    suggestions: List[Suggestion] = Field(default_factory=list)
    # Null, not absent, when the document declares no members: no route sets
    # `exclude_none`, so an Optional field always serialises. `to_dict()`/summary.json can
    # and does omit it — a plain dict is not bound by that.
    lineages: Optional[Dict[str, LineageTotals]] = None
    document: DocumentResponse


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
    # `build_validation_report` has always emitted this and the model has always dropped
    # it, because pydantic's default `extra='ignore'` says nothing when a key it does not
    # know about arrives. The continuity notes are the one part of a stage's output that
    # is about the *lineage*, so losing them on the wire is not a cosmetic gap.
    continuity: List[str] = Field(default_factory=list)
    missing_files: List[MissingFile] = Field(default_factory=list)


class CoherenceFinding(BaseModel):
    """What the declared members do and do not agree about.

    Carries its own severity, which is the point of it: `protocol_issues` is a
    `List[str]` the panel renders uniformly as a warning, so a category error routed
    through it showed a yellow "Valid, with 1 protocol note(s)" while the CLI exited 1.
    """
    severity: str    # error | warning | info
    kind: str        # atom_count | run_type | parameter | seed | fan_out
    message: str


class ValidationReport(BaseModel):
    ok: bool
    totals: Dict[str, float] = Field(default_factory=dict)
    lineages: Optional[Dict[str, LineageTotals]] = None
    coherence: List[CoherenceFinding] = Field(default_factory=list)
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
    # Optional so the field is absent-tolerant on the wire — every discover response
    # carries the key (pydantic serialises a declared field whether or not it was set),
    # but `null` is a legitimate value: a tree the layout inference refuses proposes
    # nothing. The GUI route calls `discover_draft(..., apply_tags=False)`, so this is the
    # ONLY place the grouping reaches the client at all until it is accepted.
    proposal: Optional[LineageProposal] = None
    warnings: List[str] = Field(default_factory=list)


class InferLineagesRequest(BaseModel):
    """Which path segment to try, or `None` to run the layout inference `discover` uses.

    `segment_index` indexes `stem.split("/")` on the OPEN document's own step names — the
    same posix stems `discover` built them from — directory parts first, then the run stem
    itself. See `core_bridge.build_lineage_proposal` for exactly what index a given value
    selects and where the offered indices (`LineageProposal.segments`) come from; this is
    the segment-picker's "try this column" request.
    """
    segment_index: Optional[int] = None


class LineageProposalResponse(BaseModel):
    """`POST /steps/infer-lineages`'s reply: a proposal, or none, plus why not.

    Its own model rather than a reuse of `DocumentResponse` — this route no longer touches
    the document at all (it only reads it), so returning one would claim an edit that never
    happened. Both fields are declared, not just `proposal`, because a bare
    `Optional[LineageProposal]` has no `warnings` field at all and is `null` on exactly the
    refusal path two existing tests read `body["warnings"][0]` off.
    """
    proposal: Optional[LineageProposal] = None
    warnings: List[str] = Field(default_factory=list)


class PreviewRequest(BaseModel):
    format: str = "yaml"


class PreviewResponse(BaseModel):
    content: str
    warnings: List[str] = Field(default_factory=list)
    format: str


FileInfo.model_rebuild()
