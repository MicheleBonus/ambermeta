# AmberMeta

**A simulation provenance engine for AMBER molecular dynamics**

AmberMeta extracts, organizes, and validates metadata from AMBER molecular dynamics simulation files. It parses common AMBER outputs, assembles them into ordered simulation protocols, and highlights gaps or inconsistencies so you can report your simulation provenance with confidence.

## Table of Contents

- [Key Features](#key-features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Tutorials](#tutorials)
  - [Extracting Metadata from Files](#extracting-metadata-from-files)
  - [Building a Protocol from Directory](#building-a-protocol-from-directory)
  - [Using the Terminal UI (TUI)](#using-the-terminal-ui-tui)
  - [Working with Manifests](#working-with-manifests)
- [Command Line Interface](#command-line-interface)
- [Python API](#python-api)
- [Supported File Types](#supported-file-types)
- [Documentation](#documentation)
- [License](#license)

---

## Key Features

- **Structured Parsers** for AMBER files (`prmtop`, `mdin`, `mdout`, `inpcrd`, `mdcrd`) with optional NetCDF trajectory support
- **Metadata Extraction** including atom counts, box dimensions, simulation settings, thermodynamic statistics, and timing information
- **SimulationStage and SimulationProtocol** models that aggregate parsed files, flag validation issues, and compute total steps and simulated time
- **Interactive Terminal UI (TUI)** for visually building protocol manifests with file browsing, stage creation, and export
- **Manifest-Driven Planning** with support for YAML, JSON, TOML, and CSV formats
- **Smart File Discovery** with automatic sequence detection (e.g., `prod_001`, `prod_002`) and pattern-based filtering
- **Automatic Restart Chain Detection** to link simulation stages based on atom counts and timestamps
- **Fluent Builder API** for programmatic protocol construction
- **Environment Variable Expansion** in manifest paths for portable configurations
- **Cross-Stage Validation** to verify continuity between simulation stages

---

## Installation

AmberMeta targets Python 3.8+. From the repository root, install in editable mode:

```bash
python -m pip install -e .
```

### Optional Extras

```bash
# Terminal UI (TUI) support
python -m pip install -e ".[tui]"

# NetCDF trajectory reading (for .nc files)
python -m pip install -e ".[netcdf]"

# All optional dependencies
python -m pip install -e ".[all]"

# Test tooling
python -m pip install -e ".[tests]"

# TOML manifest support (Python < 3.11)
python -m pip install tomli

# YAML manifest support
python -m pip install pyyaml
```

---

## Quick Start

### Extract Metadata from a Single File

```bash
# Get detailed metadata about any AMBER file
ambermeta info system.prmtop
ambermeta info --format json prod.mdout
```

### Discover and Analyze All Files in a Directory

```bash
# Recursively scan and build a protocol
ambermeta plan --recursive /path/to/simulations

# Export a structured summary
ambermeta plan --recursive /path/to/simulations --summary-path protocol.json
```

### Launch the Interactive TUI

```bash
# Build a manifest interactively
ambermeta tui /path/to/simulations
```

### Use in Python

```python
from ambermeta import auto_discover

# Discover and parse all AMBER files
protocol = auto_discover("/path/to/simulations", recursive=True)

# Print summary
print(f"Found {len(protocol.stages)} stages")
totals = protocol.totals()
print(f"Total simulation time: {totals['time_ps']:.2f} ps")
```

---

## Tutorials

### Extracting Metadata from Files

The core goal of AmberMeta is to extract (meta)-data from simulation input and output files. Each file type provides different information:

#### Topology Files (.prmtop, .parm7, .top)

Topology files contain system composition information:

```bash
ambermeta info system.prmtop
```

```python
from ambermeta.parsers import PrmtopParser

parser = PrmtopParser("system.prmtop")
meta = parser.parse()

print(f"Atoms: {meta.natom}")
print(f"Box dimensions: {meta.box_dimensions}")
print(f"Residue count: {meta.nres}")
print(f"Density: {meta.density} g/cc")
print(f"Ion counts: {meta.ions}")
print(f"Solvent type: {meta.solvent_type}")
print(f"HMR (hydrogen mass repartitioning): {meta.is_hmr}")
```

**Extracted metadata:**
- Atom count, residue count, and molecular composition
- Box dimensions and type (orthorhombic, truncated octahedron, etc.)
- Ion counts (Na+, Cl-, etc.)
- Solvent detection (water model, ion content)
- HMR detection for hydrogen mass repartitioning
- System density calculation

#### Input Control Files (.mdin, .in)

Input files define simulation parameters:

```bash
ambermeta info equil.mdin
```

```python
from ambermeta.parsers import MdinParser

parser = MdinParser("equil.mdin")
meta = parser.parse()

print(f"Run length: {meta.length_steps} steps")
print(f"Timestep: {meta.dt} ps")
print(f"Temperature control: {meta.temperature_control}")
print(f"Pressure control: {meta.pressure_control}")
print(f"Stage role: {meta.inferred_stage_role}")
print(f"Restraints: {meta.restraint_info}")
```

**Extracted metadata:**
- Run length (steps) and timestep
- Temperature control settings (NTT, target temperature)
- Pressure control settings (NTP, barostat)
- Constraint settings (SHAKE, hydrogen bonds)
- Restraint information (masks, force constants)
- Inferred stage role (minimization, heating, equilibration, production)

#### Output Log Files (.mdout, .out)

Output files contain simulation results and statistics:

```bash
ambermeta info prod.mdout
```

```python
from ambermeta.parsers import MdoutParser

parser = MdoutParser("prod.mdout")
meta = parser.parse()

print(f"Completion status: {'Complete' if meta.finished_properly else 'Incomplete'}")
print(f"Thermostat: {meta.thermostat}")
print(f"Barostat: {meta.barostat}")
print(f"Box type: {meta.box_type}")

# Access thermodynamic statistics
if meta.stats:
    print(f"Frames: {meta.stats.count}")
    print(f"Time range: {meta.stats.time_start} - {meta.stats.time_end} ps")
    print(f"Avg temperature: {meta.stats.temp_mean:.2f} K")
    print(f"Avg pressure: {meta.stats.press_mean:.2f} bar")
    print(f"Avg density: {meta.stats.density_mean:.4f} g/cc")
```

**Extracted metadata:**
- Completion status (finished properly flag)
- Thermostat and barostat settings
- PME settings (cutoff, grid spacing)
- Box type and dimensions
- Streaming statistics (temperature, pressure, density, energy)
- Timing information

#### Trajectory Files (.nc, .mdcrd, .crd)

Trajectory files contain coordinate data over time:

```bash
ambermeta info prod.nc
```

```python
from ambermeta.parsers import MdcrdParser

parser = MdcrdParser("prod.nc")
meta = parser.parse()

print(f"Frames: {meta.n_frames}")
print(f"Time range: {meta.time_start} - {meta.time_end} ps")
print(f"Average timestep: {meta.avg_dt} ps")
print(f"Has box: {meta.has_box}")
print(f"REMD trajectory: {meta.is_remd}")
```

**Extracted metadata:**
- Frame count and timing
- Box information (dimensions, volume statistics)
- REMD detection and replica information
- Coordinate sampling frequency

#### Restart/Coordinate Files (.rst7, .rst, .ncrst, .inpcrd)

Restart files link simulation stages:

```bash
ambermeta info equil.rst7
```

```python
from ambermeta.parsers import InpcrdParser

parser = InpcrdParser("equil.rst7")
meta = parser.parse()

print(f"Atoms: {meta.natoms}")
print(f"Has box: {meta.has_box}")
print(f"Has velocities: {meta.has_velocities}")
print(f"Time: {meta.time} ps")
```

**Extracted metadata:**
- Atom count and box dimensions
- Velocity presence
- Simulation time for continuity checking

---

### Building a Protocol from Directory

A protocol represents a complete simulation workflow with multiple stages:

```python
from ambermeta import auto_discover

# Basic discovery
protocol = auto_discover("/path/to/simulations")

# Recursive discovery with role inference
protocol = auto_discover(
    "/path/to/simulations",
    recursive=True,
    grouping_rules={
        "min": "minimization",
        "heat": "heating",
        "equil": "equilibration",
        "prod": "production",
    },
)

# With automatic restart chain detection
protocol = auto_discover(
    "/path/to/simulations",
    recursive=True,
    auto_detect_restarts=True,
)

# Filter by pattern (only production runs)
protocol = auto_discover(
    "/path/to/simulations",
    pattern_filter=r"prod_\d+",
)

# Examine results
for stage in protocol.stages:
    summary = stage.summary()
    print(f"\nStage: {stage.name}")
    print(f"  Role: {summary['intent']}")
    print(f"  Result: {summary['result']}")

    # Check validation notes
    for note in stage.validation:
        print(f"  Note: {note}")

# Get totals
totals = protocol.totals()
print(f"\nTotal steps: {totals['steps']:.0f}")
print(f"Total time: {totals['time_ps']:.3f} ps")

# Export for publication
methods_data = protocol.to_methods_dict()
```

#### Using the Builder API

For more control, use the fluent builder API:

```python
from ambermeta import ProtocolBuilder

protocol = (
    ProtocolBuilder()
    .from_directory("/path/to/files", recursive=True)
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
    .with_stage_tolerance("prod_002", expected_gap_ps=2.0, tolerance_ps=0.5)
    .build()
)
```

---

### Using the Terminal UI (TUI)

The TUI provides an interactive interface for building protocol manifests:

```bash
# Launch TUI in a directory
ambermeta tui /path/to/simulations
```

#### TUI Features

**File Browser (Left Panel)**
- Navigate the directory tree
- Files are color-coded by type:
  - `[P]` Green: prmtop (topology)
  - `[I]` Yellow: mdin (input)
  - `[O]` Cyan: mdout (output)
  - `[T]` Magenta: mdcrd (trajectory)
  - `[R]` Blue: inpcrd (restart)
- Click a `.prmtop` file to quickly assign it as global or HMR topology
- Click a folder to auto-generate stages from its contents

**Stage List (Center Panel)**
- View all configured stages
- Columns show: Name, Role, File count, Sequence position
- Select a stage to edit its properties

**Stage Editor (Right Panel)**
- Edit stage name, role, and file assignments
- Configure expected gaps and tolerances
- Add notes for documentation
- View and edit sequence information

#### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+A` | Auto-generate stages from current folder |
| `Ctrl+G` | Open global settings (prmtop, HMR, env vars) |
| `Ctrl+E` | Export manifest |
| `Ctrl+S` | Save session |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Q` | Quit |

#### Export Formats

Export your manifest to:
- **YAML** (.yaml, .yml) - Human-readable, requires PyYAML
- **JSON** (.json) - Universal, native support
- **TOML** (.toml) - Configuration-friendly format
- **CSV** (.csv) - Spreadsheet-compatible

---

### Working with Manifests

Manifests define your simulation protocol in a structured format:

#### YAML Example

```yaml
# protocol.yaml
- name: minimize
  stage_role: minimization
  prmtop: system.prmtop
  mdin: min.in
  mdout: min.out
  notes:
    - "Steepest descent minimization"

- name: heat
  stage_role: heating
  prmtop: system.prmtop
  mdin: heat.in
  mdout: heat.out
  inpcrd: min.rst7
  gaps:
    expected: 0.0
    tolerance: 0.1

- name: equilibrate
  stage_role: equilibration
  prmtop: system.prmtop
  mdin: equil.in
  mdout: equil.out
  mdcrd: equil.nc
  inpcrd: heat.rst7

- name: production
  stage_role: production
  prmtop: system.prmtop
  mdin: prod.in
  mdout: prod.out
  mdcrd: prod.nc
  inpcrd: equil.rst7
```

#### Using a Manifest

```bash
# Build protocol from manifest
ambermeta plan --manifest protocol.yaml

# With verbose output
ambermeta plan --manifest protocol.yaml -v

# Export structured summary
ambermeta plan --manifest protocol.yaml --summary-path output.json

# Export methods-ready summary for publications
ambermeta plan --manifest protocol.yaml --methods-summary-path methods.json
```

```python
from ambermeta import load_protocol_from_manifest

protocol = load_protocol_from_manifest("protocol.yaml")

for stage in protocol.stages:
    print(f"{stage.name}: {stage.summary()['result']}")
```

#### Environment Variables in Manifests

Use `${VAR}` or `$VAR` syntax for portable paths:

```yaml
- name: production
  prmtop: ${PROJECT_ROOT}/systems/complex.prmtop
  mdin: $HOME/templates/prod.in
  mdout: ${OUTPUT_DIR}/prod.out
```

Disable expansion with `--no-expand-env` or `expand_env=False`.

---

## Command Line Interface

### Main Commands

| Command | Description |
|---------|-------------|
| `plan` | Build and summarize a SimulationProtocol |
| `tui` | Launch interactive terminal UI |
| `validate` | Quick validation of simulation files |
| `info` | Display detailed metadata for a file |
| `init` | Generate example manifest templates |

### Plan Command

```bash
ambermeta plan [directory] [options]

Options:
  -m, --manifest PATH           Path to YAML/JSON/TOML/CSV manifest
  --recursive                   Scan subdirectories
  --prmtop PATH                 Global topology file for all stages
  --skip-cross-stage-validation Skip continuity checks
  -v, --verbose                 Show detailed metadata
  --summary-path PATH           Write JSON/YAML summary
  --summary-format {json,yaml}  Force summary format
  --methods-summary-path PATH   Write methods-ready JSON for publications
  --stats-csv PATH              Export statistics to CSV
  --no-expand-env               Disable environment variable expansion
  --pattern REGEX               Filter files by regex pattern
  --auto-detect-restarts        Auto-detect restart file chains
  --log-level LEVEL             Set logging level (DEBUG, INFO, WARNING, ERROR)
  --log-file PATH               Write logs to file
  -q, --quiet                   Suppress non-error output
```

### TUI Command

```bash
ambermeta tui [directory] [options]

Options:
  --recursive                   Enable recursive file discovery
  --show-all                    Show all files, not just simulation files
```

### Validate Command

```bash
# Validate individual files
ambermeta validate system.prmtop equil.mdin prod.mdout

# Strict mode (warnings become errors)
ambermeta validate --strict *.prmtop
```

### Info Command

```bash
# Show metadata in text format
ambermeta info system.prmtop

# Output as JSON or YAML
ambermeta info --format json system.prmtop
ambermeta info --format yaml prod.mdout
```

### Init Command

```bash
# Generate standard manifest template
ambermeta init my_project

# Different complexity levels
ambermeta init --template minimal my_project
ambermeta init --template comprehensive my_project

# Custom filename
ambermeta init -o my_protocol.yaml my_project
```

---

## Python API

### Core Classes

```python
from ambermeta import (
    # Protocol building
    SimulationProtocol,
    SimulationStage,
    ProtocolBuilder,

    # Discovery and loading
    auto_discover,
    load_protocol_from_manifest,
    load_manifest,

    # Utilities
    detect_numeric_sequences,
    smart_group_files,
    auto_detect_restart_chain,
    infer_stage_role_from_content,
)
```

### Individual Parsers

```python
from ambermeta.parsers import (
    PrmtopParser,
    MdinParser,
    MdoutParser,
    MdcrdParser,
    InpcrdParser,
)
```

### TUI Components (optional)

```python
from ambermeta import (
    run_tui,
    ProtocolState,
    Stage,
    TEXTUAL_AVAILABLE,
)
```

---

## Supported File Types

| Extension | Type | Description |
|-----------|------|-------------|
| `.prmtop`, `.top`, `.parm7` | prmtop | Topology/parameter file |
| `.mdin`, `.in` | mdin | Input control file |
| `.mdout`, `.out` | mdout | Output log file |
| `.mdcrd`, `.nc`, `.crd`, `.x` | mdcrd | Trajectory file |
| `.inpcrd`, `.rst`, `.rst7`, `.ncrst`, `.restrt` | inpcrd | Coordinate/restart file |

---

## Documentation

- [Tutorials](docs/tutorials.md) - Step-by-step guides for common workflows
- [Terminal UI Guide](docs/tui.md) - Complete TUI documentation
- [CLI Reference](docs/cli.md) - Detailed command-line documentation
- [Manifest Schema](docs/manifest.md) - Full manifest format documentation
- [Python API Reference](docs/api.md) - Complete API documentation
- [Improvement Plan](IMPROVEMENT_PLAN.md) - Development roadmap and changelog

---

## Sample Data

Sample AMBER inputs and outputs are in `tests/data/amber/md_test_files`. Try them with:

```python
from pathlib import Path
from ambermeta import auto_discover

sample_dir = Path("tests/data/amber/md_test_files")
protocol = auto_discover(
    str(sample_dir),
    grouping_rules={"CH3L1": "equilibration", "^ntp_prod": "production"},
    restart_files={"production": str(sample_dir / "ntp_prod_0000.rst")},
)
```

Run the automated tests:

```bash
pytest
```

---

## License

See LICENSE file for details.
