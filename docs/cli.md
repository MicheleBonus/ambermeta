# Command Line Interface Reference

AmberMeta provides a comprehensive command-line interface for parsing, validating, and analyzing AMBER molecular dynamics simulation files.

## Table of Contents

- [Installation](#installation)
- [Global Options](#global-options)
- [Commands](#commands)
  - [plan](#plan-command)
  - [tui](#tui-command)
  - [validate](#validate-command)
  - [info](#info-command)
  - [init](#init-command)
- [Examples](#examples)
- [Exit Codes](#exit-codes)
- [Environment Variables](#environment-variables)

---

## Installation

After installing AmberMeta, the `ambermeta` command is available:

```bash
pip install -e .
ambermeta --help
```

---

## Global Options

These options apply to all commands:

| Option | Description |
|--------|-------------|
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | Set logging verbosity (default: INFO) |
| `--log-file PATH` | Write logs to a file in addition to stderr |
| `-q, --quiet` | Suppress all output except errors |
| `--help` | Show help message and exit |

### Examples

```bash
# Debug logging
ambermeta --log-level DEBUG plan --recursive .

# Write logs to file
ambermeta --log-file debug.log plan --manifest protocol.yaml

# Quiet mode (errors only)
ambermeta --quiet plan --recursive . --summary-path output.json
```

---

## Commands

### Plan Command

Build and summarize a SimulationProtocol from a manifest or interactive input.

```bash
ambermeta plan [directory] [options]
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `directory` | Directory containing simulation files (default: current directory) |

#### Options

| Option | Description |
|--------|-------------|
| `-m, --manifest PATH` | Path to YAML/JSON/TOML/CSV manifest file |
| `--recursive` | Auto-discover files recursively (no interactive prompts) |
| `--prmtop PATH` | Global topology file for all stages |
| `--skip-cross-stage-validation` | Skip continuity checks between stages |
| `-v, --verbose` | Show detailed metadata and validation info |
| `--summary-path PATH` | Write structured summary (JSON/YAML) |
| `--summary-format {json,yaml}` | Force summary format (default: inferred from extension) |
| `--methods-summary-path PATH` | Write methods-ready JSON for publications |
| `--stats-csv PATH` | Export per-stage statistics to CSV |
| `--no-expand-env` | Disable environment variable expansion in manifests |
| `--pattern REGEX` | Filter discovered files by regex pattern |
| `--auto-detect-restarts` | Automatically detect and link restart files |

#### Modes of Operation

**1. Manifest Mode** (with `-m/--manifest`):
```bash
ambermeta plan -m protocol.yaml /path/to/simulations
```
Loads stages from the manifest file and parses referenced files.

**2. Recursive Discovery Mode** (with `--recursive`):
```bash
ambermeta plan --recursive /path/to/simulations
```
Automatically discovers and groups simulation files. Stage roles are inferred from filenames.

**3. Interactive Mode** (default):
```bash
ambermeta plan /path/to/simulations
```
Prompts for stage definitions interactively.

#### Output Options

**Protocol Summary** (`--summary-path`):
```bash
ambermeta plan -m protocol.yaml --summary-path protocol.json
```

Generates a JSON/YAML file containing:
- All stages with metadata
- Parsed file information
- Validation notes
- Totals (steps, time)

**Methods Summary** (`--methods-summary-path`):
```bash
ambermeta plan -m protocol.yaml --methods-summary-path methods.json
```

Generates a publication-ready summary with:
- Software information
- MD engine settings (ensemble, thermostat, barostat)
- System composition
- Restraint information

**Statistics CSV** (`--stats-csv`):
```bash
ambermeta plan -m protocol.yaml --stats-csv stats.csv
```

Exports per-stage statistics:
- Stage name and role
- Time range and duration
- Temperature (mean ± std)
- Pressure (mean ± std)
- Density (mean ± std)
- Total energy (mean ± std)

#### Examples

```bash
# Basic manifest usage
ambermeta plan -m protocol.yaml

# Recursive discovery with verbose output
ambermeta plan --recursive -v /path/to/simulations

# Filter to production runs only
ambermeta plan --recursive --pattern "prod_\d+" /path/to/simulations

# Auto-detect restart chains
ambermeta plan --recursive --auto-detect-restarts /path/to/simulations

# Skip validation for independent replicas
ambermeta plan --recursive --skip-cross-stage-validation /path/to/replicas

# Use global topology
ambermeta plan --recursive --prmtop system.prmtop /path/to/simulations

# Export all outputs
ambermeta plan -m protocol.yaml \
    --summary-path protocol.json \
    --methods-summary-path methods.json \
    --stats-csv stats.csv \
    -v
```

---

### TUI Command

Launch the interactive Terminal User Interface for building protocol manifests.

```bash
ambermeta tui [directory] [options]
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `directory` | Directory containing simulation files (default: current directory) |

#### Options

| Option | Description |
|--------|-------------|
| `--recursive` | Enable recursive file discovery |
| `--show-all` | Show all files, not just simulation files |

#### Features

The TUI provides:
- **File Browser**: Navigate directory tree with color-coded file types
- **Stage Management**: Create, edit, delete, and reorder stages
- **Sequence Detection**: Automatic detection of numbered file sequences
- **Global Settings**: Set global topology and HMR files
- **Export**: Save manifest in YAML, JSON, TOML, or CSV format
- **Undo/Redo**: Full undo/redo support

#### Examples

```bash
# Launch TUI in current directory
ambermeta tui

# Launch with recursive discovery
ambermeta tui --recursive /path/to/project

# Show all files including non-simulation files
ambermeta tui --show-all /path/to/project
```

See [TUI Guide](tui.md) for detailed documentation.

---

### Validate Command

Quick validation of simulation files with colored output.

```bash
ambermeta validate [options] files...
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `files` | One or more files to validate |

#### Options

| Option | Description |
|--------|-------------|
| `--strict` | Treat warnings as errors |

#### Output

- **OK** (green): File parsed successfully without warnings
- **WARN** (yellow): File parsed but has warnings
- **ERROR** (red): File could not be parsed or is missing

#### Examples

```bash
# Validate multiple files
ambermeta validate system.prmtop equil.mdin prod.mdout

# Validate with glob pattern
ambermeta validate *.prmtop *.mdin

# Strict mode (warnings are errors)
ambermeta validate --strict system.prmtop

# Validate all files in directory
ambermeta validate simulations/*.prmtop simulations/*.mdout
```

#### Exit Codes

- `0`: All files valid (no errors, no warnings in strict mode)
- `1`: Validation failed (errors, or warnings in strict mode)

---

### Info Command

Display detailed metadata for a single simulation file.

```bash
ambermeta info [options] file
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `file` | File to inspect |

#### Options

| Option | Description |
|--------|-------------|
| `--format {text,json,yaml}` | Output format (default: text) |

#### Supported File Types

| File Type | Extensions |
|-----------|------------|
| prmtop | `.prmtop`, `.parm7`, `.top` |
| mdin | `.mdin`, `.in` |
| mdout | `.mdout`, `.out` |
| mdcrd | `.nc`, `.mdcrd`, `.crd`, `.x` |
| inpcrd | `.rst`, `.rst7`, `.ncrst`, `.inpcrd`, `.restrt` |

#### Examples

```bash
# Text format (default)
ambermeta info system.prmtop

# JSON output
ambermeta info --format json prod.mdout

# YAML output
ambermeta info --format yaml equil.mdin

# Pipe JSON to jq for filtering
ambermeta info --format json prod.mdout | jq '.natom'
```

#### Sample Output

**Text format:**
```
File Information: system.prmtop
============================================================
  natom: 45231
  nres: 12543
  box_dimensions: [80.5, 80.5, 80.5]
  box_angles: [90.0, 90.0, 90.0]
  solvent_type: TIP3P
  ions: {'Na+': 42, 'Cl-': 38}
  density: 1.0234
  is_hmr: False
```

**JSON format:**
```json
{
  "natom": 45231,
  "nres": 12543,
  "box_dimensions": [80.5, 80.5, 80.5],
  "solvent_type": "TIP3P",
  "ions": {"Na+": 42, "Cl-": 38},
  "density": 1.0234
}
```

---

### Init Command

Generate an example manifest file.

```bash
ambermeta init [options] [directory]
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `directory` | Directory to scan for files (default: current directory) |

#### Options

| Option | Description |
|--------|-------------|
| `-o, --output FILENAME` | Output filename (default: manifest.yaml) |
| `--template {minimal,standard,comprehensive}` | Template complexity (default: standard) |

#### Templates

**Minimal**: Basic structure with single stage
```yaml
stages:
  - name: production
    prmtop: system.prmtop
    mdin: prod.in
    mdout: prod.out
```

**Standard**: Common 4-stage workflow
```yaml
stages:
  - name: minimize
    stage_role: minimization
    ...
  - name: heat
    stage_role: heating
    ...
  - name: equilibrate
    stage_role: equilibration
    ...
  - name: production
    stage_role: production
    ...
```

**Comprehensive**: All available options with documentation
```yaml
settings:
  strict_validation: false
  allow_gaps: false

stage_role_rules:
  - pattern: "min.*"
    role: minimization
  ...

stages:
  - name: minimize_1
    stage_role: minimization
    gaps:
      expected: 0.0
      tolerance: 0.1
    notes:
      - "Initial minimization"
  ...
```

#### Examples

```bash
# Generate standard template
ambermeta init my_project

# Generate minimal template
ambermeta init --template minimal my_project

# Generate comprehensive template
ambermeta init --template comprehensive my_project

# Custom output filename
ambermeta init -o my_protocol.yaml my_project

# Generate in current directory
ambermeta init --template standard .
```

---

## Examples

### Complete Workflow

```bash
# 1. Initialize a manifest template
ambermeta init --template standard /path/to/simulations

# 2. Edit the manifest
vim /path/to/simulations/manifest.yaml

# 3. Validate the manifest
ambermeta plan -m /path/to/simulations/manifest.yaml -v

# 4. Export summaries
ambermeta plan -m /path/to/simulations/manifest.yaml \
    --summary-path protocol.json \
    --methods-summary-path methods.json \
    --stats-csv stats.csv
```

### Quick Analysis

```bash
# Discover and analyze all files
ambermeta plan --recursive /path/to/simulations

# With automatic restart detection
ambermeta plan --recursive --auto-detect-restarts /path/to/simulations

# Filter to specific files
ambermeta plan --recursive --pattern "prod" /path/to/simulations
```

### File Inspection

```bash
# Check a topology file
ambermeta info system.prmtop

# Inspect output statistics
ambermeta info --format json prod.mdout | jq '.stats'

# Validate multiple files
ambermeta validate system.prmtop *.mdin *.mdout
```

### TUI Workflow

```bash
# Launch TUI
ambermeta tui /path/to/simulations

# In TUI:
# 1. Press Ctrl+G to set global prmtop
# 2. Press Ctrl+A to auto-generate stages
# 3. Review and edit stages
# 4. Press Ctrl+E to export manifest
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Error or validation failure |

---

## Environment Variables

AmberMeta respects the following environment variables:

| Variable | Description |
|----------|-------------|
| `AMBERMETA_LOG_LEVEL` | Default log level (DEBUG, INFO, WARNING, ERROR) |
| `NO_COLOR` | Disable colored output when set |
| `TERM` | Terminal type (affects color support detection) |

### Manifest Environment Variables

Manifests can reference environment variables using `${VAR}` or `$VAR` syntax:

```yaml
- name: production
  prmtop: ${PROJECT_ROOT}/system.prmtop
  mdin: $HOME/templates/prod.in
```

Set variables before running:
```bash
export PROJECT_ROOT=/path/to/project
export OUTPUT_DIR=/scratch/output
ambermeta plan -m manifest.yaml
```

Disable expansion with `--no-expand-env`:
```bash
ambermeta plan -m manifest.yaml --no-expand-env
```

---

## Logging Configuration

### Log Levels

| Level | Description |
|-------|-------------|
| `DEBUG` | Detailed debugging information |
| `INFO` | General information (default) |
| `WARNING` | Warning messages |
| `ERROR` | Error messages only |

### Examples

```bash
# Debug output to console
ambermeta --log-level DEBUG plan -m manifest.yaml

# Write logs to file
ambermeta --log-file ambermeta.log plan -m manifest.yaml

# Quiet mode (errors only)
ambermeta --quiet plan --recursive . --summary-path output.json

# Combine options
ambermeta --log-level DEBUG --log-file debug.log plan -m manifest.yaml
```

---

## Tips and Best Practices

### Large Projects

```bash
# Use pattern filtering to process subsets
ambermeta plan --recursive --pattern "replica_01" /path/to/simulations

# Export only statistics for analysis
ambermeta plan --recursive --stats-csv all_stats.csv /path/to/simulations
```

### CI/CD Integration

```bash
# Strict validation in CI
ambermeta validate --strict *.prmtop *.mdin

# Generate reports
ambermeta plan -m manifest.yaml --quiet --summary-path report.json
```

### Scripting

```bash
# Check exit codes
if ambermeta validate --strict *.prmtop; then
    echo "Validation passed"
else
    echo "Validation failed"
    exit 1
fi

# Process JSON output
ATOMS=$(ambermeta info --format json system.prmtop | jq '.natom')
echo "System has $ATOMS atoms"
```
