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

# Optional GUI
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

**`--auto` mode behavior:** Recursively discovers simulation files and produces
one stage per file-group stem (numbered sequences such as `prod_01`, `prod_02`
are each kept as a separate stage, not collapsed). Discovered topology files are
classified automatically: if a prmtop has HMR-scaled masses, it is emitted as
top-level `hmr_prmtop`; otherwise as `global_prmtop`. HMR detection falls back
to atom name patterns when the `ATOMIC_NUMBER` section is absent.

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
- `--pattern` (only applies with `--recursive`; ignored otherwise with a warning)
- `--auto-detect-restarts`
- `--skip-cross-stage-validation` (overrides `settings.strict_validation` in the manifest)
- `--strict` (abort on the first unreadable/malformed input file; default is to skip it and continue)
- `--prmtop`
- `--summary-path`
- `--summary-format {json,yaml}`
- `--methods-summary-path`
- `--stats-csv`
- `--no-expand-env`
- `-v, --verbose`

**Handling unreadable files:** By default, `plan` is fault-tolerant. If an input
file is missing, malformed, or unreadable (permission denied), that file is
skipped, the error is recorded against its stage, and a summary of skipped files
is printed; the run still completes and exits `0`. Pass `--strict` to make any
unreadable file a hard error (clean message, exit `1`, no traceback). A stage
keeps every file that *did* parse — a corrupt `mdout` does not discard a good
`prmtop` or `mdin`.

**Cross-stage validation:** By default, continuity checks between consecutive
stages are enabled unless `settings.strict_validation: false` is set in the
manifest. Pass `--skip-cross-stage-validation` to skip them unconditionally,
overriding the manifest setting.

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

## Optional GUI

The GUI is an optional, browser-based wrapper around the manifest/protocol workflow. The CLI remains the fully headless, scriptable interface (ideal for SSH/cluster use).

```bash
ambermeta gui /path/to/simulations --host 127.0.0.1 --port 8765
ambermeta gui /path/to/simulations --no-browser
```

### CLI equivalents (no GUI needed)

Everything the GUI does maps to a CLI flow:

- **Create/edit a manifest interactively**
  - `ambermeta plan /path/to/simulations --interactive`

- **Auto-group files from a folder**
  - `ambermeta init /path/to/simulations --auto --output manifest.yaml --force`

- **Run protocol analysis and export artifacts**
  ```bash
  ambermeta plan /path/to/simulations --manifest manifest.yaml \
    --summary-path summary.json \
    --methods-summary-path methods-summary.json \
    --stats-csv stats.csv
  ```

---

## Recent bug fixes (v0.2.1)

A comprehensive audit of the full codebase identified and fixed 40 bugs across all modules.

### Critical fixes
- **HMR prmtop feature now works**: Fixed attribute access (`stage.mdin.dt` &rarr; `stage.mdin.details.dt`) that prevented HMR topology assignment from ever triggering.
- **TUI auto-generate multi-select fixed**: Replaced `RadioButton` (mutual exclusion) with `Checkbox` so users can select multiple file groups.
- **TUI session loading fixed**: Child widgets now receive the updated state reference after loading a session, preventing stale data display and silent corruption.

### Security fixes
- **5 path traversal vulnerabilities patched** in the GUI API (`/api/files`, `/api/files/metadata`, session save/load, related files). All paths are now validated against the base directory.
- **CORS restricted to localhost** in the GUI server (was `allow_origins=["*"]`).

### High-priority fixes
- **Scientific notation parsing**: mdout regex and `_parse_value` now handle values like `1.234E+02` and `1E+05`.
- **Wall time parsing**: PMEMD `HH:MM:SS` format is now correctly parsed (was silently returning 0).
- **Validation deduplication**: `ProtocolBuilder.build()` no longer produces duplicate validation messages.
- **Stage role inference**: `infer_stage_role_from_path` and `_suggest_stage_role` use word-boundary matching instead of loose substring checks (e.g., "membrane" no longer matches "minimization").
- **TOML export**: Windows backslash paths are now properly escaped using TOML literal strings.
- **Reorder safety**: The GUI reorder endpoint now rejects partial stage ID lists instead of silently dropping stages.
- **License metadata corrected**: `pyproject.toml` and `setup.py` now declare BUSL-1.1 (matching the actual LICENSE file).
- **GUI dependencies installable**: `setup.py` now includes the `gui` extras group.

### Medium-priority fixes
- Fixed crash on small inpcrd files (<100 bytes) during box dimension parsing.
- Fixed `TypeError` when sorting 0-frame NetCDF trajectory files with `None` timestamps.
- Fixed sander completion detection (was only checking for PMEMD's "Final Performance Info").
- Fixed triclinic box volume calculation in prmtop parser (was using orthogonal `a*b*c` formula).
- Fixed environment variable double-expansion when `${VAR}` values contain `$OTHER`.
- Fixed shell completion scripts advertising non-existent flags (`--open-browser`, `--reload`).
- Added warning when `--format` is used without `--auto` in `init` command.
- Fixed TUI: `RadioButton` &rarr; `Switch` for auto-restart toggle, lossy widget ID encoding, permission-denied folder crash, blocking file discovery on async event loop, overly broad sequence detection.
- Fixed TOML export falling through to manual formatter on Python 3.11+.
- Fixed manifest path resolution on Windows (forward slash in manifests now normalized).

### Low-priority fixes
- Fixed `ntc` type check before numeric comparison in mdout parser.
- Fixed double-newline generation in mdin comment stripping.
- Fixed `_validate_atoms` treating `n_atoms=0` as missing data.
- Fixed logging format style using raw argument instead of resolved log level.
- Removed dead code (`_format_avg_std`, unused `stem_key` variable).
- Narrowed exception handling in TUI (`NoMatches` instead of bare `Exception`).
- Batch undo for auto-generated stages (single undo state instead of per-stem).

---

## Limitations and roadmap

Current limitations:

- CLI is the most complete and stable interface; the GUI is an optional browser-based front end over the same core.
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
- `-q, --quiet` — suppresses all stdout output; errors and usage messages still go to stderr

---

## Shell completion

```bash
ambermeta completion bash
ambermeta completion zsh
ambermeta completion fish
```
