# Command Line Interface Reference

AmberMeta provides a comprehensive command-line interface for parsing, validating, and analyzing AMBER molecular dynamics simulation files.

## Table of Contents

- [Installation](#installation)
- [Global Options](#global-options)
- [Commands](#commands)
  - [plan](#plan-command)
  - [init](#init-command)
  - [validate](#validate-command)
  - [info](#info-command)
  - [tui](#tui-command)
  - [gui](#gui-command)
  - [completion](#completion-command)
- [Shell completion setup](#shell-completion-setup)
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

### Enable shell completion

You can generate completion scripts directly from the CLI:

```bash
# Bash
ambermeta completion bash > ~/.local/share/bash-completion/completions/ambermeta

# Zsh
ambermeta completion zsh > ~/.zfunc/_ambermeta

# Fish
ambermeta completion fish > ~/.config/fish/completions/ambermeta.fish
```

Then reload your shell (`source ~/.bashrc`, `exec zsh`, or restart fish).

---

## Global Options

CLI help below is generated directly from `ambermeta/cli.py::build_parser()`.

<!-- BEGIN_CLI_HELP:root -->
```text
usage: ambermeta [-h] [--log-level {DEBUG,INFO,WARNING,ERROR}]
                 [--log-file LOG_FILE] [-q]
                 {plan,validate,info,tui,init,gui,completion} ...

AmberMeta - Simulation provenance engine for AMBER molecular dynamics.

Extract, organize, and validate metadata from AMBER simulation files.
Supports prmtop, mdin, mdout, mdcrd (NetCDF), and restart files.

positional arguments:
  {plan,validate,info,tui,init,gui,completion}
    plan                Build and summarize a SimulationProtocol from
                        manifest, recursive discovery, or explicit interactive
                        mode
    validate            Validate simulation files without building full
                        protocol
    info                Display detailed metadata for a single file
    tui                 Launch interactive TUI for building protocol manifests
    init                Generate an example manifest file
    gui                 Launch web-based GUI for building protocol manifests
    completion          Print shell completion script for bash, zsh, or fish

options:
  -h, --help            show this help message and exit
  --log-level {DEBUG,INFO,WARNING,ERROR}
                        Set logging level (default: INFO)
  --log-file LOG_FILE   Write logs to a file in addition to stderr
  -q, --quiet           Suppress all output except errors

Commands:
  plan      Build a simulation protocol from manifest or auto-discovery
  tui       Launch interactive terminal UI for building manifests
  validate  Quick validation of simulation files
  info      Display detailed metadata for a single file
  init      Generate example manifest templates

Examples:
  ambermeta plan -m manifest.yaml           Build protocol from manifest
  ambermeta plan . --recursive              Auto-discover files recursively
  ambermeta plan . --interactive            Prompt for stage definitions
  ambermeta plan -m manifest.yaml \
    --methods-summary-path methods.json     Export publication-ready summary
  ambermeta tui /path/to/simulations        Launch interactive TUI
  ambermeta validate system.prmtop *.mdout  Validate multiple files
  ambermeta info --format json system.prmtop  Show metadata as JSON
  ambermeta init --template standard .      Generate manifest template

File Types:
  prmtop:  .prmtop, .top, .parm7    (topology/parameters)
  mdin:    .mdin, .in               (input control)
  mdout:   .mdout, .out             (output log)
  mdcrd:   .nc, .mdcrd, .crd        (trajectory)
  inpcrd:  .rst, .rst7, .ncrst      (coordinates/restart)

For documentation, visit: https://github.com/MicheleBonus/ambermeta
```
<!-- END_CLI_HELP:root -->

### Examples

```bash
# Debug logging
ambermeta --log-level DEBUG plan --recursive .

# Write logs to file
ambermeta --log-file debug.log plan --manifest protocol.yaml

# Quiet mode — suppresses all stdout output; errors/usage still go to stderr
ambermeta --quiet plan --recursive . --summary-path output.json
```

---

## Commands

> **Note:** TUI (`ambermeta tui`) and GUI (`ambermeta gui`) are optional extras. The core AmberMeta workflow is fully supported by the CLI commands below.

### Plan Command

Build and summarize a SimulationProtocol from a manifest, recursive discovery, or explicit interactive mode.

```bash
ambermeta plan [directory] [options]
```

<!-- BEGIN_CLI_HELP:plan -->
```text
usage: ambermeta plan [-h] [-m MANIFEST] [--skip-cross-stage-validation]
                      [--strict] [--recursive] [--interactive] [-v]
                      [--summary-path SUMMARY_PATH]
                      [--summary-format {json,yaml}]
                      [--methods-summary-path METHODS_SUMMARY_PATH]
                      [--stats-csv STATS_CSV] [--no-expand-env]
                      [--pattern PATTERN] [--auto-detect-restarts]
                      [--prmtop PRMTOP]
                      [directory]

Build and summarize a SimulationProtocol from manifest, recursive discovery,
or explicit interactive mode. Interactive mode prompts for stage roles, file
paths, restart (inpcrd) paths, and expected gap/tolerance values.

positional arguments:
  directory             Directory containing the files referenced by the
                        manifest (default: current directory)

options:
  -h, --help            show this help message and exit
  -m MANIFEST, --manifest MANIFEST
                        Path to a YAML or JSON manifest describing stages and
                        file paths
  --skip-cross-stage-validation
                        Skip continuity checks between consecutive stages
                        (overrides the manifest's settings.strict_validation)
  --strict              Abort on the first unreadable/malformed input file
                        instead of skipping it. Default is to skip the file
                        and continue.
  --recursive           Auto-discover simulation files recursively (no
                        interactive prompts). Files are grouped by stem
                        (filename without extension) and stage roles are
                        inferred from directory names (equil→equilibration,
                        prod→production).
  --interactive         Enable interactive prompt mode for manually defining
                        stages.
  -v, --verbose         Show detailed metadata, warnings, and continuity
                        information for each stage
  --summary-path SUMMARY_PATH
                        Path to write a structured protocol summary (JSON or
                        YAML)
  --summary-format {json,yaml}
                        Force the structured summary format (default: inferred
                        from file extension)
  --methods-summary-path METHODS_SUMMARY_PATH
                        Write a Materials & Methods-ready JSON summary with
                        reproducibility-critical metadata (software versions,
                        MD settings, system composition, and trajectory
                        cadence) while omitting energies and other
                        nonessential arrays
  --stats-csv STATS_CSV
                        Export per-stage statistics to a CSV file
  --no-expand-env       Disable environment variable expansion in manifest
                        paths
  --pattern PATTERN     Regex pattern to filter discovered files (e.g.,
                        'prod_.*' for production runs)
  --auto-detect-restarts
                        Automatically detect and link restart files between
                        stages
  --prmtop PRMTOP       Global prmtop file to use for all stages (avoids
                        specifying it per stage)
```
<!-- END_CLI_HELP:plan -->

#### Modes of Operation

You must select one mode explicitly using `--manifest`, `--recursive`, or `--interactive`.

**1. Manifest Mode** (with `-m/--manifest`):
```bash
ambermeta plan -m protocol.yaml /path/to/simulations
```
Loads stages from the manifest file and parses referenced files. If the manifest
contains `settings.strict_validation: false`, cross-stage continuity checks are
skipped. Pass `--skip-cross-stage-validation` to override and skip them
unconditionally, regardless of the manifest setting.

**2. Recursive Discovery Mode** (with `--recursive`):
```bash
ambermeta plan --recursive /path/to/simulations
```
Automatically discovers and groups simulation files. Stage roles are inferred from
filenames. Use `--pattern` to filter discovered files by regex; `--pattern` only
applies in this mode and emits a warning to stderr if used without `--recursive`.

**3. Interactive Mode** (with `--interactive`):
```bash
ambermeta plan --interactive /path/to/simulations
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

---

### Init Command

Generate an example manifest file.

```bash
ambermeta init [options] [directory]
```

<!-- BEGIN_CLI_HELP:init -->
```text
usage: ambermeta init [-h] [-o OUTPUT]
                      [--template {minimal,standard,comprehensive}] [--auto]
                      [--format {yaml,json,toml,csv}] [--validate] [--dry-run]
                      [--force]
                      [directory]

Create a template manifest.yaml with example stages.

positional arguments:
  directory             Directory to scan for files (default: current
                        directory)

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output manifest filename (default: manifest.yaml)
  --template {minimal,standard,comprehensive}
                        Template complexity (default: standard)
  --auto                Non-interactive bootstrap mode: recursively discover
                        files and auto-generate grouped stages
  --format {yaml,json,toml,csv}
                        Manifest output format for --auto mode (default:
                        inferred from output extension or yaml)
  --validate            Run parsers against discovered files after writing the
                        manifest and print a concise summary
  --dry-run             Preview discovered stage grouping in --auto mode
                        without writing output files
  --force               Overwrite existing output file without prompting
                        (required for non-interactive --auto mode)
```
<!-- END_CLI_HELP:init -->

#### `--auto` mode

When `--auto` is passed, `init` recursively discovers simulation files and
generates **one stage per file-group stem**. Numbered sequences (e.g. `prod_01`,
`prod_02`) are each emitted as a separate stage rather than being collapsed.

Topology files are classified automatically:

- If a prmtop carries HMR-scaled masses it is written as top-level `hmr_prmtop`.
- All other topology files are written as top-level `global_prmtop`.

HMR detection checks the `ATOMIC_NUMBER` section first and falls back to atom
name patterns when that section is absent from the prmtop.

Use `--dry-run` to preview discovered stage grouping without writing any files.

---

### Validate Command

Quick validation of simulation files with colored output.

```bash
ambermeta validate [options] files...
```

<!-- BEGIN_CLI_HELP:validate -->
```text
usage: ambermeta validate [-h] [--strict] [--format {text,json,yaml}]
                          files [files ...]

Quick validation of simulation files with colored output.

positional arguments:
  files                 Files to validate (prmtop, mdin, mdout, mdcrd, inpcrd)

options:
  -h, --help            show this help message and exit
  --strict              Treat warnings as errors
  --format {text,json,yaml}
                        Output format (default: text)
```
<!-- END_CLI_HELP:validate -->

#### Output

- **OK** (green): File parsed successfully without warnings
- **WARN** (yellow): File parsed but has warnings
- **ERROR** (red): File could not be parsed or is missing

---

### Info Command

Display detailed metadata for a single simulation file.

```bash
ambermeta info [options] file
```

<!-- BEGIN_CLI_HELP:info -->
```text
usage: ambermeta info [-h] [--format {text,json,yaml}] file

Parse and display detailed metadata for AMBER simulation files.

positional arguments:
  file                  File to inspect (prmtop, mdin, mdout, mdcrd, inpcrd)

options:
  -h, --help            show this help message and exit
  --format {text,json,yaml}
                        Output format (default: text)
```
<!-- END_CLI_HELP:info -->

---

### TUI Command

Launch the interactive Terminal User Interface for building protocol manifests.

```bash
ambermeta tui [directory]
```

<!-- BEGIN_CLI_HELP:tui -->
```text
usage: ambermeta tui [-h] [directory]

Launch a terminal user interface for interactively building simulation
protocol manifests. Features include file browser, stage management, sequence
detection, and export to multiple formats.

positional arguments:
  directory   Directory containing simulation files (default: current
              directory)

options:
  -h, --help  show this help message and exit
```
<!-- END_CLI_HELP:tui -->

#### Features

The TUI provides:
- **File Browser**: Navigate directory tree with color-coded file types
- **Stage Management**: Create, edit, delete, and reorder stages
- **Sequence Detection**: Automatic detection of numbered file sequences
- **Global Settings**: Set global topology and HMR files
- **Export**: Save manifest in YAML, JSON, TOML, or CSV format
- **Undo/Redo**: Full undo/redo support

See [TUI Guide](tui.md) for detailed documentation.

---

### GUI Command

Launch the web-based Graphical User Interface for building protocol manifests.

```bash
ambermeta gui [directory] [options]
```

<!-- BEGIN_CLI_HELP:gui -->
```text
usage: ambermeta gui [-h] [--port PORT] [--no-browser] [--host HOST]
                     [directory]

Launch a modern web-based graphical user interface for building simulation
protocol manifests. Features include drag-and-drop file assignment, visual
stage management, sequence detection, and export to multiple formats. Opens in
your default web browser.

positional arguments:
  directory     Directory containing simulation files (default: current
                directory)

options:
  -h, --help    show this help message and exit
  --port PORT   Server port (default: 8765)
  --no-browser  Don't automatically open the browser
  --host HOST   Server host (default: 127.0.0.1)
```
<!-- END_CLI_HELP:gui -->

#### Features

The GUI provides:
- **Visual File Browser**: Navigate directory tree with drag-and-drop
- **Stage Builder**: Create, edit, delete, and reorder stages visually
- **Auto-Discovery**: One-click batch stage creation from file groups
- **Properties Panel**: Edit stage properties and global settings
- **Drag-and-Drop**: Assign files to stages by dragging
- **Session Management**: Save and load sessions
- **Export**: Save manifest in YAML, JSON, TOML, or CSV format
- **Undo/Redo**: Full undo/redo support
- **Keyboard Shortcuts**: Ctrl+S (save), Ctrl+O (load), Ctrl+A (auto-discover), Ctrl+E (export)

See [GUI Guide](gui.md) for detailed documentation.

---

### Completion Command

Print shell completion script for bash, zsh, or fish.

```bash
ambermeta completion {bash|zsh|fish}
```

<!-- BEGIN_CLI_HELP:completion -->
```text
usage: ambermeta completion [-h] {bash,zsh,fish}

Generate shell completion scripts for ambermeta commands.

positional arguments:
  {bash,zsh,fish}  Shell type for completion script

options:
  -h, --help       show this help message and exit
```
<!-- END_CLI_HELP:completion -->

## Shell completion setup

Use these one-time commands to install completion for your shell:

```bash
# bash
mkdir -p ~/.local/share/bash-completion/completions
ambermeta completion bash > ~/.local/share/bash-completion/completions/ambermeta
source ~/.bashrc

# zsh
mkdir -p ~/.zfunc
ambermeta completion zsh > ~/.zfunc/_ambermeta
echo 'fpath=(~/.zfunc $fpath)' >> ~/.zshrc
autoload -Uz compinit && compinit

# fish
mkdir -p ~/.config/fish/completions
ambermeta completion fish > ~/.config/fish/completions/ambermeta.fish
```


---

## Examples

### Complete Workflow

```bash
# 1. Initialize manifest template
ambermeta init --template standard /path/to/project

# 2. Edit manifest.yaml to match your files

# 3. Build and validate protocol
ambermeta plan -m manifest.yaml /path/to/project --verbose

# 4. Export structured summary
ambermeta plan -m manifest.yaml /path/to/project --summary-path protocol.json

# 5. Generate publication methods summary
ambermeta plan -m manifest.yaml /path/to/project --methods-summary-path methods.json

# 6. Export statistics
ambermeta plan -m manifest.yaml /path/to/project --stats-csv stats.csv

# 7. Validate individual files as needed
ambermeta validate /path/to/project/*.mdout
```

### Auto-Discovery Workflow

```bash
# Discover and process all files recursively
ambermeta plan --recursive /path/to/simulation_data

# With filtering and outputs
ambermeta plan --recursive --pattern "prod_.*" /path/to/data \
    --summary-path prod_summary.json \
    --stats-csv prod_stats.csv
```

### Quick Inspection Workflow

```bash
# Check file metadata
ambermeta info system.prmtop

# Validate critical files
ambermeta validate --strict system.prmtop production.mdout

# Generate quick template
ambermeta init --template minimal .
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Error (invalid input, parse failure, validation failure, etc.) |

---

## Environment Variables

AmberMeta supports environment variable expansion in manifest files by default.

Example manifest snippet:
```yaml
stages:
  - name: production
    prmtop: ${PROJECT_DIR}/system.prmtop
    mdout: ${PROJECT_DIR}/output/prod.mdout
```

Disable expansion with:
```bash
ambermeta plan -m manifest.yaml --no-expand-env
```

---

## See Also

- [README](../README.md) - Project overview and quick start
- [API Documentation](api.md) - Python API reference
- [TUI Guide](tui.md) - Interactive terminal interface
- [GUI Guide](gui.md) - Web-based graphical interface
- [Tutorials](tutorials.md) - Step-by-step usage examples
