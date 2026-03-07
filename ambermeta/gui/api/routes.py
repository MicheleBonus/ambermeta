"""
FastAPI routes for the AmberMeta GUI API.
"""

import os
import re
import uuid
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from .schemas import (
    FileInfo,
    FileType,
    FileMetadata,
    StageCreate,
    StageUpdate,
    StageResponse,
    StageFiles,
    StageValidation,
    StageRole,
    StageReorderRequest,
    BulkStageUpdate,
    ProtocolState,
    GlobalSettings,
    ExportRequest,
    ExportResponse,
    ExportFormat,
    ValidationResult,
    SequenceInfo,
    SessionSaveRequest,
    SessionLoadRequest,
)

router = APIRouter()

# In-memory state (per-session)
_protocol_state: Optional[ProtocolState] = None
_base_directory: str = "."


def get_state() -> ProtocolState:
    """Get the current protocol state, initializing if needed."""
    global _protocol_state
    if _protocol_state is None:
        _protocol_state = ProtocolState(
            base_directory=_base_directory,
            settings=GlobalSettings(),
            stages=[],
        )
    return _protocol_state


def set_base_directory(directory: str) -> None:
    """Set the base directory for file operations."""
    global _base_directory, _protocol_state
    _base_directory = os.path.abspath(directory)
    if _protocol_state is not None:
        _protocol_state.base_directory = _base_directory


def _get_file_type(path: str) -> FileType:
    """Determine the file type based on extension."""
    ext = Path(path).suffix.lower().lstrip(".")

    # Handle compound extensions
    name = Path(path).name.lower()

    # Prmtop files
    if ext in ("prmtop", "parm7", "top") or name.endswith(".prmtop"):
        return FileType.PRMTOP

    # Input files
    if ext in ("mdin", "in") or name.endswith(".mdin"):
        return FileType.MDIN

    # Output files
    if ext in ("mdout", "out") or name.endswith(".mdout"):
        return FileType.MDOUT

    # Trajectory files
    if ext in ("mdcrd", "nc", "netcdf", "crd", "trj") or name.endswith(".mdcrd"):
        return FileType.MDCRD

    # Coordinate/restart files
    if ext in ("inpcrd", "rst", "rst7", "restrt", "ncrst") or name.endswith(".inpcrd"):
        return FileType.INPCRD

    return FileType.OTHER


def _scan_directory(
    directory: str,
    recursive: bool = True,
    max_depth: int = 5,
    current_depth: int = 0
) -> List[FileInfo]:
    """Scan a directory for simulation files."""
    results: List[FileInfo] = []

    try:
        entries = sorted(os.listdir(directory))
    except PermissionError:
        return results

    for entry in entries:
        # Skip hidden files and common non-simulation directories
        if entry.startswith(".") or entry in ("__pycache__", "node_modules", ".git"):
            continue

        full_path = os.path.join(directory, entry)

        if os.path.isdir(full_path):
            children = None
            if recursive and current_depth < max_depth:
                children = _scan_directory(
                    full_path,
                    recursive=recursive,
                    max_depth=max_depth,
                    current_depth=current_depth + 1
                )

            results.append(FileInfo(
                path=full_path,
                name=entry,
                file_type=FileType.FOLDER,
                is_directory=True,
                parent=directory,
                children=children,
            ))
        else:
            file_type = _get_file_type(full_path)
            # Only include simulation-related files or show all if type is other
            if file_type != FileType.OTHER:
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    size = None

                results.append(FileInfo(
                    path=full_path,
                    name=entry,
                    file_type=file_type,
                    is_directory=False,
                    size=size,
                    extension=Path(full_path).suffix,
                    parent=directory,
                ))

    return results


def _detect_sequences(stages: List[StageResponse]) -> Dict[str, SequenceInfo]:
    """Detect numeric sequences in stage names."""
    sequences: Dict[str, List[str]] = {}

    # Pattern to match names with numeric suffixes
    pattern = re.compile(r"^(.+?)[-_]?(\d{2,})$")

    for stage in stages:
        match = pattern.match(stage.name)
        if match:
            base_name = match.group(1)
            if base_name not in sequences:
                sequences[base_name] = []
            sequences[base_name].append(stage.id)

    # Convert to SequenceInfo, only for groups with more than 1 member
    result: Dict[str, SequenceInfo] = {}
    for base_name, stage_ids in sequences.items():
        if len(stage_ids) > 1:
            result[base_name] = SequenceInfo(
                base_name=base_name,
                stages=stage_ids,
                count=len(stage_ids),
            )

    return result


def _suggest_stage_role(name: str, mdin_path: Optional[str] = None) -> StageRole:
    """Suggest a stage role based on name or mdin content."""
    name_lower = name.lower()

    # Check name patterns
    if any(kw in name_lower for kw in ("min", "minim")):
        return StageRole.MINIMIZATION
    elif any(kw in name_lower for kw in ("heat", "warm")):
        return StageRole.HEATING
    elif any(kw in name_lower for kw in ("equil", "npt", "nvt")):
        return StageRole.EQUILIBRATION
    elif any(kw in name_lower for kw in ("prod", "md", "run")):
        return StageRole.PRODUCTION

    return StageRole.UNKNOWN


def _validate_stage(stage: StageResponse, settings: GlobalSettings) -> StageValidation:
    """Validate a stage and return validation status."""
    validation = StageValidation(is_valid=True)

    # Check for required files based on role
    prmtop = stage.files.prmtop or settings.global_prmtop

    if not prmtop:
        validation.missing_files.append("prmtop")
        validation.messages.append("No topology file (prmtop) assigned")
        validation.is_valid = False

    if not stage.files.mdin and stage.role != StageRole.UNKNOWN:
        validation.missing_files.append("mdin")
        validation.messages.append("No input file (mdin) assigned")
        validation.is_valid = False

    # Warnings for optional files
    if not stage.files.mdout:
        validation.warnings.append("No output file (mdout) - validation limited")

    if not stage.files.inpcrd:
        validation.warnings.append("No coordinate file (inpcrd) assigned")

    # HMR-related validation: Check if mdin has large timestep suggesting HMR usage
    if stage.files.mdin and settings.hmr_prmtop:
        try:
            from ambermeta.parsers.mdin import MdinParser
            mdin_data = MdinParser(stage.files.mdin).parse()
            dt = getattr(mdin_data.details, 'dt', None) if mdin_data.details else None
            if dt is not None and dt >= 0.004:
                # Large timestep suggests HMR should be used
                effective_prmtop = stage.files.prmtop or settings.global_prmtop
                if effective_prmtop != settings.hmr_prmtop:
                    validation.warnings.append(
                        f"Large timestep (dt={dt} ps) detected. Consider using HMR prmtop."
                    )
        except Exception:
            pass  # Ignore parsing errors during validation

    # Warn if HMR prmtop is set for stage but global HMR isn't defined
    if stage.files.prmtop and settings.hmr_prmtop:
        if stage.files.prmtop == settings.hmr_prmtop:
            # Using HMR prmtop explicitly
            pass
    elif stage.files.prmtop and not settings.global_prmtop:
        # Stage has custom prmtop but no global set
        pass

    return validation


# =============================================================================
# File Endpoints
# =============================================================================

@router.get("/files", response_model=List[FileInfo])
async def list_files(
    path: Optional[str] = Query(None, description="Directory path to list"),
    recursive: bool = Query(True, description="Include subdirectories"),
) -> List[FileInfo]:
    """List discovered simulation files."""
    directory = path if path else _base_directory

    if not os.path.isdir(directory):
        raise HTTPException(status_code=404, detail=f"Directory not found: {directory}")

    return _scan_directory(directory, recursive=recursive)


@router.get("/files/metadata", response_model=FileMetadata)
async def get_file_metadata(
    path: str = Query(..., description="File path to analyze")
) -> FileMetadata:
    """Get detailed metadata for a specific file."""
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    file_type = _get_file_type(path)
    metadata: Dict[str, Any] = {"path": path}
    warnings: List[str] = []

    try:
        # Try to parse the file using the appropriate parser
        if file_type == FileType.PRMTOP:
            from ambermeta.parsers.prmtop import PrmtopParser
            parser = PrmtopParser(path)
            data = parser.parse()
            metadata.update({
                "natom": data.get("POINTERS", [0])[0] if "POINTERS" in data else None,
                "has_box": "BOX_DIMENSIONS" in data,
            })
        elif file_type == FileType.MDIN:
            from ambermeta.parsers.mdin import MdinParser
            parser = MdinParser(path)
            data = parser.parse()
            metadata.update({
                "nstlim": data.cntrl.get("nstlim"),
                "dt": data.cntrl.get("dt"),
                "ntx": data.cntrl.get("ntx"),
            })
        elif file_type == FileType.MDOUT:
            from ambermeta.parsers.mdout import MdoutParser
            parser = MdoutParser(path)
            data = parser.parse()
            metadata.update({
                "finished": data.finished_properly,
                "nstlim": data.nstlim,
                "dt": data.dt,
            })
    except Exception as e:
        warnings.append(f"Could not parse file: {str(e)}")

    return FileMetadata(
        file_path=path,
        file_type=file_type,
        metadata=metadata,
        warnings=warnings,
    )


# =============================================================================
# Stage Endpoints
# =============================================================================

@router.get("/stages", response_model=List[StageResponse])
async def list_stages() -> List[StageResponse]:
    """Get all stages in the protocol."""
    state = get_state()
    return state.stages


@router.post("/stages", response_model=StageResponse)
async def create_stage(stage: StageCreate) -> StageResponse:
    """Create a new stage."""
    state = get_state()

    # Generate unique ID
    stage_id = str(uuid.uuid4())[:8]

    # Suggest role if not provided
    role = stage.role if stage.role != StageRole.UNKNOWN else _suggest_stage_role(stage.name)

    # Create the stage response
    new_stage = StageResponse(
        id=stage_id,
        name=stage.name,
        role=role,
        files=stage.files,
        expected_gap_ps=stage.expected_gap_ps,
        gap_tolerance_ps=stage.gap_tolerance_ps,
        notes=stage.notes,
    )

    # Validate the stage
    new_stage.validation = _validate_stage(new_stage, state.settings)

    state.stages.append(new_stage)

    return new_stage


@router.get("/stages/{stage_id}", response_model=StageResponse)
async def get_stage(stage_id: str) -> StageResponse:
    """Get a specific stage by ID."""
    state = get_state()

    for stage in state.stages:
        if stage.id == stage_id:
            return stage

    raise HTTPException(status_code=404, detail=f"Stage not found: {stage_id}")


@router.put("/stages/{stage_id}", response_model=StageResponse)
async def update_stage(stage_id: str, update: StageUpdate) -> StageResponse:
    """Update an existing stage."""
    state = get_state()

    for i, stage in enumerate(state.stages):
        if stage.id == stage_id:
            # Update fields if provided
            if update.name is not None:
                stage.name = update.name
            if update.role is not None:
                stage.role = update.role
            if update.files is not None:
                # Merge files instead of replacing - only update fields that are set
                # Empty string means "clear this field", None means "don't change"
                if update.files.prmtop is not None:
                    stage.files.prmtop = update.files.prmtop if update.files.prmtop else None
                if update.files.mdin is not None:
                    stage.files.mdin = update.files.mdin if update.files.mdin else None
                if update.files.mdout is not None:
                    stage.files.mdout = update.files.mdout if update.files.mdout else None
                if update.files.mdcrd is not None:
                    stage.files.mdcrd = update.files.mdcrd if update.files.mdcrd else None
                if update.files.inpcrd is not None:
                    stage.files.inpcrd = update.files.inpcrd if update.files.inpcrd else None
            if update.expected_gap_ps is not None:
                stage.expected_gap_ps = update.expected_gap_ps
            if update.gap_tolerance_ps is not None:
                stage.gap_tolerance_ps = update.gap_tolerance_ps
            if update.notes is not None:
                stage.notes = update.notes

            # Re-validate
            stage.validation = _validate_stage(stage, state.settings)

            state.stages[i] = stage
            return stage

    raise HTTPException(status_code=404, detail=f"Stage not found: {stage_id}")


@router.delete("/stages/{stage_id}")
async def delete_stage(stage_id: str) -> Dict[str, str]:
    """Delete a stage."""
    state = get_state()

    for i, stage in enumerate(state.stages):
        if stage.id == stage_id:
            state.stages.pop(i)
            return {"status": "deleted", "id": stage_id}

    raise HTTPException(status_code=404, detail=f"Stage not found: {stage_id}")


@router.post("/stages/reorder", response_model=List[StageResponse])
async def reorder_stages(request: StageReorderRequest) -> List[StageResponse]:
    """Reorder stages according to the provided ID list."""
    state = get_state()

    # Build a map of id -> stage
    stage_map = {stage.id: stage for stage in state.stages}

    # Validate all IDs exist
    for stage_id in request.stage_ids:
        if stage_id not in stage_map:
            raise HTTPException(status_code=400, detail=f"Unknown stage ID: {stage_id}")

    # Reorder
    state.stages = [stage_map[stage_id] for stage_id in request.stage_ids]

    # Auto-link restart files if enabled (order matters for restart chaining)
    if state.settings.auto_link_restarts:
        _link_restart_files(state)
        # Re-validate all stages after linking
        for stage in state.stages:
            stage.validation = _validate_stage(stage, state.settings)

    return state.stages


@router.put("/stages/bulk", response_model=List[StageResponse])
async def bulk_update_stages(request: BulkStageUpdate) -> List[StageResponse]:
    """Apply the same update to multiple stages at once."""
    state = get_state()
    stage_map = {stage.id: stage for stage in state.stages}

    updated: List[StageResponse] = []
    for stage_id in request.stage_ids:
        stage = stage_map.get(stage_id)
        if stage is None:
            raise HTTPException(status_code=400, detail=f"Unknown stage ID: {stage_id}")

        update = request.update
        if update.name is not None:
            stage.name = update.name
        if update.role is not None:
            stage.role = update.role
        if update.files is not None:
            if update.files.prmtop is not None:
                stage.files.prmtop = update.files.prmtop if update.files.prmtop else None
            if update.files.mdin is not None:
                stage.files.mdin = update.files.mdin if update.files.mdin else None
            if update.files.mdout is not None:
                stage.files.mdout = update.files.mdout if update.files.mdout else None
            if update.files.mdcrd is not None:
                stage.files.mdcrd = update.files.mdcrd if update.files.mdcrd else None
            if update.files.inpcrd is not None:
                stage.files.inpcrd = update.files.inpcrd if update.files.inpcrd else None
        if update.expected_gap_ps is not None:
            stage.expected_gap_ps = update.expected_gap_ps
        if update.gap_tolerance_ps is not None:
            stage.gap_tolerance_ps = update.gap_tolerance_ps
        if update.notes is not None:
            stage.notes = update.notes

        stage.validation = _validate_stage(stage, state.settings)
        updated.append(stage)

    return updated


# =============================================================================
# Protocol Endpoints
# =============================================================================

@router.get("/protocol", response_model=ProtocolState)
async def get_protocol() -> ProtocolState:
    """Get the full protocol state."""
    return get_state()


@router.post("/validate", response_model=ValidationResult)
async def validate_protocol() -> ValidationResult:
    """Validate the entire protocol including cross-stage checks."""
    state = get_state()

    result = ValidationResult(is_valid=True)

    # Validate each stage
    for stage in state.stages:
        stage.validation = _validate_stage(stage, state.settings)
        result.stage_validations[stage.id] = stage.validation
        if not stage.validation.is_valid:
            result.is_valid = False

    # Cross-stage validation
    if len(state.stages) > 1:
        # Check for consistent prmtop across stages
        prmtops = set()
        for stage in state.stages:
            prmtop = stage.files.prmtop or state.settings.global_prmtop
            if prmtop:
                prmtops.add(prmtop)

        if len(prmtops) > 1 and not state.settings.hmr_prmtop:
            result.cross_stage_issues.append(
                f"Multiple topology files used across stages: {', '.join(prmtops)}"
            )

    # Generate summary
    valid_count = sum(1 for v in result.stage_validations.values() if v.is_valid)
    total_count = len(result.stage_validations)
    result.summary = f"{valid_count}/{total_count} stages valid"

    if result.cross_stage_issues:
        result.summary += f", {len(result.cross_stage_issues)} cross-stage issues"

    return result


@router.post("/export", response_model=ExportResponse)
async def export_protocol(request: ExportRequest) -> ExportResponse:
    """Export the protocol to a manifest file."""
    state = get_state()

    # Build the export structure
    export_data: Dict[str, Any] = {
        "base_directory": state.base_directory if not request.use_relative_paths else ".",
    }

    # Add global prmtop if set
    if state.settings.global_prmtop:
        prmtop_path = state.settings.global_prmtop
        if request.use_relative_paths:
            try:
                prmtop_path = os.path.relpath(prmtop_path, state.base_directory)
            except ValueError:
                pass  # Keep absolute if on different drive
        export_data["global_prmtop"] = prmtop_path

    # Add HMR prmtop if set
    if state.settings.hmr_prmtop:
        hmr_path = state.settings.hmr_prmtop
        if request.use_relative_paths:
            try:
                hmr_path = os.path.relpath(hmr_path, state.base_directory)
            except ValueError:
                pass
        export_data["hmr_prmtop"] = hmr_path

    # Build stages
    stages_data = []
    for stage in state.stages:
        stage_entry: Dict[str, Any] = {"name": stage.name}

        if stage.role and stage.role != StageRole.UNKNOWN:
            # Ensure stage_role is serialized as a plain string, not a Python enum object
            stage_entry["stage_role"] = stage.role.value if hasattr(stage.role, 'value') else str(stage.role)

        # Add files
        for file_key in ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"]:
            file_path = getattr(stage.files, file_key)
            if file_path:
                if request.use_relative_paths:
                    try:
                        file_path = os.path.relpath(file_path, state.base_directory)
                    except ValueError:
                        pass
                stage_entry[file_key] = file_path

        # Add optional fields
        if stage.expected_gap_ps is not None:
            stage_entry["expected_gap_ps"] = stage.expected_gap_ps
        if stage.gap_tolerance_ps is not None:
            stage_entry["gap_tolerance_ps"] = stage.gap_tolerance_ps
        if stage.notes:
            stage_entry["notes"] = stage.notes

        stages_data.append(stage_entry)

    export_data["stages"] = stages_data

    # Format output
    content: str
    filename: str

    if request.format == ExportFormat.YAML:
        try:
            import yaml
            content = yaml.dump(export_data, default_flow_style=False, sort_keys=False)
        except ImportError:
            raise HTTPException(status_code=500, detail="YAML support not installed")
        filename = "protocol.yaml"

    elif request.format == ExportFormat.JSON:
        content = json.dumps(export_data, indent=2)
        filename = "protocol.json"

    elif request.format == ExportFormat.TOML:
        try:
            import sys
            if sys.version_info >= (3, 11):
                import tomllib
                # tomllib is read-only, need tomli-w for writing
                raise ImportError("tomllib cannot write")
            else:
                import toml
                content = toml.dumps(export_data)
        except ImportError:
            # Fallback to basic TOML formatting
            lines = []
            if "base_directory" in export_data:
                lines.append(f'base_directory = "{export_data["base_directory"]}"')
            if "global_prmtop" in export_data:
                lines.append(f'global_prmtop = "{export_data["global_prmtop"]}"')
            if "hmr_prmtop" in export_data:
                lines.append(f'hmr_prmtop = "{export_data["hmr_prmtop"]}"')

            for stage in stages_data:
                lines.append("")
                lines.append("[[stages]]")
                for key, value in stage.items():
                    if isinstance(value, str):
                        lines.append(f'{key} = "{value}"')
                    elif isinstance(value, list):
                        lines.append(f'{key} = {json.dumps(value)}')
                    else:
                        lines.append(f'{key} = {value}')

            content = "\n".join(lines)
        filename = "protocol.toml"

    elif request.format == ExportFormat.CSV:
        # CSV format: name,role,prmtop,mdin,mdout,mdcrd,inpcrd
        lines = ["name,role,prmtop,mdin,mdout,mdcrd,inpcrd"]
        for stage in stages_data:
            row = [
                stage.get("name", ""),
                stage.get("stage_role", ""),
                stage.get("prmtop", ""),
                stage.get("mdin", ""),
                stage.get("mdout", ""),
                stage.get("mdcrd", ""),
                stage.get("inpcrd", ""),
            ]
            lines.append(",".join(f'"{v}"' for v in row))
        content = "\n".join(lines)
        filename = "protocol.csv"

    else:
        raise HTTPException(status_code=400, detail=f"Unknown format: {request.format}")

    return ExportResponse(
        content=content,
        filename=filename,
        format=request.format,
    )


# =============================================================================
# Settings Endpoints
# =============================================================================

@router.get("/settings", response_model=GlobalSettings)
async def get_settings() -> GlobalSettings:
    """Get global protocol settings."""
    return get_state().settings


@router.put("/settings", response_model=GlobalSettings)
async def update_settings(settings: GlobalSettings) -> GlobalSettings:
    """Update global protocol settings."""
    state = get_state()
    state.settings = settings

    # Re-validate all stages with new settings
    for stage in state.stages:
        stage.validation = _validate_stage(stage, settings)

    return settings


# =============================================================================
# Related Files Endpoint
# =============================================================================


@router.get("/files/related/{stem:path}")
async def get_related_files(stem: str) -> Dict[str, str]:
    """Find all simulation files related to a given stem (filename without extension).

    This is used for auto-grouping related files when creating a stage from a dragged file.
    Returns a dict mapping file_type to file_path for all related files.
    """
    state = get_state()
    base_dir = state.base_directory

    # Build the stem path - if stem has a file extension, remove it
    stem_path = stem
    if Path(stem).suffix.lower() in (".mdin", ".mdout", ".nc", ".rst", ".rst7", ".prmtop", ".in", ".out", ".crd", ".x", ".ncrst", ".restrt", ".inpcrd", ".mdcrd", ".parm7", ".top"):
        stem_path = str(Path(stem).with_suffix(""))

    # Get the directory and stem name
    if "/" in stem_path or os.sep in stem_path:
        stem_dir = Path(base_dir) / Path(stem_path).parent
        stem_name = Path(stem_path).name
    else:
        stem_dir = Path(base_dir)
        stem_name = stem_path

    # Define file type mappings
    file_type_extensions = {
        "mdin": {".mdin", ".in"},
        "mdout": {".mdout", ".out"},
        "mdcrd": {".mdcrd", ".nc", ".crd", ".x"},
        "inpcrd": {".rst", ".rst7", ".ncrst", ".restrt", ".inpcrd"},
    }

    related_files: Dict[str, str] = {}

    try:
        if stem_dir.exists():
            for entry in stem_dir.iterdir():
                if entry.is_file():
                    # Check if the file stem matches
                    entry_stem = entry.stem
                    if entry_stem == stem_name:
                        # Determine file type (exclude prmtop - it should be set globally)
                        for file_type, extensions in file_type_extensions.items():
                            if entry.suffix.lower() in extensions:
                                if file_type not in related_files:
                                    related_files[file_type] = str(entry)
                                break
    except Exception:
        pass

    return related_files


# =============================================================================
# Session Endpoints
# =============================================================================

@router.post("/session/save")
async def save_session(request: SessionSaveRequest) -> Dict[str, str]:
    """Save the current session to a file."""
    state = get_state()

    # Serialize state
    session_data = state.model_dump()

    # Determine file path
    if not request.filename.endswith(".json"):
        request.filename += ".json"

    filepath = os.path.join(state.base_directory, request.filename)

    try:
        with open(filepath, "w") as f:
            json.dump(session_data, f, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save session: {str(e)}")

    return {"status": "saved", "path": filepath}


@router.post("/session/load")
async def load_session(request: SessionLoadRequest) -> ProtocolState:
    """Load a session from a file."""
    global _protocol_state

    filepath = request.filename
    if not os.path.isabs(filepath):
        filepath = os.path.join(_base_directory, filepath)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"Session file not found: {filepath}")

    try:
        with open(filepath, "r") as f:
            session_data = json.load(f)

        _protocol_state = ProtocolState(**session_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load session: {str(e)}")

    return _protocol_state


# =============================================================================
# Restart Linking Endpoints
# =============================================================================


def _find_initial_coordinates(
    base_dir: str, stage_stems: set, global_prmtop: Optional[str]
) -> Optional[str]:
    """Find initial coordinate files (not associated with any stage).

    These are typically files like 'system.inpcrd', 'complex.crd', 'structure.rst7'
    that were generated by tleap/pdb4amber/parmed before the simulation protocol.
    """
    inpcrd_extensions = {".rst", ".rst7", ".ncrst", ".restrt", ".inpcrd", ".crd"}
    candidates: List[str] = []

    # Scan for inpcrd files whose stem doesn't match any stage
    def scan_dir(directory: str, depth: int = 0) -> None:
        if depth > 3:  # Limit recursion depth
            return
        try:
            for entry in os.listdir(directory):
                if entry.startswith("."):
                    continue
                full_path = os.path.join(directory, entry)
                if os.path.isdir(full_path):
                    scan_dir(full_path, depth + 1)
                elif os.path.isfile(full_path):
                    p = Path(full_path)
                    if p.suffix.lower() in inpcrd_extensions:
                        inpcrd_stem = p.stem
                        if inpcrd_stem not in stage_stems:
                            # This inpcrd doesn't match any stage - could be initial coords
                            # Prefer files in the same directory as the prmtop
                            if global_prmtop:
                                prmtop_dir = str(Path(global_prmtop).parent)
                                inpcrd_dir = str(p.parent)
                                if prmtop_dir == inpcrd_dir:
                                    candidates.insert(0, full_path)  # Higher priority
                                else:
                                    candidates.append(full_path)
                            else:
                                candidates.append(full_path)
        except (PermissionError, OSError):
            pass

    scan_dir(base_dir)
    return candidates[0] if candidates else None


def _get_discovered_inpcrd_for_stem(base_dir: str, stem_name: str) -> Optional[str]:
    """Find an inpcrd/restart file for a given stage stem."""
    inpcrd_extensions = {".rst", ".rst7", ".ncrst", ".restrt", ".inpcrd"}

    def scan_dir(directory: str, depth: int = 0) -> Optional[str]:
        if depth > 3:
            return None
        try:
            for entry in os.listdir(directory):
                if entry.startswith("."):
                    continue
                full_path = os.path.join(directory, entry)
                if os.path.isdir(full_path):
                    result = scan_dir(full_path, depth + 1)
                    if result:
                        return result
                elif os.path.isfile(full_path):
                    p = Path(full_path)
                    if p.suffix.lower() in inpcrd_extensions and p.stem == stem_name:
                        return full_path
        except (PermissionError, OSError):
            pass
        return None

    return scan_dir(base_dir)


def _link_restart_files(state: ProtocolState) -> int:
    """Link restart files between consecutive stages.

    For each stage (except the first), determines the appropriate input coordinates:
    - The INPUT for stage N should be the restart OUTPUT from stage N-1
    - A same-stem inpcrd for stage N is its OUTPUT (restart), not its input

    Returns the number of stages that were updated.
    """
    if not state.stages:
        return 0

    updates_made = 0
    base_dir = state.base_directory

    # Build a set of stage stems
    stage_stems = {Path(s.name).stem for s in state.stages}

    # Handle first stage: look for initial coordinate file
    first_stage = state.stages[0]
    first_inpcrd = first_stage.files.inpcrd

    # If user provided an explicit initial_coordinates in settings, use that
    # for the first stage (highest priority for first step).
    if state.settings.initial_coordinates:
        if not first_inpcrd or first_inpcrd != state.settings.initial_coordinates:
            first_stage.files.inpcrd = state.settings.initial_coordinates
            updates_made += 1
    elif first_inpcrd:
        first_inpcrd_stem = Path(first_inpcrd).stem
        first_stage_stem = Path(first_stage.name).stem
        # If the first stage's inpcrd matches its own stem, it's actually its OUTPUT
        # We need to find the initial system coordinates instead
        if first_inpcrd_stem == first_stage_stem:
            initial_inpcrd = _find_initial_coordinates(
                base_dir, stage_stems, state.settings.global_prmtop
            )
            if initial_inpcrd:
                first_stage.files.inpcrd = initial_inpcrd
                updates_made += 1
    elif first_inpcrd is None:
        # First stage has no inpcrd at all - try to find initial coordinates
        initial_inpcrd = _find_initial_coordinates(
            base_dir, stage_stems, state.settings.global_prmtop
        )
        if initial_inpcrd:
            first_stage.files.inpcrd = initial_inpcrd
            updates_made += 1

    if len(state.stages) < 2:
        return updates_made

    # Link subsequent stages
    for i in range(1, len(state.stages)):
        prev_stage = state.stages[i - 1]
        curr_stage = state.stages[i]

        # Check if current stage already has an explicitly set inpcrd
        # that doesn't match its own stem (meaning it was set intentionally)
        curr_inpcrd = curr_stage.files.inpcrd
        curr_stem = Path(curr_stage.name).stem

        if curr_inpcrd:
            inpcrd_stem = Path(curr_inpcrd).stem
            if curr_stem != inpcrd_stem:
                # It's explicitly set to a different file, don't override
                continue

        # Look for restart file from previous stage
        # The previous stage's restart OUTPUT should be named like prev_stage.rst7
        prev_stem = Path(prev_stage.name).stem
        prev_inpcrd = prev_stage.files.inpcrd

        # If prev_inpcrd exists and has the same stem as the previous stage,
        # it's the restart OUTPUT of that stage, which we use as INPUT for current stage
        if prev_inpcrd:
            prev_inpcrd_stem = Path(prev_inpcrd).stem
            if prev_inpcrd_stem == prev_stem:
                # This is the restart output from prev_stage - use it as input for curr_stage
                curr_stage.files.inpcrd = prev_inpcrd
                updates_made += 1
                continue

        # Alternative: Look for restart file by scanning for prev_stem.rst* patterns
        restart_file = _get_discovered_inpcrd_for_stem(base_dir, prev_stem)
        if restart_file:
            curr_stage.files.inpcrd = restart_file
            updates_made += 1

    return updates_made


@router.post("/link-restarts")
async def link_restart_files() -> Dict[str, Any]:
    """Link restart files between consecutive stages.

    This endpoint implements the restart file chain logic:
    - First stage gets initial coordinates (system.inpcrd, complex.crd, etc.)
    - Each subsequent stage uses the restart output from the previous stage as input

    This is called automatically when auto_link_restarts is enabled and stages
    are created or reordered, but can also be triggered manually.
    """
    state = get_state()

    if not state.settings.auto_link_restarts:
        return {
            "status": "skipped",
            "message": "auto_link_restarts is disabled",
            "updates": 0,
        }

    updates = _link_restart_files(state)

    # Re-validate all stages after linking
    for stage in state.stages:
        stage.validation = _validate_stage(stage, state.settings)

    return {
        "status": "success",
        "message": f"Linked restart files for {updates} stage(s)",
        "updates": updates,
    }


# =============================================================================
# Sequence Endpoints
# =============================================================================

@router.get("/sequences", response_model=Dict[str, SequenceInfo])
async def get_sequences() -> Dict[str, SequenceInfo]:
    """Get detected stage sequences."""
    state = get_state()
    return _detect_sequences(state.stages)
