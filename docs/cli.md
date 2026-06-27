# CLI reference

**The `ambermeta` command line is the complete, headless interface to the engine** — everything AmberMeta does is reachable here, no GUI required. It is the right surface for scripting, CI gates, and cluster/SSH work.

Six commands sit under one entry point:

| Command | Purpose |
|---|---|
| [`plan`](#plan) | Build and summarize a protocol; export reproducibility artifacts |
| [`init`](#init) | Generate a manifest (template, or `--auto` from a directory) |
| [`validate`](#validate) | Validate files without building a full protocol |
| [`info`](#info) | Print parsed metadata for a single file |
| [`gui`](#gui) | Launch the browser GUI |
| [`completion`](#completion) | Emit a shell-completion script |

> The help blocks below are generated directly from `ambermeta/cli.py::build_parser()` and kept in sync by CI (`scripts/export_cli_help.py --check`). They are the authoritative flag list.

---

## Install & completion

```bash
python -m pip install -e .
ambermeta --help
```

Generate a completion script for your shell:

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

## Global options

These apply before the subcommand:

| Option | Effect |
|---|---|
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | Logging verbosity (default `INFO`) |
| `--log-file PATH` | Also write logs to a file |
| `-q`, `--quiet` | Suppress stdout; errors/usage still go to stderr |

<!-- BEGIN_CLI_HELP:root -->
```text
usage: ambermeta [-h] [--log-level {DEBUG,INFO,WARNING,ERROR}]
                 [--log-file LOG_FILE] [-q]
                 {plan,validate,info,init,gui,completion} ...

AmberMeta - Simulation provenance engine for AMBER molecular dynamics.

Extract, organize, and validate metadata from AMBER simulation files.
Supports prmtop, mdin, mdout, mdcrd (NetCDF), and restart files.

positional arguments:
  {plan,validate,info,init,gui,completion}
    plan                Build and summarize a SimulationProtocol from
                        manifest, recursive discovery, or explicit interactive
                        mode
    validate            Validate simulation files without building full
                        protocol
    info                Display detailed metadata for a single file
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
  validate  Quick validation of simulation files
  info      Display detailed metadata for a single file
  init      Generate example manifest templates

Examples:
  ambermeta plan -m manifest.yaml           Build protocol from manifest
  ambermeta plan . --recursive              Auto-discover files recursively
  ambermeta plan . --interactive            Prompt for stage definitions
  ambermeta plan -m manifest.yaml \
    --methods-summary-path methods.json     Export publication-ready summary
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

```bash
ambermeta --log-level DEBUG plan . --recursive
ambermeta --quiet plan . --recursive --summary-path out.json
```

---

## `plan`

Build and summarize a `SimulationProtocol` from a manifest, recursive discovery, or interactive prompts — and export artifacts. **Pick exactly one mode:** `--manifest`, `--recursive`, or `--interactive`.

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

### Modes

| Mode | Flag | Behavior |
|---|---|---|
| Manifest | `-m/--manifest FILE` | Load stages from the manifest; honors `settings.strict_validation` |
| Discovery | `--recursive` | Group files by stem and infer roles; `--pattern REGEX` filters (this mode only) |
| Interactive | `--interactive` | Prompt for each stage's files, role, restart, and gap/tolerance |

### Exports

| Flag | Output |
|---|---|
| `--summary-path FILE` | Full protocol summary (JSON/YAML; `--summary-format` forces the format) |
| `--methods-summary-path FILE` | Materials-&-Methods JSON: software, MD engine settings, system composition, restraints |
| `--stats-csv FILE` | Per-stage statistics (one row per stage) |

The CSV header is exactly:

```text
stage_name,stage_role,time_start_ps,time_end_ps,duration_ns,frame_count,temp_avg,temp_std,pressure_avg,pressure_std,density_avg,density_std,etot_avg,etot_std
```

### Behavior

- **Fault-tolerant by default.** A missing/malformed/unreadable file is skipped, the error is recorded against its stage, a skip summary is printed, and the run exits `0`. `--strict` makes the first bad file a hard error (clean message, exit `1`, no traceback). A stage keeps every file that *did* parse.
- **Cross-stage validation** runs unless `settings.strict_validation: false`; `--skip-cross-stage-validation` overrides the manifest and skips it unconditionally.

```text
$ ambermeta plan tests/data/amber/md_test_files --recursive

Scanning .../md_test_files recursively for simulation files...
Discovered 7 stage(s).

Protocol summary
================
Stages: 7
Total steps: 25000000
Total simulated time (ps): 100000.000

- ntp_prod_0001
  intent: Production [NPT (isotropic)]
  result: Completed
  mdout: status=complete, steps=5000000, dt=0.004 ps, thermostat=Langevin @ 300 K, barostat=Berendsen
  stats: frames=200, time=1020–20920 ps, temp=300.43 ± 1.25 K, density=1.0370 ± 0.0012 g/cc
  evidence: INFO: Part of sequence 'ntp_prod' (item 2 of 6); INFO: stage_role inferred from mdin file
```

---

## `init`

Generate a manifest — a template, or `--auto` to bootstrap one from a directory.

```bash
ambermeta init [directory] [options]
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

`--auto` discovers files recursively and writes **one stage per file-group stem** — numbered sequences (`prod_0001`, `prod_0002`, …) stay separate, not collapsed. Topology is classified automatically: an HMR-scaled prmtop becomes top-level `hmr_prmtop`, others `global_prmtop` (HMR detection checks the `ATOMIC_NUMBER` section, falling back to atom-name patterns). Use `--dry-run` to preview without writing.

```text
$ ambermeta init tests/data/amber/md_test_files --auto --dry-run

Auto-grouped stages:
  global_prmtop: CH3L1_HUMAN_6NAG.top
  1. CH3L1_HUMAN_6NAG [unclassified]
     mdcrd: CH3L1_HUMAN_6NAG.crd
  2. ntp_prod_0000 [production]
     inpcrd: ntp_prod_0000.rst
  3. ntp_prod_0001 [production]
     mdin: ntp_prod_0001.mdin
     mdout: ntp_prod_0001.mdout
     inpcrd: ntp_prod_0001.rst
  ...

Dry run complete; no files were written.
```

> ⚠️ `--auto` is non-interactive and needs `--force` to overwrite an existing output file. `--format` only applies in `--auto` mode (it warns otherwise).

---

## `validate`

Validate one or more files without building a full protocol. Exit `0` on pass, `1` on failure — designed for CI.

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

Status per file: **OK** (parsed, no warnings), **WARN** (parsed, has warnings), **ERROR** (unreadable/missing). `--strict` turns warnings into a non-zero exit.

```text
$ ambermeta validate tests/data/amber/md_test_files/ntp_prod_0001.{mdin,mdout}

Validation Results
==================================================
OK: ntp_prod_0001.mdin
OK: ntp_prod_0001.mdout
==================================================
Validation PASSED
```

```text
$ ambermeta validate --format json tests/data/amber/md_test_files/ntp_prod_0001.mdout
{
  "status": "ok",
  "files": [
    { "file": ".../ntp_prod_0001.mdout", "status": "ok", "warnings": [], "errors": [] }
  ],
  "warnings": [],
  "errors": []
}
```

---

## `info`

Print parsed metadata for a single file.

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

The field names printed here are the parser metadata fields documented in the [API reference §6](api.md#6-parser-metadata-fields). Use `--format json` to feed the metadata into other tools.

```text
$ ambermeta info tests/data/amber/md_test_files/ntp_prod_0001.mdin
File Information: ntp_prod_0001.mdin
============================================================
  length_steps: 5000000
  dt: 0.004
  ensemble: NPT (isotropic)
  stage_role: Production [NPT (isotropic)]
  cutoff: 9.0
  temp_control: Langevin Dynamics
  target_temp: 300.0
  press_control: Berendsen (Isotropic)
  constraints: H-bonds
```

---

## `gui`

Launch the browser-based manifest editor (requires the `gui` extra). See the [GUI guide](gui.md).

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

```bash
ambermeta gui runs/                       # opens http://127.0.0.1:8765
ambermeta gui runs/ --port 9000 --no-browser
```

---

## `completion`

Print a shell-completion script.

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

See [Install & completion](#install--completion) for one-time setup per shell.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success (including a fault-tolerant `plan` that skipped bad files) |
| `1` | Error — invalid input, parse failure, validation failure, or a `--strict` hard stop |

---

## Environment variables

Manifest paths support `${VAR}`/`$VAR` expansion by default:

```yaml
stages:
  - name: production
    prmtop: ${PROJECT_DIR}/system.prmtop
    mdout: ${PROJECT_DIR}/output/prod.mdout
```

Disable with `--no-expand-env`. Full rules in the [manifest reference §6](manifest.md#6-environment-variable-expansion).

---

## See also

- [README](../README.md) — overview and quickstart
- [Tutorials](tutorials.md) — task-oriented walkthroughs · [Recipes](recipes.md) — copy-paste one-liners
- [Manifest schema](manifest.md) · [Python API](api.md) · [GUI guide](gui.md)
