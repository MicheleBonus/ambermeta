# Tutorials

Task-oriented walkthroughs for getting real work done with AmberMeta. Each uses the sample data in `tests/data/amber/md_test_files/` — a 64,528-atom glycoprotein system with a six-member NPT production sequence — so every command and output below is reproducible.

## Contents

1. [Inspect individual files](#1-inspect-individual-files)
2. [Build a protocol](#2-build-a-protocol)
3. [Build a manifest interactively (GUI)](#3-build-a-manifest-interactively-gui)
4. [Write manifests for reproducibility](#4-write-manifests-for-reproducibility)
5. [Validate continuity](#5-validate-continuity)
6. [Export for publications](#6-export-for-publications)
7. [Work with production sequences](#7-work-with-production-sequences)
8. [Automate metadata collection](#8-automate-metadata-collection)

> **Prerequisite.** `pip install -e ".[all]"` (the NetCDF extra is needed to parse the `.nc`/`.ncrst` files some projects use; the sample restarts are NetCDF).

> ⚠️ **Python usage — read this first.** A parser's `parse()` returns a wrapper; the metadata is on `.details`. Every Python example below uses `Parser(path).parse().details`. See [API reference](api.md#6-parser-metadata-fields) for the full field list.

---

## 1. Inspect individual files

**Goal:** pull the metadata out of each AMBER file type.

### Topology (`prmtop`)

```bash
ambermeta info tests/data/amber/md_test_files/CH3L1_HUMAN_6NAG.top
```

```python
from ambermeta.parsers import PrmtopParser

meta = PrmtopParser("tests/data/amber/md_test_files/CH3L1_HUMAN_6NAG.top").parse().details
print(meta.natom, meta.nres)                 # 64528 15102
print(meta.solvent_type, meta.density)       # Explicit Solvent 0.8434
print(meta.residue_composition["WAT"])       # 14659
print(meta.hmr_active, meta.hmr_detection_method)   # False atomic_number
```

You get atom/residue counts, box geometry, density, solvent model, system composition (`residue_composition`, including ions and water), and HMR status (`hmr_active` + how it was detected).

### Input (`mdin`)

```python
from ambermeta.parsers import MdinParser

meta = MdinParser("tests/data/amber/md_test_files/ntp_prod_0001.mdin").parse().details
print(meta.length_steps, meta.dt)            # 5000000 0.004
print(meta.ensemble, meta.stage_role)        # NPT (isotropic)  Production [NPT (isotropic)]
print(meta.temp_control, meta.target_temp)   # Langevin Dynamics 300.0
print(meta.press_control, meta.constraints)  # Berendsen (Isotropic)  H-bonds
print(meta.cntrl_parameters["nstlim"])       # 5000000
```

Run length, timestep, ensemble, temperature/pressure control, constraints, and the raw `&cntrl` namelist in `cntrl_parameters` — plus a heuristic `stage_role`.

### Output (`mdout`)

```python
from ambermeta.parsers import MdoutParser

meta = MdoutParser("tests/data/amber/md_test_files/ntp_prod_0001.mdout").parse().details
print(meta.program, meta.version)            # PMEMD 22
print(meta.finished_properly)                # True
print(meta.thermostat, meta.barostat)        # Langevin Berendsen
s = meta.stats
print(s.count, s.time_start, s.time_end)     # 200 1020.0 20920.0
print(s.temp_stats.mean, s.temp_stats.stdev) # 300.43200000000013 1.2504190252445306
print(s.density_stats.mean)                  # 1.0369550000000003
```

Completion status, engine settings, performance (`wall_time_seconds`, `ns_per_day`), and streaming thermodynamics. Per-quantity stats live on `stats.<q>_stats` (`temp_stats`, `pressure_stats`, `density_stats`, `etot_stats`, `volume_stats`), each exposing `.mean` and `.stdev`.

### Restart (`inpcrd`)

```python
from ambermeta.parsers import InpcrdParser

meta = InpcrdParser("tests/data/amber/md_test_files/ntp_prod_0001.rst").parse().details
print(meta.natoms, meta.time)                # 64528 20920.00000242704
print(meta.has_velocities, meta.has_box)     # True True
```

Atom count and `time` are what continuity checking uses to chain stages.

---

## 2. Build a protocol

**Goal:** assemble loose files into an ordered `SimulationProtocol`.

### From a directory

```python
from ambermeta import auto_discover

protocol = auto_discover("tests/data/amber/md_test_files", recursive=True)
print(len(protocol.stages))                  # 7
for stage in protocol.stages:
    print(stage.name, "->", stage.summary()["intent"])
```

### From a manifest

```python
from ambermeta import load_protocol_from_manifest

protocol = load_protocol_from_manifest("protocol.yaml", directory="runs/")
```

### With the builder (full control)

```python
from ambermeta import ProtocolBuilder

protocol = (
    ProtocolBuilder()
    .from_directory("tests/data/amber/md_test_files", recursive=True)
    .with_grouping_rules({r"ntp_prod.*": "production"})
    .with_pattern_filter(r"ntp_prod_\d+")
    .auto_detect_restarts()
    .build()
)
print(protocol.totals())   # {'steps': 25000000.0, 'time_ps': 100000.0}
```

`ProtocolBuilder` chains the same primitives `auto_discover` uses; see [API §1](api.md#1-discovery--assembly).

---

## 3. Build a manifest interactively (GUI)

**Goal:** assemble a manifest in the browser.

```bash
ambermeta gui tests/data/amber/md_test_files
```

This starts a localhost server and opens a three-pane window — **Files** · **Stages** · **Properties**.

1. **Discover** auto-groups the directory into stages (one per file group), detects the numbered sequence, and classifies the topology.
2. Drag a file from **Files** onto a stage slot, or use the picker in **Properties**.
3. Select a stage to edit its name, role, gap/tolerance, and notes.
4. **Validate** reports issues with jump-to-issue; **Save** writes the canonical manifest — byte-identical to the CLI's.

Full walkthrough: [GUI guide](gui.md). Prefer the terminal? `ambermeta plan … --interactive` and `ambermeta init … --auto` cover the same ground headlessly.

---

## 4. Write manifests for reproducibility

**Goal:** capture a protocol as a durable, reviewable file.

Bootstrap one from a directory, then edit:

```bash
ambermeta init runs/ --auto --output manifest.yaml --validate --force
```

Or write it by hand:

```yaml
# protocol.yaml
global_prmtop: systems/complex.prmtop
stages:
  - name: minimize
    stage_role: minimization
    mdin: inputs/min.in
    mdout: outputs/min.out
    notes: ["Steepest descent, 5000 steps"]

  - name: equilibrate
    stage_role: equilibration
    mdin: inputs/equil.in
    mdout: outputs/equil.out
    mdcrd: traj/equil.nc
    inpcrd: restarts/heat.rst7
    gaps: { expected: 0.0, tolerance: 0.1 }

  - name: production
    stage_role: production
    mdin: inputs/prod.in
    mdout: outputs/prod.out
    mdcrd: traj/prod.nc
    inpcrd: restarts/equil.rst7
```

Make it portable with environment variables, then load it:

```yaml
- name: production
  prmtop: ${PROJECT_ROOT}/systems/complex.prmtop
  mdout: ${OUTPUT_DIR}/prod.out
```

```bash
export PROJECT_ROOT=/home/user/sim OUTPUT_DIR=/scratch/out
ambermeta plan ./runs --manifest protocol.yaml -v
```

Full schema: [manifest reference](manifest.md).

---

## 5. Validate continuity

**Goal:** confirm stages actually connect.

```python
from ambermeta import auto_discover

protocol = auto_discover("runs/", recursive=True, auto_detect_restarts=True)
for stage in protocol.stages:
    for note in stage.validation + stage.continuity:
        print(f"{stage.name}: {note}")
```

Notes are tagged `INFO` (role inferred, gap confirmed, check skipped for missing data) or `WARNING` (atom-count mismatch, timing inconsistency, box change, unexpected gap).

Configure expected gaps where a discontinuity is intentional:

```yaml
- name: prod_002
  stage_role: production
  mdin: prod_002.in
  mdout: prod_002.out
  inpcrd: prod_001.rst7
  gaps:
    expected: 2.0      # expected 2 ps jump (e.g. restart from a checkpoint)
    tolerance: 0.5
    notes: ["Gap due to job failure and restart"]
```

For non-contiguous protocols (independent replicas), skip the cross-stage checks:

```bash
ambermeta plan --manifest protocol.yaml --skip-cross-stage-validation
```

---

## 6. Export for publications

**Goal:** produce methods-section-ready artifacts.

```bash
ambermeta plan --manifest protocol.yaml \
  --methods-summary-path methods.json \
  --stats-csv stats.csv \
  --summary-path protocol.json
```

```python
import json
from ambermeta import auto_discover

protocol = auto_discover("runs/", recursive=True)
json.dump(protocol.to_methods_dict(), open("methods.json", "w"), indent=2)
```

The methods summary is `{stage_sequence, stages[]}`, where each stage carries `software`, `md_engine` (ensemble / thermostat / barostat / cutoff / constraints / timestep / run length), `restraints`, and `system` (atom counts, box, composition) — energies and bulk arrays are dropped. The exact shape is in [API §7](api.md#7-export-structures). The stats CSV has one row per stage with temperature/pressure/density/energy as mean ± σ.

---

## 7. Work with production sequences

**Goal:** handle numbered runs (`ntp_prod_0001`, `…0002`, …).

```python
from ambermeta import detect_numeric_sequences, smart_group_files

detect_numeric_sequences(["ntp_prod_0001.mdout", "ntp_prod_0002.mdout", "equil.mdout"])
# {'ntp_prod_': ['ntp_prod_0001.mdout', 'ntp_prod_0002.mdout']}

groups = smart_group_files("tests/data/amber/md_test_files", pattern=r"ntp_prod_\d+", recursive=True)
for stem, files in groups.items():
    print(stem, {k: v for k, v in files.items() if not k.startswith("_")})
```

Each numbered run becomes its own stage (sequences are **not** collapsed), ordered by index, each carrying a "item *n* of *m*" note. In the GUI, the sequence collapses into one expandable group whose role you can set in one action.

```python
from ambermeta import ProtocolBuilder

protocol = (
    ProtocolBuilder()
    .from_directory("tests/data/amber/md_test_files", recursive=True)
    .with_pattern_filter(r"ntp_prod_\d+")
    .with_grouping_rules({r"ntp_prod.*": "production"})
    .auto_detect_restarts()      # chains 0002←0001, 0003←0002, ...
    .build()
)
```

---

## 8. Automate metadata collection

**Goal:** process many simulation directories unattended.

```python
#!/usr/bin/env python3
"""Summarize every simulation directory under a root."""
import json
from pathlib import Path
from ambermeta import auto_discover, AmberMetaError

def process(sim_dir: Path, out_dir: Path) -> bool:
    try:
        protocol = auto_discover(str(sim_dir), recursive=True, auto_detect_restarts=True)
    except AmberMetaError as e:
        print(f"{sim_dir.name}: {e}")
        return False
    (out_dir / f"{sim_dir.name}_protocol.json").write_text(
        json.dumps(protocol.to_dict(), indent=2))
    (out_dir / f"{sim_dir.name}_methods.json").write_text(
        json.dumps(protocol.to_methods_dict(), indent=2))
    return True

def main():
    root, out = Path("/path/to/simulations"), Path("/path/to/output")
    out.mkdir(exist_ok=True)
    ok = sum(process(d, out) for d in root.iterdir() if d.is_dir())
    print(f"Processed {ok} directories")

if __name__ == "__main__":
    main()
```

`auto_discover` is fault-tolerant by default — a bad file in one directory is recorded as a `FileLoadError` on its stage rather than aborting the batch. To audit completion across runs, read `stage.mdout.details.finished_properly` (see [API §9](api.md#9-worked-examples)).

---

## See also

- [Recipes](recipes.md) — short copy-paste one-liners
- [CLI reference](cli.md) · [Python API](api.md) · [Manifest schema](manifest.md) · [GUI guide](gui.md)
