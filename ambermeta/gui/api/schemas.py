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
    use_hmr_prmtop: bool = False  # If True, use HMR prmtop instead of normal global prmtop
    expected_gap_ps: Optional[float] = None  # Override global default if set
    gap_tolerance_ps: Optional[float] = None  # Override global default if set
    notes: List[str] = Field(default_factory=list)


class StageUpdate(BaseModel):
    """Request model for updating a stage."""
    name: Optional[str] = None
    role: Optional[StageRole] = None
    files: Optional[StageFiles] = None
    use_hmr_prmtop: Optional[bool] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: Optional[List[str]] = None


class StageValidation(BaseModel):
    """Validation status for a stage."""
    is_valid: bool = True
    messages: List[str] = Field(default_factory=list)
    missing_files: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class StageResponse(BaseModel):
    """Response model for a stage."""
    id: str
    name: str
    role: StageRole
    files: StageFiles
    use_hmr_prmtop: bool = False  # If True, use HMR prmtop instead of normal global prmtop
    expected_gap_ps: Optional[float] = None  # User-specified or None to use global default
    gap_tolerance_ps: Optional[float] = None  # User-specified or None to use global default
    detected_duration_ps: Optional[float] = None  # Auto-detected from mdin (dt * nstlim)
    notes: List[str] = Field(default_factory=list)
    validation: StageValidation = Field(default_factory=StageValidation)
    sequence_base: Optional[str] = None
    sequence_index: Optional[int] = None

    class Config:
        use_enum_values = True


class GlobalSettings(BaseModel):
    """Global protocol settings."""
    global_prmtop: Optional[str] = None
    hmr_prmtop: Optional[str] = None
    default_expected_gap_ps: Optional[float] = None  # Default expected gap for all stages
    default_gap_tolerance_ps: Optional[float] = 0.1  # Default tolerance for all stages
    auto_link_restarts: bool = True
    validate_on_export: bool = True
    use_relative_paths: bool = False


class ProtocolState(BaseModel):
    """Full protocol state."""
    base_directory: str
    settings: GlobalSettings = Field(default_factory=GlobalSettings)
    stages: List[StageResponse] = Field(default_factory=list)


class StageReorderRequest(BaseModel):
    """Request model for reordering stages."""
    stage_ids: List[str]


class ExportFormat(str, Enum):
    """Supported export formats."""
    YAML = "yaml"
    JSON = "json"
    TOML = "toml"
    CSV = "csv"


class ExportRequest(BaseModel):
    """Request model for exporting the protocol."""
    format: ExportFormat = ExportFormat.YAML
    include_validation: bool = True
    use_relative_paths: bool = True

    class Config:
        use_enum_values = True


class ExportResponse(BaseModel):
    """Response model for export."""
    content: str
    filename: str
    format: ExportFormat

    class Config:
        use_enum_values = True


class ValidationResult(BaseModel):
    """Result of protocol validation."""
    is_valid: bool
    stage_validations: Dict[str, StageValidation] = Field(default_factory=dict)
    cross_stage_issues: List[str] = Field(default_factory=list)
    summary: str = ""


class FileMetadata(BaseModel):
    """Metadata extracted from a file."""
    file_path: str
    file_type: FileType
    metadata: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)

    class Config:
        use_enum_values = True


class SequenceInfo(BaseModel):
    """Information about a detected sequence of stages."""
    base_name: str
    stages: List[str]
    count: int


class SessionSaveRequest(BaseModel):
    """Request model for saving a session."""
    filename: str


class SessionLoadRequest(BaseModel):
    """Request model for loading a session."""
    filename: str


class ApiError(BaseModel):
    """Standard API error response."""
    detail: str
    code: Optional[str] = None


# Forward reference resolution
FileInfo.model_rebuild()
