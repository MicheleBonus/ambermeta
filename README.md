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
