"""AmberMeta - Simulation provenance extraction for AMBER molecular dynamics."""

__version__ = "0.2.0"

from ambermeta.protocol import (
    SimulationProtocol,
    SimulationStage,
    ProtocolBuilder,
    auto_discover,
    detect_numeric_sequences,
    infer_stage_role_from_content,
    auto_detect_restart_chain,
    smart_group_files,
    load_manifest,
    load_protocol_from_manifest,
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
    "load_manifest",
    "load_protocol_from_manifest",
]
