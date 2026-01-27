# Python API Reference

This document provides a comprehensive reference for the AmberMeta Python API.

## Table of Contents

- [Installation](#installation)
- [Core Classes](#core-classes)
  - [SimulationProtocol](#simulationprotocol)
  - [SimulationStage](#simulationstage)
  - [ProtocolBuilder](#protocolbuilder)
- [Parsers](#parsers)
  - [PrmtopParser](#prmtopparser)
  - [MdinParser](#mdinparser)
  - [MdoutParser](#mdoutparser)
  - [MdcrdParser](#mdcrdparser)
  - [InpcrdParser](#inpcrdparser)
- [Discovery Functions](#discovery-functions)
- [Utility Functions](#utility-functions)
- [TUI Components](#tui-components)
- [Examples](#examples)

---

## Installation

```python
# Core functionality
from ambermeta import (
    SimulationProtocol,
    SimulationStage,
    ProtocolBuilder,
    auto_discover,
    load_protocol_from_manifest,
    load_manifest,
)

# Individual parsers
from ambermeta.parsers import (
    PrmtopParser,
    MdinParser,
    MdoutParser,
    MdcrdParser,
    InpcrdParser,
)

# Utility functions
from ambermeta import (
    detect_numeric_sequences,
    smart_group_files,
    auto_detect_restart_chain,
    infer_stage_role_from_content,
)

# TUI (optional)
from ambermeta import (
    run_tui,
    ProtocolState,
    Stage,
    TEXTUAL_AVAILABLE,
)
```

---

## Core Classes

### SimulationProtocol

Container for multiple simulation stages with validation and export capabilities.

```python
class SimulationProtocol:
    """Represents a complete simulation protocol with multiple stages."""

    stages: List[SimulationStage]  # Ordered list of stages
```

#### Methods

##### `totals() -> Dict[str, float]`

Calculate total steps and simulation time across all stages.

```python
protocol = auto_discover("/path/to/simulations")
totals = protocol.totals()

print(f"Total steps: {totals['steps']:.0f}")
print(f"Total time: {totals['time_ps']:.3f} ps")
```

Returns:
```python
{
    "steps": 50000000.0,
    "time_ps": 100000.0
}
```

##### `validate(cross_stage: bool = True) -> None`

Run validation checks on all stages.

```python
protocol.validate(cross_stage=True)

# Check validation notes
for stage in protocol.stages:
    for note in stage.validation:
        print(note)
```

##### `to_dict() -> Dict[str, Any]`

Convert protocol to a JSON-serializable dictionary.

```python
import json

data = protocol.to_dict()
with open("protocol.json", "w") as f:
    json.dump(data, f, indent=2)
```

##### `to_methods_dict() -> Dict[str, Any]`

Generate a publication-ready summary with reproducibility-critical metadata.

```python
methods = protocol.to_methods_dict()

# Contains:
# - stages: List of stage summaries
# - totals: Step and time totals
# - software: AMBER version info
# - engine_settings: MD parameters
```

---

### SimulationStage

Represents a single simulation stage with parsed file metadata.

```python
class SimulationStage:
    """A single simulation stage."""

    name: str                           # Stage identifier
    stage_role: Optional[str]           # minimization, heating, equilibration, production
    prmtop: Optional[ParsedFile]        # Topology metadata
    mdin: Optional[ParsedFile]          # Input metadata
    mdout: Optional[ParsedFile]         # Output metadata
    mdcrd: Optional[ParsedFile]         # Trajectory metadata
    inpcrd: Optional[ParsedFile]        # Restart metadata
    restart_path: Optional[str]         # Path to restart file
    validation: List[str]               # Validation notes
    continuity: List[str]               # Continuity check results
    expected_gap_ps: Optional[float]    # Expected gap from previous stage
    gap_tolerance_ps: Optional[float]   # Tolerance for gap validation
```

#### Methods

##### `summary() -> Dict[str, Any]`

Generate a summary of the stage.

```python
stage = protocol.stages[0]
summary = stage.summary()

print(f"Intent: {summary['intent']}")
print(f"Result: {summary['result']}")
print(f"Evidence: {summary['evidence']}")
```

##### `to_dict() -> Dict[str, Any]`

Convert stage to a dictionary.

```python
data = stage.to_dict()
# Contains: name, stage_role, files, validation, continuity
```

---

### ProtocolBuilder

Fluent API for constructing protocols programmatically.

```python
class ProtocolBuilder:
    """Builder pattern for SimulationProtocol construction."""
```

#### Methods

##### `from_directory(path: str, recursive: bool = False) -> ProtocolBuilder`

Set the base directory for file discovery.

```python
builder = ProtocolBuilder().from_directory("/path/to/simulations", recursive=True)
```

##### `from_manifest(path: str) -> ProtocolBuilder`

Load stages from a manifest file.

```python
builder = ProtocolBuilder().from_manifest("protocol.yaml")
```

##### `with_grouping_rules(rules: Dict[str, str]) -> ProtocolBuilder`

Set rules for stage role inference based on name patterns.

```python
builder = builder.with_grouping_rules({
    r"min.*": "minimization",
    r"heat.*": "heating",
    r"equil.*": "equilibration",
    r"prod.*": "production",
})
```

##### `with_pattern_filter(pattern: str) -> ProtocolBuilder`

Filter discovered files by regex pattern.

```python
builder = builder.with_pattern_filter(r"prod_\d+")  # Only production runs
```

##### `include_roles(roles: List[str]) -> ProtocolBuilder`

Include only stages with specified roles.

```python
builder = builder.include_roles(["equilibration", "production"])
```

##### `auto_detect_restarts() -> ProtocolBuilder`

Enable automatic restart file detection.

```python
builder = builder.auto_detect_restarts()
```

##### `with_stage_tolerance(stage_name: str, expected_gap_ps: float, tolerance_ps: float) -> ProtocolBuilder`

Set gap expectations for a specific stage.

```python
builder = builder.with_stage_tolerance("prod_001", expected_gap_ps=0.0, tolerance_ps=0.1)
builder = builder.with_stage_tolerance("prod_002", expected_gap_ps=2.0, tolerance_ps=0.5)
```

##### `skip_validation(skip: bool = True) -> ProtocolBuilder`

Skip cross-stage validation.

```python
builder = builder.skip_validation(True)
```

##### `add_stage(...) -> ProtocolBuilder`

Add a stage manually.

```python
builder = builder.add_stage(
    name="production",
    stage_role="production",
    prmtop="system.prmtop",
    mdin="prod.in",
    mdout="prod.out",
    mdcrd="prod.nc",
    inpcrd="equil.rst7",
    expected_gap_ps=0.0,
)
```

##### `build() -> SimulationProtocol`

Build the final protocol.

```python
protocol = builder.build()
```

#### Complete Example

```python
from ambermeta import ProtocolBuilder

protocol = (
    ProtocolBuilder()
    .from_directory("/path/to/simulations", recursive=True)
    .with_grouping_rules({
        r"min.*": "minimization",
        r"heat.*": "heating",
        r"equil.*": "equilibration",
        r"prod.*": "production",
    })
    .with_pattern_filter(r"(equil|prod)_\d+")
    .include_roles(["equilibration", "production"])
    .auto_detect_restarts()
    .with_stage_tolerance("prod_001", expected_gap_ps=0.0, tolerance_ps=0.1)
    .build()
)
```

---

## Parsers

All parsers follow a consistent interface:

```python
parser = Parser(filepath)
result = parser.parse()

# Result contains:
# - details: Parsed metadata object
# - warnings: List of warning messages
# - filename: Original filename
```

### PrmtopParser

Parse AMBER topology/parameter files.

```python
from ambermeta.parsers import PrmtopParser

parser = PrmtopParser("system.prmtop")
result = parser.parse()
meta = result.details

# Available attributes
meta.natom          # int: Total atom count
meta.nres           # int: Total residue count
meta.residue_counts # Dict[str, int]: Residues by name
meta.box_dimensions # Tuple[float, float, float]: Box size (Angstroms)
meta.box_angles     # Tuple[float, float, float]: Box angles (degrees)
meta.solvent_type   # str: Detected solvent (TIP3P, TIP4P, etc.)
meta.ions           # Dict[str, int]: Ion counts
meta.total_charge   # float: System charge
meta.density        # float: Estimated density (g/cc)
meta.is_hmr         # bool: Hydrogen mass repartitioning detected
meta.n_atoms        # int: Alias for natom (consistent naming)
```

### MdinParser

Parse AMBER input control files.

```python
from ambermeta.parsers import MdinParser

parser = MdinParser("prod.mdin")
result = parser.parse()
meta = result.details

# Available attributes
meta.length_steps       # int: Total steps (nstlim or maxcyc)
meta.dt                 # float: Timestep (ps)
meta.temperature_control # str: Temperature control method
meta.target_temp        # float: Target temperature (K)
meta.pressure_control   # str: Pressure control method
meta.constraints        # str: Constraint description
meta.restraint_info     # Dict: Restraint details (mask, force constant)
meta.inferred_stage_role # str: Inferred role (minimization, heating, etc.)
meta.namelist           # Dict: Raw namelist parameters
```

### MdoutParser

Parse AMBER output log files.

```python
from ambermeta.parsers import MdoutParser

parser = MdoutParser("prod.mdout")
result = parser.parse()
meta = result.details

# Available attributes
meta.finished_properly  # bool: Simulation completed normally
meta.nstlim            # int: Total steps
meta.dt                # float: Timestep (ps)
meta.thermostat        # str: Thermostat type
meta.target_temp       # float: Target temperature
meta.barostat          # str: Barostat type
meta.box_type          # str: Box geometry
meta.pme_cutoff        # float: PME cutoff (Angstroms)

# Statistics (uses streaming Welford algorithm)
meta.stats.count       # int: Number of data points
meta.stats.time_start  # float: Start time (ps)
meta.stats.time_end    # float: End time (ps)
meta.stats.temp_mean   # float: Mean temperature
meta.stats.temp_std    # float: Temperature std dev
meta.stats.press_mean  # float: Mean pressure
meta.stats.press_std   # float: Pressure std dev
meta.stats.density_mean # float: Mean density
meta.stats.density_std  # float: Density std dev
```

### MdcrdParser

Parse AMBER trajectory files (ASCII or NetCDF).

```python
from ambermeta.parsers import MdcrdParser

parser = MdcrdParser("prod.nc")
result = parser.parse()
meta = result.details

# Available attributes
meta.n_frames      # int: Number of frames
meta.time_start    # float: Start time (ps)
meta.time_end      # float: End time (ps)
meta.avg_dt        # float: Average timestep (ps)
meta.has_box       # bool: Box information present
meta.box_type      # str: Box geometry
meta.volume_stats  # Tuple: (min, max, avg) volume
meta.is_remd       # bool: REMD trajectory
meta.remd_types    # List[str]: REMD exchange types
meta.remd_temp_stats # Tuple: (min, max, avg) temperature
```

### InpcrdParser

Parse AMBER restart/coordinate files.

```python
from ambermeta.parsers import InpcrdParser

parser = InpcrdParser("equil.rst7")
result = parser.parse()
meta = result.details

# Available attributes
meta.natoms         # int: Atom count
meta.has_velocities # bool: Velocities present
meta.has_box        # bool: Box information present
meta.box_dimensions # Tuple: Box dimensions
meta.time           # float: Simulation time (ps)
meta.n_atoms        # int: Alias for natoms
```

---

## Discovery Functions

### `auto_discover()`

Automatically discover and parse simulation files.

```python
from ambermeta import auto_discover

protocol = auto_discover(
    directory="/path/to/simulations",
    manifest=None,                    # Optional manifest dict
    recursive=True,                   # Scan subdirectories
    skip_cross_stage_validation=False,
    auto_detect_restarts=True,
    pattern_filter=r"prod_\d+",       # Regex filter
    grouping_rules={                  # Role inference
        "prod": "production",
    },
    restart_files={                   # Manual restart mapping
        "prod_001": "/path/to/equil.rst7",
    },
    global_prmtop="/path/to/system.prmtop",
    expand_env=True,                  # Expand ${VAR} in paths
)
```

### `load_protocol_from_manifest()`

Load a protocol from a manifest file.

```python
from ambermeta import load_protocol_from_manifest

protocol = load_protocol_from_manifest(
    manifest_path="protocol.yaml",
    directory=None,                   # Override base directory
    skip_cross_stage_validation=False,
    recursive=False,
    expand_env=True,
    global_prmtop=None,
)
```

### `load_manifest()`

Load manifest data from a file.

```python
from ambermeta import load_manifest

# Returns parsed data (list or dict)
data = load_manifest("protocol.yaml", expand_env=True)
```

---

## Utility Functions

### `detect_numeric_sequences()`

Detect numbered file sequences.

```python
from ambermeta import detect_numeric_sequences

files = ["prod_001.out", "prod_002.out", "prod_003.out", "equil.out"]
sequences = detect_numeric_sequences(files)

# Returns: {"prod_": ["prod_001.out", "prod_002.out", "prod_003.out"]}
```

Supported patterns:
- `name_001` (underscore + digits)
- `name.001` (dot + digits)
- `name001` (digits suffix)
- `name-001` (hyphen + digits)

### `smart_group_files()`

Group simulation files by stem with type detection.

```python
from ambermeta import smart_group_files

grouped = smart_group_files(
    directory="/path/to/simulations",
    recursive=True,
    pattern=r"prod_\d+",
)

# Returns:
# {
#     "prod_001": {
#         "mdin": "prod_001.in",
#         "mdout": "prod_001.out",
#         "mdcrd": "prod_001.nc",
#         "_sequence_base": "prod_",
#         "_sequence_index": 0,
#     },
#     ...
# }
```

### `auto_detect_restart_chain()`

Automatically detect restart file chains.

```python
from ambermeta import auto_detect_restart_chain

# Given a list of stages
restarts = auto_detect_restart_chain(
    stages=protocol.stages,
    directory="/path/to/simulations",
)

# Returns:
# {
#     "prod_002": "/path/to/prod_001.rst7",
#     "prod_003": "/path/to/prod_002.rst7",
# }
```

Detection is based on:
- Atom count matching
- Timestamp continuity
- Naming conventions
- Sequence ordering

### `infer_stage_role_from_content()`

Infer stage role from file content.

```python
from ambermeta import infer_stage_role_from_content

# From mdin file
role = infer_stage_role_from_content(mdin_metadata)
# Returns: "minimization", "heating", "equilibration", "production", or None
```

---

## TUI Components

### `run_tui()`

Launch the terminal user interface.

```python
from ambermeta import run_tui, TEXTUAL_AVAILABLE

if TEXTUAL_AVAILABLE:
    run_tui(
        directory="/path/to/simulations",
        recursive=True,
    )
else:
    print("TUI not available. Install with: pip install ambermeta[tui]")
```

### `ProtocolState`

State management for TUI protocol building.

```python
from ambermeta import ProtocolState, Stage

# Create state
state = ProtocolState("/path/to/simulations")

# Discover files
state.discover_files(recursive=True)

# Get discovered data
files = state.get_discovered_files()
sequences = state.get_sequences()

# Add stages
stage = Stage(
    name="production",
    role="production",
    files={"mdin": "prod.in", "mdout": "prod.out"},
)
state.add_stage(stage)

# Set global prmtop
state.set_global_prmtop("/path/to/system.prmtop")

# Undo/redo
state.undo()
state.redo()

# Export
state.export_yaml("manifest.yaml", use_absolute_paths=True)
state.export_json("manifest.json")
state.export_toml("manifest.toml")
state.export_csv("manifest.csv")

# Session management
state.save_session("session.json")
loaded = ProtocolState.load_session("session.json")
```

### `Stage`

Data class for stage information.

```python
from ambermeta import Stage

stage = Stage(
    name="production",
    role="production",
    files={"mdin": "prod.in", "mdout": "prod.out"},
    expected_gap_ps=0.0,
    gap_tolerance_ps=0.1,
    notes=["Main production run"],
    sequence_base="prod",
    sequence_index=0,
)

# Convert to manifest format
data = stage.to_dict()
```

---

## Examples

### Extract Metadata from All Files

```python
from pathlib import Path
from ambermeta.parsers import (
    PrmtopParser, MdinParser, MdoutParser, MdcrdParser, InpcrdParser
)

def analyze_directory(directory):
    """Analyze all simulation files in a directory."""
    results = {}

    for path in Path(directory).rglob("*"):
        if path.suffix in (".prmtop", ".top", ".parm7"):
            results[str(path)] = PrmtopParser(str(path)).parse()
        elif path.suffix in (".mdin", ".in"):
            results[str(path)] = MdinParser(str(path)).parse()
        elif path.suffix in (".mdout", ".out"):
            results[str(path)] = MdoutParser(str(path)).parse()
        elif path.suffix in (".nc", ".mdcrd"):
            results[str(path)] = MdcrdParser(str(path)).parse()
        elif path.suffix in (".rst", ".rst7", ".ncrst"):
            results[str(path)] = InpcrdParser(str(path)).parse()

    return results
```

### Build Protocol with Full Control

```python
from ambermeta import ProtocolBuilder
import json

# Build protocol
protocol = (
    ProtocolBuilder()
    .from_directory("/path/to/simulations", recursive=True)
    .with_grouping_rules({
        r"min.*": "minimization",
        r"heat.*": "heating",
        r"equil.*": "equilibration",
        r"prod.*": "production",
    })
    .auto_detect_restarts()
    .build()
)

# Print summary
print(f"Stages: {len(protocol.stages)}")
totals = protocol.totals()
print(f"Total time: {totals['time_ps']/1000:.2f} ns")

# Export
with open("protocol.json", "w") as f:
    json.dump(protocol.to_dict(), f, indent=2)

with open("methods.json", "w") as f:
    json.dump(protocol.to_methods_dict(), f, indent=2)
```

### Process Multiple Projects

```python
from pathlib import Path
from ambermeta import auto_discover
import json

def process_all_projects(base_dir):
    """Process all simulation projects in a directory."""
    results = []

    for project_dir in Path(base_dir).iterdir():
        if not project_dir.is_dir():
            continue

        try:
            protocol = auto_discover(
                str(project_dir),
                recursive=True,
                auto_detect_restarts=True,
            )

            totals = protocol.totals()
            results.append({
                "project": project_dir.name,
                "stages": len(protocol.stages),
                "time_ns": totals["time_ps"] / 1000,
                "steps": totals["steps"],
            })

        except Exception as e:
            results.append({
                "project": project_dir.name,
                "error": str(e),
            })

    return results

# Run
results = process_all_projects("/path/to/all/simulations")
print(json.dumps(results, indent=2))
```

### Custom Validation

```python
from ambermeta import auto_discover

def validate_protocol(protocol):
    """Perform custom validation checks."""
    issues = []

    for stage in protocol.stages:
        # Check for completion
        if stage.mdout and stage.mdout.details:
            if not stage.mdout.details.finished_properly:
                issues.append(f"{stage.name}: Simulation did not complete properly")

        # Check temperature stability
        if stage.mdout and stage.mdout.details and stage.mdout.details.stats:
            stats = stage.mdout.details.stats
            if hasattr(stats, "temp_std") and stats.temp_std > 10:
                issues.append(f"{stage.name}: High temperature fluctuation ({stats.temp_std:.1f} K)")

        # Check for validation notes
        warnings = [n for n in stage.validation if "WARNING" in n]
        if warnings:
            issues.extend(f"{stage.name}: {w}" for w in warnings)

    return issues

# Run validation
protocol = auto_discover("/path/to/simulations", recursive=True)
issues = validate_protocol(protocol)

if issues:
    print("Validation issues found:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("All checks passed!")
```
