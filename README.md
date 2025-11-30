# ambermeta

AmberMeta: A Simulation Provenance Engine

## Library overview

AmberMeta provides lightweight Python classes for extracting provenance from AMBER
molecular dynamics runs. The package is organized around three main parts:

- **Shared utilities** (`ambermeta/utils.py`): helpers for format detection,
  value cleaning, statistics, volume calculation, and optional NetCDF backend
  detection shared across all parsers.
- **Parser classes** (`ambermeta/parsers/`): file-specific parsers that return
  structured `*Data` objects (for `prmtop`, `inpcrd`, `mdin`, `mdout`, and
  `mdcrd`) and are re-exported via `ambermeta.parsers` for convenient import.
- **Protocol model** (`ambermeta/protocol.py`): domain objects describing a
  `SimulationStage`, collections of stages in a `SimulationProtocol`, and the
  `auto_discover` helper that assembles stages from files on disk.

## Installation and imports

This repository is a standard Python package. From the repository root you can
install it in editable mode for local development:

```bash
python -m pip install -e .
```

The package offers two optional extras:

- NetCDF readers for trajectory/coordinate parsing: `python -m pip install -e ".[netcdf]"`
- Test tooling: `python -m pip install -e ".[tests]"`

After installation, the core types are available directly from the top-level
package, and individual parsers can be imported from `ambermeta.parsers`:

```python
from ambermeta import SimulationProtocol, SimulationStage, auto_discover
from ambermeta.parsers import PrmtopParser, MdoutParser
```

## Quickstart example

The snippet below discovers AMBER artifacts in a directory, constructs a
protocol, validates consistency, and prints a concise summary. Replace
`"/path/to/amber_runs"` with a directory containing matching AMBER output files
(e.g., `stage1.mdin`, `stage1.mdout`, `stage1.prmtop`, etc.).

```python
from pprint import pprint

from ambermeta import auto_discover

# Build the protocol from all recognizable files in the directory.
protocol = auto_discover("/path/to/amber_runs")

# Run additional validation (auto_discover already triggers per-stage checks).
protocol.validate()

print("Totals (steps, time_ps):")
pprint(protocol.totals())

print("\nStage summaries:")
for stage in protocol.stages:
    summary = stage.summary()
    print(f"- {stage.name}: intent={summary['intent']} result={summary['result']}")
    if summary["evidence"]:
        print(f"  evidence: {summary['evidence']}")
```

The `SimulationStage` objects keep the parsed data for each file type and expose
validation notes that highlight mismatches in atom counts, box information,
simulation timing, and sampling frequency. The `SimulationProtocol` aggregates
those stages, performs continuity checks across them, and returns total steps and
simulation time for rapid reporting.

## Command-line planning

After installing the package you will also have an `ambermeta` console script.
The `plan` command builds a `SimulationProtocol` from a manifest or launches an
interactive prompt to collect stage roles, ordering, and known gaps:

```bash
# Build from a YAML/JSON manifest (see templates below)
ambermeta plan --manifest ./protocol.yaml

# Prompt for stage names, roles, file paths, and gaps, then summarize
ambermeta plan /path/to/amber_runs
```

The output lists total steps/time plus each stage's intent, result, restart
source (if any), and validation notes. Use `--skip-cross-stage-validation` to
omit continuity checks when the stages are known to be non-contiguous.

### Manifest templates

Manifests can be YAML (requires `pyyaml`) or JSON and may be either a list of
stage objects or a mapping of stage names. Relative paths are resolved against
the manifest file's directory by default.

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
    "inpcrd": "ntp_prod_0000.rst",
    "mdin": "ntp_prod_0001.in",
    "mdout": "ntp_prod_0001.out"
  }
]
```

You can also load a manifest directly from Python using
`load_protocol_from_manifest`:

```python
from ambermeta import load_protocol_from_manifest

protocol = load_protocol_from_manifest("protocol.yaml")
```

## Testing and sample data

Run the automated test suite with:

```bash
pytest
```

Sample AMBER inputs and outputs live under `tests/data/amber/md_test_files`. The
fixtures include the original `CH3L1_HUMAN_6NAG` coordinate and parameter pair
alongside production restarts, control files, and logs (no trajectories are
provided). `ntp_prod_0000.rst` represents the starting restart for the
production stages. You can point `auto_discover` at the bundled fixtures to
experiment locally:

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
