# Manifest Schema

AmberMeta supports manifest-driven planning for simulation protocols via multiple file formats. Manifests feed `load_protocol_from_manifest`, `auto_discover`, and the `ambermeta plan` CLI to assemble ordered `SimulationStage` objects and run per-stage and cross-stage validation.

## Supported Formats

| Format | Extension | Requires |
|--------|-----------|----------|
| YAML | `.yaml`, `.yml` | `pyyaml` package |
| JSON | `.json` | Built-in |
| TOML | `.toml` | `tomllib` (Python 3.11+) or `tomli` package |
| CSV | `.csv` | Built-in |

Format is auto-detected based on file extension.

---

## Top-Level Structure

- **Accepted types:** the manifest must be either a list of stage dictionaries or a mapping whose keys are stage names and whose values are dictionaries. Mixed or other types raise an error.
- **Stage dictionaries:** each stage entry is a mapping of metadata and file pointers. When the manifest is a mapping, the stage name key is copied into the stage entry when no explicit `name` is present.
- **Relative paths:** any relative file paths are resolved against the manifest directory when using `load_protocol_from_manifest` or the optional `directory` argument passed to `auto_discover`. The `ambermeta plan --manifest` command forwards its positional `directory` argument for this purpose.

---

## Required and Optional Keys Per Stage

### Required
- `name`: unique identifier used for ordering and restart lookups
- `stage_role`: high-level intent (e.g., `minimization`, `heating`, `equilibration`, `production`). If omitted, the role may be inferred from parsed `mdin` metadata when available; otherwise intent is reported as unknown.

### File References
Files may be specified under `files` or as top-level keys inside the stage:
- `prmtop` - Topology/parameter file
- `mdin` - Input control file
- `mdout` - Output log file
- `inpcrd` - Coordinate/restart file
- `mdcrd` - Trajectory file

Only these keys are consumed; others are ignored. At least one recognized file is recommended so the stage can be parsed and validated.

### Optional Metadata
- `notes`: string or list of strings that become validation notes
- `gaps` / `gap`: describes expected discontinuities before the stage
- `expected_gap_ps`: expected gap in picoseconds (alternative to nested `gaps`)
- `gap_tolerance_ps`: tolerance for gap validation (alternative to nested `gaps`)

### Restart Sources
Providing `inpcrd` marks the restart used for the stage. Programmatic callers may also pass a `restart_files` mapping to `auto_discover`/`load_protocol_from_manifest` to inject restarts by stage `name` or `stage_role` when absent from the manifest.

---

## Gap Configuration

The `gaps` or `gap` key describes expected discontinuities before a stage. It accepts several formats:

### As a dictionary
```yaml
gaps:
  expected: 100.0       # or expected_ps
  tolerance: 0.5        # or tolerance_ps
  notes:
    - "Gap due to restart from backup"
```

### As a number
```yaml
gaps: 100.0  # Expected gap in ps, no tolerance specified
```

### As a string or list (notes only)
```yaml
gaps: "Manual restart from backup"
# or
gaps:
  - "First note"
  - "Second note"
```

---

## Environment Variable Expansion

File paths support environment variable expansion using `${VAR}` or `$VAR` syntax:

```yaml
- name: production
  prmtop: ${PROJECT_ROOT}/systems/complex.prmtop
  mdin: $HOME/templates/prod.in
  mdout: ${PROJECT_ROOT}/output/prod.out
```

**Behavior:**
- Variables are expanded at manifest load time
- Undefined variables are left unchanged
- Expansion can be disabled with `expand_env=False` parameter or `--no-expand-env` CLI flag

---

## Format-Specific Examples

### YAML List Format

```yaml
# protocol.yaml - List of stages
- name: minimize
  stage_role: minimization
  prmtop: systems/complex.prmtop
  inpcrd: systems/complex.inpcrd
  mdin: mdin/minim.in
  mdout: logs/minim.out
  notes: Single-point minimization; no trajectory expected.

- name: heat
  stage_role: heating
  files:
    mdin: mdin/heat.mdin
    mdout: logs/heat.mdout
  inpcrd: restarts/minim.rst7
  gaps:
    expected_ps: 0
    tolerance_ps: 0.5
    notes:
      - Uses minim restart implicitly

- name: equilibrate
  stage_role: equilibration
  prmtop: systems/complex.prmtop
  mdin: mdin/equil.in
  mdout: logs/equil.out
  mdcrd: traj/equil.nc
  inpcrd: restarts/heat.rst7

- name: prod1
  stage_role: production
  mdin: mdin/prod1.in
  mdout: logs/prod1.out
  mdcrd: traj/prod1.nc
  inpcrd: restarts/equil.rst7
  expected_gap_ps: 0.0
  gap_tolerance_ps: 0.1

- name: prod2
  stage_role: production
  files:
    mdin: mdin/prod2.in
    mdout: logs/prod2.out
  gaps: 250  # Expect ~250 ps jump before this stage
  notes:
    - Trajectory intentionally omitted
```

### YAML Mapping Format

```yaml
# protocol.yaml - Mapping with stage names as keys
minimize:
  stage_role: minimization
  prmtop: system.prmtop
  mdin: min.in
  mdout: min.out

equilibrate:
  stage_role: equilibration
  prmtop: system.prmtop
  mdin: equil.in
  mdout: equil.out
  inpcrd: min.rst7

production:
  stage_role: production
  prmtop: system.prmtop
  mdin: prod.in
  mdout: prod.out
  mdcrd: prod.nc
  inpcrd: equil.rst7
```

### JSON List Format

```json
[
  {
    "name": "minimize",
    "stage_role": "minimization",
    "prmtop": "systems/complex.prmtop",
    "mdin": "mdin/minim.in",
    "mdout": "logs/minim.out"
  },
  {
    "name": "equilibrate",
    "stage_role": "equilibration",
    "files": {
      "mdin": "mdin/equil.in",
      "mdout": "logs/equil.out",
      "mdcrd": "traj/equil.nc"
    },
    "inpcrd": "restarts/minim.rst7"
  },
  {
    "name": "production",
    "stage_role": "production",
    "files": {
      "mdin": "mdin/prod.in",
      "mdout": "logs/prod.out",
      "mdcrd": "traj/prod.nc"
    },
    "gaps": {
      "expected": 0,
      "tolerance": 0.1
    }
  }
]
```

### JSON Mapping Format

```json
{
  "minimize": {
    "stage_role": "minimization",
    "prmtop": "system.prmtop",
    "mdin": "min.in",
    "mdout": "min.out"
  },
  "production": {
    "stage_role": "production",
    "prmtop": "system.prmtop",
    "mdin": "prod.in",
    "mdout": "prod.out",
    "mdcrd": "prod.nc",
    "inpcrd": "equil.rst7"
  }
}
```

### TOML Format

```toml
# protocol.toml - Using array of tables

[[stages]]
name = "minimize"
stage_role = "minimization"
prmtop = "systems/complex.prmtop"
inpcrd = "systems/complex.inpcrd"
mdin = "mdin/minim.in"
mdout = "logs/minim.out"
notes = "Single-point minimization"

[[stages]]
name = "heat"
stage_role = "heating"
mdin = "mdin/heat.mdin"
mdout = "logs/heat.mdout"
inpcrd = "restarts/minim.rst7"

[[stages]]
name = "equilibrate"
stage_role = "equilibration"
prmtop = "systems/complex.prmtop"
mdin = "mdin/equil.in"
mdout = "logs/equil.out"
mdcrd = "traj/equil.nc"
inpcrd = "restarts/heat.rst7"

[[stages]]
name = "production"
stage_role = "production"
prmtop = "systems/complex.prmtop"
mdin = "mdin/prod.in"
mdout = "logs/prod.out"
mdcrd = "traj/prod.nc"
inpcrd = "restarts/equil.rst7"
expected_gap_ps = 0.0
gap_tolerance_ps = 0.1
```

### CSV Format

```csv
name,stage_role,prmtop,mdin,mdout,mdcrd,inpcrd,expected_gap_ps,gap_tolerance_ps,notes
minimize,minimization,system.prmtop,min.in,min.out,,,,,"Initial minimization"
heat,heating,system.prmtop,heat.in,heat.out,,min.rst7,,,"Heat to 300K"
equilibrate,equilibration,system.prmtop,equil.in,equil.out,equil.nc,heat.rst7,0,0.1,"NVT equilibration"
production,production,system.prmtop,prod.in,prod.out,prod.nc,equil.rst7,0,0.1,"Main production run"
```

**CSV Notes:**
- First row must be headers
- Empty cells are treated as missing values
- Notes field supports semicolon-separated values for multiple notes
- Order of columns is flexible (determined by headers)

---

## Behavior in Consumers

### `load_manifest()`
Loads YAML, JSON, TOML (requires optional `tomllib`/`tomli`), or CSV, based on file extension. Returns the parsed manifest data structure with optional environment variable expansion.

### `load_protocol_from_manifest()`
Loads a manifest and passes it to `auto_discover()`, resolving relative paths against the manifest directory or specified `directory`.

### `auto_discover()`
When provided a manifest, parses each referenced file into a `SimulationStage`, attaches restart paths, applies gap expectations, and runs validation. When `manifest` is `None`, it discovers files on disk instead. Pass `recursive=True` to search subdirectories; stage names use the relative path (without extension) so nested files remain distinct.

### `ambermeta plan`
Uses the manifest path when provided; otherwise it prompts for the same stage keys interactively. Additional options:
- `--skip-cross-stage-validation` - Disables continuity checks (useful for non-contiguous protocols)
- `--no-expand-env` - Disables environment variable expansion
- `--auto-detect-restarts` - Automatically detect restart chains
- `--pattern REGEX` - Filter files by pattern

---

## Advanced Features

### Programmatic Restart Injection

When using `auto_discover` or `load_protocol_from_manifest`, you can inject restart files that aren't in the manifest:

```python
from ambermeta import auto_discover

protocol = auto_discover(
    "/path/to/files",
    manifest=manifest_data,
    restart_files={
        "prod1": "/path/to/equil.rst7",       # By stage name
        "production": "/path/to/default.rst7", # By stage role
    }
)
```

### Automatic Restart Detection

Enable automatic restart chain detection:

```python
from ambermeta import auto_discover

protocol = auto_discover(
    "/path/to/files",
    manifest=manifest_data,
    auto_detect_restarts=True,
)
```

Or via CLI:
```bash
ambermeta plan --manifest protocol.yaml --auto-detect-restarts
```

### Smart Pattern-Based Filtering

Filter discovered files by regex pattern:

```python
protocol = auto_discover(
    "/path/to/files",
    pattern_filter=r"prod_\d+",  # Only production runs
)
```

Or via CLI:
```bash
ambermeta plan --pattern "prod_\d+" /path/to/files
```

### Builder Pattern with Per-Stage Tolerances

```python
from ambermeta import ProtocolBuilder

protocol = (
    ProtocolBuilder()
    .from_manifest("protocol.yaml")
    .with_stage_tolerance("prod1", expected_gap_ps=0.0, tolerance_ps=0.1)
    .with_stage_tolerance("prod2", expected_gap_ps=2.0, tolerance_ps=0.5)
    .auto_detect_restarts()
    .build()
)
```

---

## Creating Manifests with the TUI

The easiest way to create a manifest is using the Terminal User Interface:

```bash
ambermeta tui /path/to/simulations
```

The TUI provides:
- Visual file browser with color-coded file types
- Automatic file grouping and sequence detection
- Stage creation with role inference
- Export to YAML, JSON, TOML, or CSV

See [TUI Guide](tui.md) for detailed documentation.

---

## Validation Notes

### Stage Role Inference
If `stage_role` is omitted, AmberMeta attempts to infer it from:
1. The `mdin` file's parsed content (ensemble, temperature settings, etc.)
2. The `mdout` file's parsed content
3. The stage name (e.g., "min" -> minimization, "prod" -> production)

An INFO note is added when inference occurs.

### Gap Validation
When `expected_gap_ps` is specified:
- AmberMeta compares observed vs expected gap
- Within tolerance: INFO note confirming gap is as expected
- Outside tolerance: WARNING note indicating deviation

When no gap expectation is provided:
- Very small gaps (< numerical tolerance) are normalized to 0
- Non-zero gaps generate a note to verify continuity

### Missing Files
- Stages can be defined even if some files are missing
- Validation notes will indicate which checks couldn't be performed
- Cross-stage continuity requires `mdcrd` from previous stage and `inpcrd` from current stage

---

## Migration Guide

### From YAML to TOML
```yaml
# YAML
- name: prod
  stage_role: production
  prmtop: system.prmtop
```

```toml
# TOML
[[stages]]
name = "prod"
stage_role = "production"
prmtop = "system.prmtop"
```

### From YAML to CSV
```yaml
# YAML
- name: prod
  stage_role: production
  prmtop: system.prmtop
  mdin: prod.in
  mdout: prod.out
  notes: Main production run
```

```csv
# CSV
name,stage_role,prmtop,mdin,mdout,mdcrd,inpcrd,notes
prod,production,system.prmtop,prod.in,prod.out,,,Main production run
```

---

## Error Handling

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `FileNotFoundError` | Manifest file doesn't exist | Check path to manifest |
| `FileNotFoundError` (validation) | Referenced file doesn't exist | Check file paths in manifest |
| `ImportError` (YAML) | PyYAML not installed | `pip install pyyaml` |
| `ImportError` (TOML) | tomllib/tomli not installed | `pip install tomli` (Python < 3.11) |
| `TypeError` | Invalid manifest structure | Must be list or dict of stages |
| `ValueError` | Missing required `name` field | Add `name` to each stage |

### Validation Warnings

AmberMeta generates warnings (not errors) for:
- Missing files that prevent validation
- Inconsistent atom counts across files
- Timing mismatches between files
- Unexpected gaps between stages
- Box dimension inconsistencies
