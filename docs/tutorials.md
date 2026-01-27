# AmberMeta Tutorials

This guide provides step-by-step tutorials for using AmberMeta to extract (meta)-data from AMBER molecular dynamics simulation files.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Tutorial 1: Extracting Metadata from Individual Files](#tutorial-1-extracting-metadata-from-individual-files)
3. [Tutorial 2: Building a Protocol from Scratch](#tutorial-2-building-a-protocol-from-scratch)
4. [Tutorial 3: Using the Terminal UI](#tutorial-3-using-the-terminal-ui)
5. [Tutorial 4: Creating Manifests for Reproducibility](#tutorial-4-creating-manifests-for-reproducibility)
6. [Tutorial 5: Validating Simulation Continuity](#tutorial-5-validating-simulation-continuity)
7. [Tutorial 6: Exporting Data for Publications](#tutorial-6-exporting-data-for-publications)
8. [Tutorial 7: Working with Production Run Sequences](#tutorial-7-working-with-production-run-sequences)
9. [Tutorial 8: Automating Metadata Collection](#tutorial-8-automating-metadata-collection)

---

## Getting Started

### Prerequisites

Install AmberMeta with all optional dependencies:

```bash
# Basic installation
pip install -e .

# With all extras (recommended for tutorials)
pip install -e ".[all]"
```

### Sample Data

The tutorials use sample data in `tests/data/amber/md_test_files/`. This includes:
- Topology files (`.top`)
- Input files (`.mdin`)
- Output logs (`.mdout`)
- Restart files (`.rst`)
- Trajectory files (`.crd`)

---

## Tutorial 1: Extracting Metadata from Individual Files

**Goal:** Learn how to extract specific metadata from each AMBER file type.

### Step 1: Inspect a Topology File

Topology files contain the molecular system definition.

**Command Line:**
```bash
ambermeta info tests/data/amber/md_test_files/CH3L1.top
```

**Python:**
```python
from ambermeta.parsers import PrmtopParser

# Parse the topology file
parser = PrmtopParser("tests/data/amber/md_test_files/CH3L1.top")
meta = parser.parse()

# System composition
print("=== System Composition ===")
print(f"Total atoms: {meta.natom}")
print(f"Total residues: {meta.nres}")
print(f"Residue breakdown: {meta.residue_counts}")

# Box information
print("\n=== Box Information ===")
print(f"Box dimensions: {meta.box_dimensions}")
print(f"Box angles: {meta.box_angles}")

# Solvent and ions
print("\n=== Solvent Analysis ===")
print(f"Solvent type: {meta.solvent_type}")
print(f"Ion counts: {meta.ions}")

# Physical properties
print("\n=== Physical Properties ===")
print(f"Density: {meta.density:.4f} g/cc" if meta.density else "Density: N/A")
print(f"Total charge: {meta.total_charge}")
print(f"HMR detected: {meta.is_hmr}")
```

**Key metadata extracted:**
- Atom and residue counts
- Box dimensions and type
- Solvent model (TIP3P, TIP4P, etc.)
- Ion composition
- Hydrogen mass repartitioning status
- System density

### Step 2: Inspect an Input Control File

Input files define simulation parameters and settings.

**Command Line:**
```bash
ambermeta info tests/data/amber/md_test_files/ntp_prod_0000.mdin
```

**Python:**
```python
from ambermeta.parsers import MdinParser

parser = MdinParser("tests/data/amber/md_test_files/ntp_prod_0000.mdin")
meta = parser.parse()

# Run parameters
print("=== Run Parameters ===")
print(f"Total steps: {meta.length_steps}")
print(f"Timestep: {meta.dt} ps")
print(f"Total time: {meta.length_steps * meta.dt if meta.dt else 'N/A'} ps")

# Temperature control
print("\n=== Temperature Control ===")
print(f"Method: {meta.temperature_control}")
print(f"Target temperature: {meta.target_temp} K" if meta.target_temp else "")

# Pressure control
print("\n=== Pressure Control ===")
print(f"Method: {meta.pressure_control}")

# Constraints and restraints
print("\n=== Constraints ===")
print(f"Constraint method: {meta.constraints}")

# Automatic role inference
print("\n=== Inferred Stage Role ===")
print(f"Stage type: {meta.inferred_stage_role}")
```

**Key metadata extracted:**
- Simulation length (steps and time)
- Temperature control (Langevin, Berendsen, etc.)
- Pressure control settings
- Constraint algorithms (SHAKE)
- Restraint masks and force constants
- Automatic stage role inference

### Step 3: Inspect an Output Log File

Output files contain simulation results and statistics.

**Command Line:**
```bash
ambermeta info tests/data/amber/md_test_files/ntp_prod_0000.mdout
```

**Python:**
```python
from ambermeta.parsers import MdoutParser

parser = MdoutParser("tests/data/amber/md_test_files/ntp_prod_0000.mdout")
meta = parser.parse()

# Completion status
print("=== Simulation Status ===")
print(f"Finished properly: {meta.finished_properly}")

# Settings from output
print("\n=== Simulation Settings ===")
print(f"Steps: {meta.nstlim}")
print(f"Timestep: {meta.dt} ps")
print(f"Thermostat: {meta.thermostat}")
print(f"Barostat: {meta.barostat}")
print(f"Box type: {meta.box_type}")

# Thermodynamic statistics
print("\n=== Thermodynamic Statistics ===")
if meta.stats:
    print(f"Data points: {meta.stats.count}")
    print(f"Time range: {meta.stats.time_start} - {meta.stats.time_end} ps")
    print(f"Temperature: {meta.stats.temp_mean:.2f} ± {meta.stats.temp_std:.2f} K")
    print(f"Pressure: {meta.stats.press_mean:.2f} ± {meta.stats.press_std:.2f} bar")
    print(f"Density: {meta.stats.density_mean:.4f} ± {meta.stats.density_std:.4f} g/cc")
```

**Key metadata extracted:**
- Completion status
- Thermostat and barostat settings
- PME parameters
- Running statistics (temperature, pressure, density, energy)
- Timing information

### Step 4: Inspect a Restart File

Restart files link simulation stages together.

**Command Line:**
```bash
ambermeta info tests/data/amber/md_test_files/ntp_prod_0000.rst
```

**Python:**
```python
from ambermeta.parsers import InpcrdParser

parser = InpcrdParser("tests/data/amber/md_test_files/ntp_prod_0000.rst")
meta = parser.parse()

print("=== Restart File Information ===")
print(f"Atom count: {meta.natoms}")
print(f"Has velocities: {meta.has_velocities}")
print(f"Has box: {meta.has_box}")
print(f"Simulation time: {meta.time} ps" if meta.time else "Time: N/A")
print(f"Box dimensions: {meta.box_dimensions}")
```

**Key metadata extracted:**
- Atom count (for validation)
- Velocity presence
- Box dimensions
- Simulation time (for continuity checking)

---

## Tutorial 2: Building a Protocol from Scratch

**Goal:** Learn how to assemble multiple simulation files into a coherent protocol.

### Step 1: Auto-Discover Files in a Directory

```python
from ambermeta import auto_discover

# Simple discovery
protocol = auto_discover("tests/data/amber/md_test_files")

print(f"Discovered {len(protocol.stages)} stages:")
for stage in protocol.stages:
    print(f"  - {stage.name}")
```

### Step 2: Configure Discovery with Grouping Rules

```python
from ambermeta import auto_discover

protocol = auto_discover(
    "tests/data/amber/md_test_files",
    recursive=True,
    grouping_rules={
        "ntp_prod": "production",
        "equil": "equilibration",
        "heat": "heating",
        "min": "minimization",
    },
)

for stage in protocol.stages:
    summary = stage.summary()
    print(f"\n{stage.name}:")
    print(f"  Role: {summary['intent']}")
    print(f"  Result: {summary['result']}")
```

### Step 3: Use the Builder API for Full Control

```python
from ambermeta import ProtocolBuilder

protocol = (
    ProtocolBuilder()
    .from_directory("tests/data/amber/md_test_files", recursive=True)
    .with_grouping_rules({
        r"ntp_prod.*": "production",
        r"CH3L1.*": "equilibration",
    })
    .with_pattern_filter(r"ntp_prod_\d+")  # Only production runs
    .auto_detect_restarts()
    .build()
)

# Examine the protocol
print(f"Protocol contains {len(protocol.stages)} stages")
totals = protocol.totals()
print(f"Total simulation time: {totals['time_ps']:.2f} ps")
print(f"Total steps: {totals['steps']:.0f}")
```

### Step 4: Manually Build a Protocol

```python
from ambermeta import ProtocolBuilder

protocol = (
    ProtocolBuilder()
    .from_directory("tests/data/amber/md_test_files")
    .add_stage(
        name="equilibration",
        stage_role="equilibration",
        prmtop="CH3L1.top",
        mdin="CH3L1.mdin",
        mdout="CH3L1.mdout",
    )
    .add_stage(
        name="production_001",
        stage_role="production",
        prmtop="CH3L1.top",
        mdin="ntp_prod_0000.mdin",
        mdout="ntp_prod_0000.mdout",
        mdcrd="ntp_prod_0000.crd",
        inpcrd="ntp_prod_0000.rst",
        expected_gap_ps=0.0,
    )
    .build()
)
```

---

## Tutorial 3: Using the Terminal UI

**Goal:** Learn how to use the interactive TUI for building protocol manifests.

### Step 1: Launch the TUI

```bash
# Launch in a simulation directory
ambermeta tui tests/data/amber/md_test_files

# With recursive file discovery
ambermeta tui --recursive tests/data/amber/md_test_files
```

### Step 2: Navigate the File Browser

The left panel shows a directory tree of simulation files:

1. **Expand directories** by clicking or pressing Enter
2. **File icons indicate type:**
   - `[P]` Green = prmtop (topology)
   - `[I]` Yellow = mdin (input)
   - `[O]` Cyan = mdout (output)
   - `[T]` Magenta = mdcrd (trajectory)
   - `[R]` Blue = inpcrd/restart

### Step 3: Set Global Topology

1. Click on a `.prmtop` file
2. A modal appears with options:
   - "Set as Global Prmtop" - applies to all stages
   - "Set as HMR Prmtop" - for hydrogen mass repartitioning systems
   - "Add to Stage Editor" - add to current stage being edited

Or use `Ctrl+G` to open Global Settings.

### Step 4: Create Stages

**Manual creation:**
1. Navigate to files in the file browser
2. Click files to add them to the stage editor
3. Set stage name and role
4. Click "Apply" to create the stage

**Auto-generate from folder:**
1. Click on a directory in the file browser, or
2. Press `Ctrl+A` to open Auto-Generate modal
3. Select target folder
4. Stages are created based on file groupings

### Step 5: Edit Stage Properties

Select a stage in the center panel to edit:
- **Name:** Unique identifier
- **Role:** minimization, heating, equilibration, production
- **Files:** prmtop, mdin, mdout, mdcrd, inpcrd paths
- **Expected Gap:** Expected time gap from previous stage (ps)
- **Tolerance:** Acceptable deviation from expected gap (ps)
- **Notes:** Documentation for the stage

### Step 6: Export the Manifest

1. Press `Ctrl+E` to open Export modal
2. Choose format: YAML, JSON, TOML, or CSV
3. Select path options (absolute vs relative)
4. Click Export

---

## Tutorial 4: Creating Manifests for Reproducibility

**Goal:** Learn how to create and use manifest files for reproducible protocols.

### Step 1: Generate a Template

```bash
# Generate standard template
ambermeta init my_project

# Generate comprehensive template with all options
ambermeta init --template comprehensive my_project

# Custom output filename
ambermeta init -o my_protocol.yaml my_project
```

### Step 2: Edit the Manifest

Create `protocol.yaml`:

```yaml
# Simulation Protocol Manifest
# Project: My MD Simulation

# Stage 1: Energy Minimization
- name: minimize
  stage_role: minimization
  prmtop: systems/complex.prmtop
  mdin: inputs/min.in
  mdout: outputs/min.out
  notes:
    - "Steepest descent for 5000 steps"
    - "Hydrogen-only constraints"

# Stage 2: Heating
- name: heat
  stage_role: heating
  prmtop: systems/complex.prmtop
  mdin: inputs/heat.in
  mdout: outputs/heat.out
  inpcrd: restarts/min.rst7
  gaps:
    expected: 0.0
    tolerance: 0.1
  notes:
    - "Heat from 0K to 300K over 100ps"
    - "NVT ensemble with position restraints"

# Stage 3: Equilibration
- name: equilibrate
  stage_role: equilibration
  prmtop: systems/complex.prmtop
  mdin: inputs/equil.in
  mdout: outputs/equil.out
  mdcrd: trajectories/equil.nc
  inpcrd: restarts/heat.rst7
  notes:
    - "NPT equilibration at 300K, 1 bar"
    - "2 ns with decreasing restraints"

# Stage 4: Production
- name: production
  stage_role: production
  prmtop: systems/complex.prmtop
  mdin: inputs/prod.in
  mdout: outputs/prod.out
  mdcrd: trajectories/prod.nc
  inpcrd: restarts/equil.rst7
  gaps:
    expected: 0.0
    tolerance: 0.1
```

### Step 3: Use Environment Variables

For portable manifests across systems:

```yaml
# protocol.yaml with environment variables
- name: production
  prmtop: ${PROJECT_ROOT}/systems/complex.prmtop
  mdin: ${PROJECT_ROOT}/inputs/prod.in
  mdout: ${OUTPUT_DIR}/prod.out
  mdcrd: ${OUTPUT_DIR}/prod.nc
```

Set environment variables before running:
```bash
export PROJECT_ROOT=/home/user/simulations
export OUTPUT_DIR=/scratch/output
ambermeta plan --manifest protocol.yaml
```

### Step 4: Load and Validate

```bash
# Validate the manifest
ambermeta plan --manifest protocol.yaml -v

# Export validated protocol
ambermeta plan --manifest protocol.yaml --summary-path validated_protocol.json
```

```python
from ambermeta import load_protocol_from_manifest

protocol = load_protocol_from_manifest("protocol.yaml")

# Check for validation issues
for stage in protocol.stages:
    if stage.validation:
        print(f"\n{stage.name} validation notes:")
        for note in stage.validation:
            print(f"  - {note}")
```

---

## Tutorial 5: Validating Simulation Continuity

**Goal:** Learn how to validate that simulation stages are properly connected.

### Step 1: Enable Cross-Stage Validation

```python
from ambermeta import auto_discover

protocol = auto_discover(
    "path/to/simulations",
    recursive=True,
    auto_detect_restarts=True,  # Automatically link restart files
)

# Validation is performed automatically
for stage in protocol.stages:
    print(f"\n{stage.name}:")
    for note in stage.validation:
        print(f"  {note}")
```

### Step 2: Understand Validation Notes

AmberMeta generates several types of validation notes:

**Informational (INFO):**
- Stage role inferred from file content
- Expected gaps confirmed within tolerance
- Cross-stage checks skipped (when data unavailable)

**Warnings:**
- Atom count mismatches between files
- Timing inconsistencies
- Box dimension changes
- Unexpected gaps between stages

### Step 3: Configure Gap Tolerances

```python
from ambermeta import ProtocolBuilder

protocol = (
    ProtocolBuilder()
    .from_directory("path/to/simulations")
    .auto_detect_restarts()
    # Stage-specific tolerances
    .with_stage_tolerance("prod_001", expected_gap_ps=0.0, tolerance_ps=0.1)
    .with_stage_tolerance("prod_002", expected_gap_ps=2.0, tolerance_ps=0.5)  # Expected gap
    .build()
)
```

Or in a manifest:
```yaml
- name: prod_002
  stage_role: production
  prmtop: system.prmtop
  mdin: prod_002.in
  mdout: prod_002.out
  inpcrd: prod_001.rst7
  gaps:
    expected: 2.0  # Expected 2 ps gap (e.g., restart from backup)
    tolerance: 0.5
    notes:
      - "Gap due to job failure and restart from checkpoint"
```

### Step 4: Skip Validation When Needed

For non-contiguous protocols (e.g., independent replicas):

```bash
ambermeta plan --manifest protocol.yaml --skip-cross-stage-validation
```

```python
protocol = auto_discover(
    "path/to/simulations",
    skip_cross_stage_validation=True,
)
```

---

## Tutorial 6: Exporting Data for Publications

**Goal:** Learn how to export protocol data for methods sections and supplementary materials.

### Step 1: Export Methods-Ready Summary

```bash
# Generate publication-ready JSON
ambermeta plan --manifest protocol.yaml --methods-summary-path methods.json
```

```python
from ambermeta import auto_discover
import json

protocol = auto_discover("path/to/simulations", recursive=True)

# Get methods-ready dictionary
methods = protocol.to_methods_dict()

# Save to file
with open("methods.json", "w") as f:
    json.dump(methods, f, indent=2)
```

### Step 2: Understand the Methods Summary

The methods summary includes:

```python
{
    "stages": [
        {
            "name": "production",
            "role": "production",
            "software": "AMBER",
            "engine_settings": {
                "ensemble": "NPT",
                "thermostat": "Langevin",
                "barostat": "Monte Carlo",
                "cutoff_angstrom": 10.0,
                "constraints": "SHAKE on hydrogen"
            },
            "system": {
                "atoms": 45231,
                "residues": 12543,
                "box_type": "truncated octahedron",
                "solvent": "TIP3P"
            }
        }
    ],
    "totals": {
        "stages": 4,
        "total_time_ps": 100000.0,
        "total_steps": 50000000
    }
}
```

### Step 3: Export Statistics to CSV

```bash
# Export per-stage statistics
ambermeta plan --manifest protocol.yaml --stats-csv statistics.csv
```

The CSV includes:
- Stage name and role
- Temperature (mean ± std)
- Pressure (mean ± std)
- Density (mean ± std)
- Total energy statistics
- Completion status

### Step 4: Generate Full Protocol JSON

```python
from ambermeta import auto_discover
import json

protocol = auto_discover("path/to/simulations", recursive=True)

# Full protocol with all metadata
full_data = protocol.to_dict()

with open("protocol_full.json", "w") as f:
    json.dump(full_data, f, indent=2)
```

---

## Tutorial 7: Working with Production Run Sequences

**Goal:** Learn how to handle numbered production run sequences (prod_001, prod_002, etc.).

### Step 1: Detect Numeric Sequences

```python
from ambermeta import detect_numeric_sequences

files = [
    "prod_001.mdout",
    "prod_002.mdout",
    "prod_003.mdout",
    "equil.mdout",
]

sequences = detect_numeric_sequences(files)
print(sequences)
# Output: {'prod_': ['prod_001.mdout', 'prod_002.mdout', 'prod_003.mdout']}
```

### Step 2: Smart File Grouping

```python
from ambermeta import smart_group_files

# Group files by stem with sequence detection
grouped = smart_group_files(
    "path/to/production_runs",
    recursive=True,
    pattern=r"prod_\d+",  # Only production files
)

for stem, files in grouped.items():
    print(f"\n{stem}:")
    for file_type, path in files.items():
        if not file_type.startswith("_"):
            print(f"  {file_type}: {path}")

    # Sequence metadata
    if "_sequence_base" in files:
        print(f"  Sequence: {files['_sequence_base']} #{files['_sequence_index']}")
```

### Step 3: Build Protocol from Sequences

```python
from ambermeta import ProtocolBuilder

protocol = (
    ProtocolBuilder()
    .from_directory("path/to/production_runs", recursive=True)
    .with_pattern_filter(r"prod_\d+")
    .with_grouping_rules({r"prod.*": "production"})
    .auto_detect_restarts()  # Links prod_002 to prod_001.rst, etc.
    .build()
)

# Stages are ordered by sequence number
for stage in protocol.stages:
    print(f"{stage.name}: {stage.sequence_index}")
```

### Step 4: TUI Sequence Features

In the TUI, sequences are automatically detected and displayed:

1. The "Seq #" column shows position within a sequence
2. Use `Ctrl+A` to auto-generate stages from a folder with sequences
3. Stages in the same sequence share a common base pattern

---

## Tutorial 8: Automating Metadata Collection

**Goal:** Learn how to automate metadata collection for large-scale simulations.

### Step 1: Batch Processing Script

```python
#!/usr/bin/env python3
"""Batch process multiple simulation directories."""

import json
from pathlib import Path
from ambermeta import auto_discover

def process_simulation(sim_dir: Path, output_dir: Path):
    """Process a single simulation directory."""
    try:
        protocol = auto_discover(
            str(sim_dir),
            recursive=True,
            auto_detect_restarts=True,
        )

        # Save protocol summary
        output_file = output_dir / f"{sim_dir.name}_protocol.json"
        with open(output_file, "w") as f:
            json.dump(protocol.to_dict(), f, indent=2)

        # Save methods summary
        methods_file = output_dir / f"{sim_dir.name}_methods.json"
        with open(methods_file, "w") as f:
            json.dump(protocol.to_methods_dict(), f, indent=2)

        print(f"Processed: {sim_dir.name}")
        return True

    except Exception as e:
        print(f"Error processing {sim_dir.name}: {e}")
        return False


def main():
    base_dir = Path("/path/to/simulations")
    output_dir = Path("/path/to/output")
    output_dir.mkdir(exist_ok=True)

    # Find all simulation directories
    sim_dirs = [d for d in base_dir.iterdir() if d.is_dir()]

    results = []
    for sim_dir in sim_dirs:
        success = process_simulation(sim_dir, output_dir)
        results.append((sim_dir.name, success))

    # Summary
    print(f"\nProcessed {sum(1 for _, s in results if s)}/{len(results)} successfully")


if __name__ == "__main__":
    main()
```

### Step 2: Generate Consolidated Report

```python
#!/usr/bin/env python3
"""Generate consolidated report from multiple protocols."""

import json
import csv
from pathlib import Path
from ambermeta import load_protocol_from_manifest

def load_protocols(manifest_dir: Path):
    """Load all manifests from a directory."""
    protocols = []
    for manifest in manifest_dir.glob("*.yaml"):
        try:
            protocol = load_protocol_from_manifest(str(manifest))
            protocols.append((manifest.stem, protocol))
        except Exception as e:
            print(f"Error loading {manifest}: {e}")
    return protocols


def generate_report(protocols, output_file: Path):
    """Generate CSV report of all protocols."""
    with open(output_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "System", "Stages", "Total Time (ns)",
            "Avg Temperature (K)", "Avg Pressure (bar)",
            "Completed"
        ])

        for name, protocol in protocols:
            totals = protocol.totals()
            time_ns = totals["time_ps"] / 1000

            # Aggregate statistics from production stages
            temps, pressures = [], []
            completed = True

            for stage in protocol.stages:
                if stage.mdout and stage.mdout.details:
                    stats = getattr(stage.mdout.details, "stats", None)
                    if stats:
                        if hasattr(stats, "temp_mean"):
                            temps.append(stats.temp_mean)
                        if hasattr(stats, "press_mean"):
                            pressures.append(stats.press_mean)

                    if not getattr(stage.mdout.details, "finished_properly", True):
                        completed = False

            avg_temp = sum(temps) / len(temps) if temps else None
            avg_press = sum(pressures) / len(pressures) if pressures else None

            writer.writerow([
                name,
                len(protocol.stages),
                f"{time_ns:.2f}",
                f"{avg_temp:.1f}" if avg_temp else "N/A",
                f"{avg_press:.1f}" if avg_press else "N/A",
                "Yes" if completed else "No"
            ])


def main():
    manifest_dir = Path("/path/to/manifests")
    protocols = load_protocols(manifest_dir)
    generate_report(protocols, Path("simulation_report.csv"))


if __name__ == "__main__":
    main()
```

### Step 3: Monitor Running Simulations

```python
#!/usr/bin/env python3
"""Monitor progress of running simulations."""

import time
from pathlib import Path
from ambermeta.parsers import MdoutParser

def check_progress(mdout_path: Path):
    """Check simulation progress from output file."""
    parser = MdoutParser(str(mdout_path))
    meta = parser.parse()

    if meta.stats:
        current_time = meta.stats.time_end
        print(f"  Current time: {current_time:.2f} ps")
        print(f"  Frames collected: {meta.stats.count}")
        print(f"  Avg temperature: {meta.stats.temp_mean:.2f} K")

    print(f"  Status: {'Running' if not meta.finished_properly else 'Complete'}")


def monitor_simulations(sim_dir: Path, interval: int = 60):
    """Monitor all simulations in a directory."""
    while True:
        print(f"\n{'='*60}")
        print(f"Checking simulations at {time.strftime('%H:%M:%S')}")
        print("="*60)

        for mdout in sim_dir.rglob("*.mdout"):
            print(f"\n{mdout.name}:")
            try:
                check_progress(mdout)
            except Exception as e:
                print(f"  Error: {e}")

        time.sleep(interval)


if __name__ == "__main__":
    monitor_simulations(Path("/path/to/running_sims"))
```

---

## Summary

This tutorial covered the main workflows for using AmberMeta:

1. **Extracting metadata** from individual AMBER files
2. **Building protocols** from directories or manifests
3. **Using the TUI** for interactive manifest creation
4. **Creating manifests** for reproducible documentation
5. **Validating continuity** between simulation stages
6. **Exporting data** for publications and reports
7. **Working with sequences** of production runs
8. **Automating collection** for large-scale projects

For more detailed information, see:
- [CLI Reference](cli.md) - Complete command-line documentation
- [TUI Guide](tui.md) - Detailed TUI documentation
- [Manifest Schema](manifest.md) - Full manifest format specification
- [Python API](api.md) - Complete API reference
