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
    # single member. Written by `discover`'s inference or by editing the manifest, so the
    # GUI only displays it.
    lineage: Optional[str] = None
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
    # The tag is read-only at this surface today: no route writes it. Declared as a
    # top-level field so it inherits `topology`'s presence semantics when a write path
    # arrives, rather than `files`' ""-clears rule — a lineage is a label, not a file slot.
    lineage: Optional[str] = None
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


class PlanResult(BaseModel):
    written: List[WrittenFile] = Field(default_factory=list)
    # One unwritable path does not hide the artifacts that did land: the response names
    # both, so the user is never told "it failed" about a run that wrote three files.
    failed: List[FailedFile] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    stage_count: int = 0
    totals: Dict[str, float] = Field(default_factory=dict)
    document: DocumentResponse


class Suggestion(BaseModel):
    id: str
    kind: str        # missing_run|continuity_gap|topology_confirm|restart_link|role_guess|starting_structure|lineage_group
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
