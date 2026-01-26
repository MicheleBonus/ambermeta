# ambermeta

AmberMeta is a simulation provenance engine for AMBER molecular dynamics runs. It parses common AMBER outputs, stitches them together into ordered simulation protocols, and highlights gaps or inconsistencies so you can report progress with confidence.

## What you get
- Structured parsers for AMBER artifacts (`prmtop`, `mdin`, `mdout`, `inpcrd`, `mdcrd`) with optional NetCDF trajectory support.
- `SimulationStage` and `SimulationProtocol` models that aggregate parsed files, flag validation issues, and compute total steps and simulated time.
- Manifest-driven planning plus an interactive `ambermeta plan` CLI for quickly describing stage intent, restarts, expected gaps, and known discontinuities.
- Utilities for file format detection, cleaning values, and computing statistics shared across all parsers.

## Installation
AmberMeta targets Python 3.8+. From the repository root install in editable mode for local development:

```bash
python -m pip install -e .
```

Optional extras:
- NetCDF trajectory reading: `python -m pip install -e ".[netcdf]"`
- Test tooling: `python -m pip install -e ".[tests]"`

After installation the core models are available from the top-level package, while individual parsers live under `ambermeta.parsers`:

```python
from ambermeta import SimulationProtocol, SimulationStage, auto_discover
from ambermeta.parsers import MdoutParser, PrmtopParser
```

## Use from Python
1. **Discover files and build a protocol**
   ```python
   from ambermeta import auto_discover

   protocol = auto_discover("/path/to/amber_runs")
   ```
   Pass `grouping_rules`, `restart_files`, or a `manifest` to control how files map to stages. Use
   `recursive=True` to scan nested stage folders while preserving relative paths in stage names.
   ```python
   protocol = auto_discover("/path/to/amber_runs", recursive=True)
   ```

2. **Validate and summarize**
   ```python
   protocol.validate()  # already run during auto_discover, safe to call again
   totals = protocol.totals()  # {"steps": ..., "time_ps": ...}
   ```

3. **Inspect individual stages**
   ```python
   for stage in protocol.stages:
       summary = stage.summary()
       print(stage.name, summary["intent"], summary["result"], summary.get("evidence"))
       for note in stage.validation:
           print("note:", note)
   ```

## Use the command line
Installing the package also provides an `ambermeta` console script for quick planning and reporting.

```bash
# Build from a YAML/JSON manifest and summarize
ambermeta plan --manifest ./protocol.yaml /path/to/amber_runs

# Recursively discover stage files in nested directories
ambermeta plan --recursive /path/to/amber_runs

# Prompt for stage names, roles, file paths, restarts, and expected gap/tolerance values, then summarize
ambermeta plan /path/to/amber_runs

# Write a structured summary for downstream tools
ambermeta plan --manifest ./protocol.yaml --summary-path ./protocol.json
```

Flags worth knowing:
- `--skip-cross-stage-validation` disables continuity checks when stages are intentionally non-contiguous.
- `-v/--verbose` prints parsed metadata, warnings, and continuity notes.
- `--summary-format {json|yaml}` forces the written summary format (defaults to file extension).
- `--recursive` scans subdirectories and uses relative paths for stage naming.

## Methods summaries (`--methods-summary-path`)
Use `--methods-summary-path` to write a compact, JSON methods summary intended for reporting or manuscript supplements. The output matches the CLI help text by omitting nonessential arrays and energy series, and it is always JSON regardless of file extension. For example:

```bash
ambermeta plan --methods-summary-path methods.json /path/to/amber_runs
```

The output mirrors `SimulationProtocol.to_methods_dict()` and includes these top-level keys:
- `stage_sequence`: ordered stage names.
- `stages`: per-stage metadata with `software`, `md_engine`, `system`, and `trajectory_output` entries.

## Manifests at a glance
Manifests describe ordered simulation stages for both `auto_discover` and `ambermeta plan`. YAML (requires the optional `pyyaml` extra) and JSON are supported.

- **Required:** `name` and `stage_role` (intent). Roles can sometimes be inferred from `mdin` metadata but are best provided explicitly.
- **Files:** `prmtop`, `mdin`, `mdout`, `inpcrd`, `mdcrd` either directly in each stage or nested under `files`. Relative paths resolve against the manifest location or the directory passed to `auto_discover`.
- **Optional:** `notes` (string or list), `gaps`/`gap` to declare expected discontinuities, and `inpcrd`/`restart_files` to capture restart sources.

See [docs/manifest.md](docs/manifest.md) for the full schema and edge cases. Templates:

```yaml
# protocol.yaml
- name: equil
  stage_role: equilibration
  files:
    prmtop: CH3L1_HUMAN_6NAG_3xenergy.prmtop
    mdin: CH3L1_HUMAN_6NAG_3xenergy.mdin
    mdout: CH3L1_HUMAN_6NAG_3xenergy.mdout
  notes:
    - Coordinate file missing; using restart from production
- name: prod1
  stage_role: production
  files:
    mdin: ntp_prod_0001.in
    mdout: ntp_prod_0001.out
    inpcrd: ntp_prod_0000.rst
```

```json
// protocol.json
[
  {
    "name": "equil",
    "stage_role": "equilibration",
    "files": {
      "prmtop": "CH3L1_HUMAN_6NAG_3xenergy.prmtop",
      "mdin": "CH3L1_HUMAN_6NAG_3xenergy.mdin",
      "mdout": "CH3L1_HUMAN_6NAG_3xenergy.mdout"
    }
  },
  {
    "name": "prod1",
    "stage_role": "production",
    "files": {
      "mdin": "ntp_prod_0001.in",
      "mdout": "ntp_prod_0001.out",
      "inpcrd": "ntp_prod_0000.rst"
    }
  }
]
```

You can also load a manifest directly from Python:

```python
from ambermeta import load_protocol_from_manifest

protocol = load_protocol_from_manifest("protocol.yaml")
```

## Sample data and tests
Sample AMBER inputs and outputs live under `tests/data/amber/md_test_files`. The fixtures include the original `CH3L1_HUMAN_6NAG` coordinate and parameter pair alongside production restarts, control files, and logs (no trajectories). Try them out with:

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
