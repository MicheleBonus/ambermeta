# AmberMeta

**AmberMeta is a simulation provenance engine for AMBER molecular dynamics workflows.**

It parses AMBER files (`prmtop`, `mdin`, `mdout`, `mdcrd`, `inpcrd`), assembles stages into a protocol, and helps you validate continuity and metadata before reporting results.

## What AmberMeta does

- Extracts metadata from AMBER simulation files.
- Builds stage-ordered protocols from a manifest or file discovery.
- Validates files and cross-stage continuity.
- Exports machine-readable artifacts for reporting and downstream analysis.

---

## Install

AmberMeta requires Python 3.8+.

### Core install

```bash
python -m pip install -e .
```

### Optional extras

```bash
# NetCDF trajectory parsing support
python -m pip install -e ".[netcdf]"

# YAML manifest support
python -m pip install -e ".[yaml]"

# TOML manifest support (mainly for Python < 3.11)
python -m pip install -e ".[toml]"

# Optional interfaces
python -m pip install -e ".[tui]"
python -m pip install -e ".[gui]"

# Test and dev dependencies
python -m pip install -e ".[tests]"
python -m pip install -e ".[dev]"

# Everything
python -m pip install -e ".[all]"
```

---

## CLI quickstart (CLI-only path)

```bash
# 1) Bootstrap a manifest from a simulation directory
ambermeta init /path/to/simulations --auto --output manifest.yaml --validate --force

# 2) Build protocol from the manifest and export artifacts
ambermeta plan /path/to/simulations \
  --manifest /path/to/simulations/manifest.yaml \
  --summary-path /path/to/simulations/summary.json \
  --methods-summary-path /path/to/simulations/methods-summary.json \
  --stats-csv /path/to/simulations/stats.csv

# 3) Validate specific files
ambermeta validate /path/to/simulations/system.prmtop /path/to/simulations/prod.mdout --format text

# 4) Inspect one file deeply
ambermeta info /path/to/simulations/prod.mdout --format json
```

---

## Command overview

### `init`
Create a starter manifest.

```bash
ambermeta init /path/to/simulations --output manifest.yaml
ambermeta init /path/to/simulations --auto --output manifest.yaml --format yaml --validate --force
ambermeta init /path/to/simulations --auto --dry-run
```

Key flags:
- `-o, --output`
- `--template {minimal,standard,comprehensive}`
- `--auto`
- `--format {yaml,json,toml,csv}`
- `--validate`
- `--dry-run`
- `--force`

### `plan`
Build and summarize a protocol from a manifest, recursive discovery, or interactive prompts.

```bash
ambermeta plan /path/to/simulations --manifest manifest.yaml
ambermeta plan /path/to/simulations --recursive --pattern 'prod_.*' --auto-detect-restarts
ambermeta plan /path/to/simulations --interactive
```

Key flags:
- `-m, --manifest`
- `--recursive`
- `--interactive`
- `--pattern`
- `--auto-detect-restarts`
- `--skip-cross-stage-validation`
- `--prmtop`
- `--summary-path`
- `--summary-format {json,yaml}`
- `--methods-summary-path`
- `--stats-csv`
- `--no-expand-env`
- `-v, --verbose`

### `validate`
Validate one or more files without building a full protocol.

```bash
ambermeta validate file1.prmtop file2.mdout
ambermeta validate file1.prmtop file2.mdout --strict --format json
```

Key flags:
- `--strict`
- `--format {text,json,yaml}`

### `info`
Inspect a single file and print parsed metadata.

```bash
ambermeta info /path/to/file.prmtop
ambermeta info /path/to/file.mdout --format yaml
```

Key flags:
- `--format {text,json,yaml}`

---

## End-to-end examples

### Example A: Manifest-driven workflow

```bash
ambermeta init ./runs --auto --output manifest.yaml --validate --force
ambermeta plan ./runs --manifest manifest.yaml --summary-path summary.yaml --summary-format yaml
ambermeta plan ./runs --manifest manifest.yaml --methods-summary-path methods-summary.json --stats-csv stats.csv
```

### Example B: Discovery-first workflow (no manifest file)

```bash
ambermeta plan ./runs --recursive --auto-detect-restarts --summary-path summary.json
ambermeta validate ./runs/system.prmtop ./runs/prod_01.mdout --format text
ambermeta info ./runs/prod_01.mdout --format json
```

---

## Output artifacts

When using `plan`, three export-oriented outputs are available:

- `--summary-path <file>`
  - Structured protocol summary (JSON or YAML).
  - Use `--summary-format` to force format; otherwise inferred from extension.

- `--methods-summary-path <file>`
  - Publication-oriented JSON summary emphasizing reproducibility-critical metadata.

- `--stats-csv <file>`
  - Per-stage statistics in CSV form (one row per stage with available metrics).

---

## Python API quickstart

```python
from ambermeta import auto_discover, load_protocol_from_manifest

# Auto-discover files recursively
protocol = auto_discover("/path/to/simulations", recursive=True)
print(len(protocol.stages), protocol.totals())

# Or load from a manifest
protocol2 = load_protocol_from_manifest("/path/to/simulations/manifest.yaml", "/path/to/simulations")
print(len(protocol2.stages), protocol2.totals())
```

---

## Optional interfaces (TUI/GUI)

These interfaces are optional wrappers around manifest/protocol workflows.

```bash
# TUI
ambermeta tui /path/to/simulations

# GUI
ambermeta gui /path/to/simulations --host 127.0.0.1 --port 8765
ambermeta gui /path/to/simulations --no-browser
```

### Migration note (TUI/GUI ➜ CLI)

If you previously relied on TUI/GUI, equivalent CLI flows are:

- **Create/edit manifest interactively**
  - Old: `ambermeta tui /path/to/simulations`
  - CLI alternative: `ambermeta plan /path/to/simulations --interactive`

- **Auto-group files from a folder**
  - Old: GUI/TUI discovery actions
  - CLI alternative: `ambermeta init /path/to/simulations --auto --output manifest.yaml --force`

- **Run protocol analysis and export artifacts**
  - Old: GUI export actions
  - CLI alternative:
    ```bash
    ambermeta plan /path/to/simulations --manifest manifest.yaml \
      --summary-path summary.json \
      --methods-summary-path methods-summary.json \
      --stats-csv stats.csv
    ```

---

## Limitations and roadmap

Current limitations:

- CLI is the most complete and stable interface; TUI/GUI are optional and may lag behind CLI capabilities.
- Some parsing features depend on optional dependencies (for example NetCDF support).
- Manifest parsing for YAML requires `pyyaml`.

Roadmap themes:

- Keep CLI as the source of truth for new functionality.
- Continue improving validation depth and export consistency.
- Improve parity between optional interfaces and CLI workflows.

---

## Maintenance rule for docs and CI

README command snippets must stay synchronized with `ambermeta.cli.build_parser()`.

At minimum, CI should validate:

```bash
ambermeta --help
ambermeta init --help
ambermeta plan --help
ambermeta validate --help
ambermeta info --help
```

and verify every documented flag exists in parser help output.

---

## Global CLI options

These apply before subcommands:

- `--log-level {DEBUG,INFO,WARNING,ERROR}`
- `--log-file <path>`
- `-q, --quiet`

---

## Shell completion

```bash
ambermeta completion bash
ambermeta completion zsh
ambermeta completion fish
```
