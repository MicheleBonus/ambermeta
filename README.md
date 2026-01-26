# AmberMeta

AmberMeta is a simulation provenance engine for AMBER molecular dynamics runs. It parses common AMBER outputs, stitches them together into ordered simulation protocols, and highlights gaps or inconsistencies so you can report progress with confidence.

## What You Get

- **Structured parsers** for AMBER artifacts (`prmtop`, `mdin`, `mdout`, `inpcrd`, `mdcrd`) with optional NetCDF trajectory support
- **`SimulationStage` and `SimulationProtocol`** models that aggregate parsed files, flag validation issues, and compute total steps and simulated time
- **Manifest-driven planning** with support for YAML, JSON, TOML, and CSV formats
- **Interactive CLI** (`ambermeta plan`) for quickly describing stage intent, restarts, expected gaps, and known discontinuities
- **Smart file discovery** with automatic sequence detection and pattern-based filtering
- **Automatic restart chain detection** to link simulation stages
- **Fluent Builder API** for programmatic protocol construction
- **Environment variable expansion** in manifest paths for portable configurations

## Installation

AmberMeta targets Python 3.8+. From the repository root install in editable mode for local development:

```bash
python -m pip install -e .
```

### Optional Extras

```bash
# NetCDF trajectory reading
python -m pip install -e ".[netcdf]"

# Test tooling
python -m pip install -e ".[tests]"

# TOML manifest support (Python < 3.11)
python -m pip install tomli
```

After installation the core models are available from the top-level package, while individual parsers live under `ambermeta.parsers`:

```python
from ambermeta import SimulationProtocol, SimulationStage, ProtocolBuilder, auto_discover
from ambermeta.parsers import MdoutParser, PrmtopParser
```

---

## Quick Start

### Basic File Discovery

```python
from ambermeta import auto_discover

# Discover and parse all AMBER files in a directory
protocol = auto_discover("/path/to/amber_runs")

# Print summary
print(f"Found {len(protocol.stages)} stages")
totals = protocol.totals()
print(f"Total simulation time: {totals['time_ps']:.2f} ps")
```

### Using a Manifest

```python
from ambermeta import load_protocol_from_manifest

# Load from YAML, JSON, TOML, or CSV
protocol = load_protocol_from_manifest("protocol.yaml")

# Validate and inspect
for stage in protocol.stages:
    print(f"{stage.name}: {stage.stage_role} - {stage.summary()['result']}")
```

### Using the Builder API

```python
from ambermeta import ProtocolBuilder

protocol = (
    ProtocolBuilder()
    .from_directory("/path/to/files", recursive=True)
    .with_grouping_rules({"prod": "production", "equil": "equilibration"})
    .auto_detect_restarts()
    .with_stage_tolerance("prod_002", expected_gap_ps=0.0, tolerance_ps=0.1)
    .build()
)
```

---

## Command Line Interface

### Basic Usage

```bash
# Build from a manifest and summarize
ambermeta plan --manifest protocol.yaml /path/to/amber_runs

# Recursively discover stage files
ambermeta plan --recursive /path/to/amber_runs

# Interactive mode (prompts for stage configuration)
ambermeta plan /path/to/amber_runs

# Write structured summary
ambermeta plan --manifest protocol.yaml --summary-path protocol.json
```

### CLI Subcommands

| Command | Description |
|---------|-------------|
| `plan` | Build and summarize a SimulationProtocol from manifest or interactive input |
| `validate` | Quick validation of simulation files with colored output |
| `info` | Display detailed metadata for a single file |
| `init` | Generate example manifest templates |

### Plan Command Options

```bash
ambermeta plan [directory] [options]

Options:
  -m, --manifest PATH          Path to YAML/JSON/TOML/CSV manifest
  --recursive                  Scan subdirectories
  --skip-cross-stage-validation  Skip continuity checks
  -v, --verbose               Show detailed metadata
  --summary-path PATH         Write JSON/YAML summary
  --summary-format {json,yaml}  Force summary format
  --methods-summary-path PATH   Write methods-ready JSON
  --stats-csv PATH            Export statistics to CSV
  --no-expand-env             Disable environment variable expansion
  --pattern REGEX             Filter files by regex pattern
  --auto-detect-restarts      Auto-detect restart file chains
```

### Validate Command

```bash
# Validate individual files
ambermeta validate system.prmtop equil.mdin prod.mdout

# Strict mode (warnings as errors)
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

# Generate with different complexity levels
ambermeta init --template minimal my_project
ambermeta init --template comprehensive my_project

# Custom output filename
ambermeta init -o my_protocol.yaml my_project
```

---

## Manifest Formats

AmberMeta supports four manifest formats, auto-detected by file extension:

### YAML (.yaml, .yml)

```yaml
# protocol.yaml
- name: minimize
  stage_role: minimization
  prmtop: system.prmtop
  mdin: min.in
  mdout: min.out

- name: equilibrate
  stage_role: equilibration
  files:
    prmtop: system.prmtop
    mdin: equil.in
    mdout: equil.out
    mdcrd: equil.nc
  inpcrd: min.rst7
  notes:
    - "NVT equilibration at 300K"

- name: production
  stage_role: production
  prmtop: system.prmtop
  mdin: prod.in
  mdout: prod.out
  mdcrd: prod.nc
  inpcrd: equil.rst7
  gaps:
    expected_ps: 0.0
    tolerance_ps: 0.1
```

### JSON (.json)

```json
[
  {
    "name": "minimize",
    "stage_role": "minimization",
    "prmtop": "system.prmtop",
    "mdin": "min.in",
    "mdout": "min.out"
  },
  {
    "name": "production",
    "stage_role": "production",
    "files": {
      "prmtop": "system.prmtop",
      "mdin": "prod.in",
      "mdout": "prod.out",
      "mdcrd": "prod.nc"
    },
    "inpcrd": "equil.rst7"
  }
]
```

### TOML (.toml)

```toml
# protocol.toml
[[stages]]
name = "minimize"
stage_role = "minimization"
prmtop = "system.prmtop"
mdin = "min.in"
mdout = "min.out"

[[stages]]
name = "production"
stage_role = "production"
prmtop = "system.prmtop"
mdin = "prod.in"
mdout = "prod.out"
mdcrd = "prod.nc"
inpcrd = "equil.rst7"
```

### CSV (.csv)

```csv
name,stage_role,prmtop,mdin,mdout,mdcrd,inpcrd,notes
minimize,minimization,system.prmtop,min.in,min.out,,,Initial minimization
equilibrate,equilibration,system.prmtop,equil.in,equil.out,equil.nc,min.rst7,NVT at 300K
production,production,system.prmtop,prod.in,prod.out,prod.nc,equil.rst7,Main production run
```

---

## Environment Variables in Manifests

Use `${VAR}` or `$VAR` syntax in file paths for portable configurations:

```yaml
# Uses $HOME and $PROJECT_ROOT environment variables
- name: production
  stage_role: production
  prmtop: ${PROJECT_ROOT}/systems/complex.prmtop
  mdin: $HOME/templates/prod.in
  mdout: ${PROJECT_ROOT}/output/prod.out
```

Disable expansion with `--no-expand-env` or `expand_env=False`:

```bash
ambermeta plan --manifest protocol.yaml --no-expand-env
```

```python
protocol = load_protocol_from_manifest("protocol.yaml", expand_env=False)
```

---

## Python API Examples

### Auto-Discovery with Options

```python
from ambermeta import auto_discover

# Basic discovery
protocol = auto_discover("/path/to/amber_runs")

# Recursive discovery with grouping rules
protocol = auto_discover(
    "/path/to/amber_runs",
    recursive=True,
    grouping_rules={
        "min": "minimization",
        "heat": "heating",
        "equil": "equilibration",
        "prod": "production",
    },
)

# With pattern filtering (only production runs)
protocol = auto_discover(
    "/path/to/amber_runs",
    pattern_filter=r"prod_\d+",
    auto_detect_restarts=True,
)

# With explicit restart files
protocol = auto_discover(
    "/path/to/amber_runs",
    restart_files={
        "prod_001": "/path/to/equil.rst7",
        "production": "/path/to/default.rst7",  # By role
    },
)
```

### Using the Builder API

```python
from ambermeta import ProtocolBuilder

# Full-featured builder example
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

# Manual stage construction
protocol = (
    ProtocolBuilder()
    .from_directory("/path/to/files")
    .add_stage(
        name="min",
        stage_role="minimization",
        prmtop="system.prmtop",
        mdin="min.in",
        mdout="min.out",
    )
    .add_stage(
        name="equil",
        stage_role="equilibration",
        prmtop="system.prmtop",
        mdin="equil.in",
        mdout="equil.out",
        inpcrd="min.rst7",
        expected_gap_ps=0.0,
    )
    .add_stage(
        name="prod",
        stage_role="production",
        prmtop="system.prmtop",
        mdin="prod.in",
        mdout="prod.out",
        mdcrd="prod.nc",
        inpcrd="equil.rst7",
    )
    .build()
)
```

### Validating and Inspecting Stages

```python
from ambermeta import auto_discover

protocol = auto_discover("/path/to/amber_runs")

# Protocol is validated during discovery, but can re-validate
protocol.validate(cross_stage=True)

# Get totals
totals = protocol.totals()
print(f"Total steps: {totals['steps']:.0f}")
print(f"Total time: {totals['time_ps']:.3f} ps")

# Inspect individual stages
for stage in protocol.stages:
    summary = stage.summary()
    print(f"\n{stage.name}")
    print(f"  Role: {summary['intent']}")
    print(f"  Result: {summary['result']}")

    # Check validation notes
    for note in stage.validation:
        print(f"  Note: {note}")

    # Access parsed file metadata
    if stage.prmtop and stage.prmtop.details:
        print(f"  Atoms: {stage.prmtop.details.natom}")
    if stage.mdin and stage.mdin.details:
        print(f"  Steps: {stage.mdin.details.length_steps}")
        print(f"  Timestep: {stage.mdin.details.dt} ps")
```

### Exporting Data

```python
from ambermeta import auto_discover
import json

protocol = auto_discover("/path/to/amber_runs")

# Export full protocol data
with open("protocol.json", "w") as f:
    json.dump(protocol.to_dict(), f, indent=2)

# Export methods-ready summary
with open("methods.json", "w") as f:
    json.dump(protocol.to_methods_dict(), f, indent=2)
```

### Smart File Grouping

```python
from ambermeta import detect_numeric_sequences, smart_group_files

# Detect sequences in filenames
files = ["prod_001.out", "prod_002.out", "prod_003.out", "equil.out"]
sequences = detect_numeric_sequences(files)
# Returns: {"prod_": ["prod_001.out", "prod_002.out", "prod_003.out"]}

# Smart grouping with pattern filter
grouped = smart_group_files(
    "/path/to/files",
    pattern=r"prod_\d+",
    recursive=True,
)
# Returns: {"prod_001": {"mdin": "...", "mdout": "...", "_sequence_base": "prod_"}}
```

### Restart Chain Detection

```python
from ambermeta import auto_discover, auto_detect_restart_chain

# Auto-detect restarts during discovery
protocol = auto_discover(
    "/path/to/amber_runs",
    auto_detect_restarts=True,
)

# Or detect manually
protocol = auto_discover("/path/to/amber_runs")
restart_mapping = auto_detect_restart_chain(protocol.stages, "/path/to/amber_runs")
# Returns: {"prod_002": "/path/to/prod_001.rst7", "prod_003": "/path/to/prod_002.rst7"}
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

## Sample Data and Tests

Sample AMBER inputs and outputs are in `tests/data/amber/md_test_files`. Try them with:

```python
from pathlib import Path
from ambermeta import auto_discover

sample_dir = Path("tests/data/amber/md_test_files")
protocol = auto_discover(
    str(sample_dir),
    grouping_rules={"CH3L1": "equilibration", "^ntp_prod": "production"},
    restart_files={"production": str(sample_dir / "ntp_prod_0000.rst")},
    skip_cross_stage_validation=True,
)
```

Run the automated tests with:

```bash
pytest
```

---

## Configuration

### Logging

Configure logging via CLI or API:

```bash
# CLI options
ambermeta --log-level DEBUG plan .
ambermeta --log-file debug.log plan .
ambermeta --quiet plan .  # Errors only
```

```python
from ambermeta.logging_config import configure_logging

configure_logging(
    level="DEBUG",
    log_file="ambermeta.log",
    format_style="verbose",
)
```

---

## Documentation

- [Manifest Schema](docs/manifest.md) - Full manifest format documentation
- [Improvement Plan](IMPROVEMENT_PLAN.md) - Development roadmap and changelog

---

## License

See LICENSE file for details.
