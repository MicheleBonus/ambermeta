"""
Pydantic schemas for the AmberMeta GUI API.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum


class FileType(str, Enum):
    """Enumeration of supported file types."""
    PRMTOP = "prmtop"
    MDIN = "mdin"
    MDOUT = "mdout"
    MDCRD = "mdcrd"
    INPCRD = "inpcrd"
    FOLDER = "folder"
    OTHER = "other"


class StageRole(str, Enum):
    """Enumeration of simulation stage roles."""
    MINIMIZATION = "minimization"
    HEATING = "heating"
    EQUILIBRATION = "equilibration"
    PRODUCTION = "production"
    UNKNOWN = ""


class FileInfo(BaseModel):
    """Information about a discovered file."""
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


class StageFiles(BaseModel):
    """Files associated with a simulation stage."""
    prmtop: Optional[str] = None
    mdin: Optional[str] = None
    mdout: Optional[str] = None
    mdcrd: Optional[str] = None
    inpcrd: Optional[str] = None


class StageCreate(BaseModel):
    """Request model for creating a new stage."""
    name: str
    role: StageRole = StageRole.UNKNOWN
    files: StageFiles = Field(default_factory=StageFiles)
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: List[str] = Field(default_factory=list)


class StageUpdate(BaseModel):
    """Request model for updating a stage."""
    name: Optional[str] = None
    role: Optional[StageRole] = None
    files: Optional[StageFiles] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: Optional[List[str]] = None


class GlobalSettings(BaseModel):
    """Global protocol settings (runtime; only prmtop fields are persisted)."""
    global_prmtop: Optional[str] = None
    hmr_prmtop: Optional[str] = None
    initial_coordinates: Optional[str] = None
    auto_link_restarts: bool = True
    strict_validation: bool = True
    allow_gaps: bool = False
    use_relative_paths: bool = True


class SettingsPatch(BaseModel):
    """Partial patch for GlobalSettings — all fields Optional."""
    global_prmtop: Optional[str] = None
    hmr_prmtop: Optional[str] = None
    initial_coordinates: Optional[str] = None
    auto_link_restarts: Optional[bool] = None
    strict_validation: Optional[bool] = None
    allow_gaps: Optional[bool] = None
    use_relative_paths: Optional[bool] = None


class StageModel(BaseModel):
    """A protocol stage as edited in the GUI (flat gap fields)."""
    id: str
    name: str
    role: StageRole = StageRole.UNKNOWN
    prmtop: Optional[str] = None
    mdin: Optional[str] = None
    mdout: Optional[str] = None
    mdcrd: Optional[str] = None
    inpcrd: Optional[str] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: List[str] = Field(default_factory=list)

    class Config:
        use_enum_values = True


class DocumentResponse(BaseModel):
    """The whole server-authoritative document in one payload."""
    base_directory: str
    manifest_path: Optional[str] = None
    dirty: bool = False
    can_undo: bool = False
    can_redo: bool = False
    settings: GlobalSettings = Field(default_factory=GlobalSettings)
    stages: List[StageModel] = Field(default_factory=list)


class StageReorderRequest(BaseModel):
    """Request model for reordering stages."""
    stage_ids: List[str]


class BulkStageUpdate(BaseModel):
    """Request model for bulk-updating multiple stages at once."""
    stage_ids: List[str]
    update: StageUpdate


class FileMetadata(BaseModel):
    """Metadata extracted from a file."""
    file_path: str
    file_type: FileType
    metadata: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)

    class Config:
        use_enum_values = True


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


class ApiError(BaseModel):
    """Standard API error response."""
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


class PreviewRequest(BaseModel):
    format: str = "yaml"


class PreviewResponse(BaseModel):
    content: str
    warnings: List[str] = Field(default_factory=list)
    format: str


# Forward reference resolution
FileInfo.model_rebuild()
