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
# `lineages` the function is deliberately NOT re-exported: binding that name here would
# overwrite the `ambermeta.lineages` submodule attribute, and `import ambermeta.lineages
# as L` would then hand the caller the function instead of the module. Import it as
# `from ambermeta.lineages import lineages` at the call site.
from ambermeta.lineages import (
    UNTAGGED,
    infer_lineages_from_layout,
    is_multi_lineage,
    members,
)

__all__ = [
    "__version__",
    "AmberMetaError",
    "FileLoadError",
    "UNTAGGED",
    "infer_lineages_from_layout",
    "is_multi_lineage",
    "members",
    "SimulationProtocol",
    "SimulationStage",
    "ProtocolBuilder",
    "auto_discover",
    "detect_numeric_sequences",
    "infer_stage_role_from_content",
    "auto_detect_restart_chain",
    "smart_group_files",
]
