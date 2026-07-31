"""AmberMeta - Simulation provenance extraction for AMBER molecular dynamics."""

__version__ = "1.1.0"

from ambermeta.protocol import (
    SimulationProtocol,
    SimulationStage,
    ProtocolBuilder,
    auto_discover,
    detect_numeric_sequences,
    infer_stage_role_from_content,
    auto_detect_restart_chain,
    smart_group_files,
)
from ambermeta.errors import AmberMetaError, FileLoadError

__all__ = [
    "__version__",
    "AmberMetaError",
    "FileLoadError",
    "SimulationProtocol",
    "SimulationStage",
    "ProtocolBuilder",
    "auto_discover",
    "detect_numeric_sequences",
    "infer_stage_role_from_content",
    "auto_detect_restart_chain",
    "smart_group_files",
]
