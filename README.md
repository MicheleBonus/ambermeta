# AmberMeta

**AmberMeta is a provenance engine for AMBER molecular-dynamics workflows. It reads the files a run already produced — `prmtop`, `mdin`, `mdout`, `mdcrd`, `inpcrd` — reconstructs the staged protocol behind them, validates that the stages actually connect, and exports a machine-readable record you can drop into a methods section or a downstream pipeline.**

You point it at a directory (or a manifest), and it answers the questions that are tedious to answer by hand: *What was actually run? In what order? Do the restarts line up? Is the topology hydrogen-mass-repartitioned? What were the ensemble, thermostat, barostat, and cutoff? Did the run finish?*

- **Version:** 1.0.0 · **Python:** 3.8+ · **License:** BUSL-1.1
- **Repository:** <https://github.com/MicheleBonus/ambermeta>

---

## 1. What it does

| Capability | What you get |
|---|---|
| **Metadata extraction** | Per-file parsers for topology, input, output, trajectory, and restart files. Atom/residue counts, box geometry, density, solvent model, HMR status, ensemble, thermostat/barostat, cutoff, SHAKE, completion status, and streaming thermodynamic statistics (temperature/pressure/density/energy, mean ± σ). |
| **Protocol assembly** | Groups loose files into ordered stages, detects numbered sequences (`prod_0001 … prod_0050`), infers each stage's role (minimization / heating / equilibration / production), and links the restart chain. |
| **Continuity validation** | Per-file checks (atom-count agreement, box sanity) and cross-stage checks (timing gaps between consecutive stages, restart→trajectory continuity), with configurable gap tolerances. |
| **Canonical manifests** | A *tolerant reader* (accepts YAML / JSON / TOML / CSV, legacy key aliases, several shapes) and a *canonical writer* (one deterministic on-disk form). The GUI and CLI write byte-identical manifests. |
| **Reproducibility exports** | A full protocol summary (JSON/YAML), a Materials-&-Methods-ready summary that keeps the reproducibility-critical metadata and drops the noise, and a per-stage statistics CSV. |

Two interfaces sit on one shared core:

| Surface | Use it when | Entry point |
|---|---|---|
| **CLI** | Scripting, CI, SSH/cluster, headless batch processing | `ambermeta <command>` |
| **GUI** | Interactively assembling or auditing a manifest in a browser | `ambermeta gui` |

> The CLI is the complete, headless interface — everything AmberMeta does is reachable without the GUI. The GUI is an optional, offline, localhost-only manifest editor built on the same engine (it imports the core through a single bridge module; it does not re-implement any logic). There is no separate TUI.

---

## 2. Install

AmberMeta requires **Python 3.8+**. The base install is dependency-light; optional features live behind extras.

```bash
python -m pip install -e .
```

| Extra | Pulls in | Enables |
|---|---|---|
| _(base)_ | stdlib only | All parsers except NetCDF; JSON & CSV manifests; full CLI |
| `netcdf` | `netCDF4`, `scipy`, `numpy` | NetCDF trajectory (`.nc`) and NetCDF restart (`.ncrst`) parsing |
| `gui` | `fastapi`, `uvicorn`, `websockets`, `python-multipart`, `pyyaml` | The browser GUI (`ambermeta gui`) |
| `yaml` | `pyyaml` | YAML manifests |
| `toml` | `tomli` (only on Python < 3.11; 3.11+ uses stdlib `tomllib`) | TOML manifests |
| `tests` | `pytest`, `pytest-cov`, `httpx` | Running the test suite |
| `dev` | `black`, `ruff`, `mypy` | Linting and type checking |
| `all` | everything runtime (netcdf + gui + yaml + toml) | The full feature set (does **not** include `tests`/`dev`) |

```bash
python -m pip install -e ".[all]"     # all runtime features
python -m pip install -e ".[gui]"     # just the GUI
```

> ⚠️ The GUI ships a **pre-built, offline frontend bundle** under `ambermeta/gui/static/`. No Node.js, no build step, and no CDN at runtime — it works on an air-gapped workstation. The `gui` extra only adds the Python web server.

---

## 3. Sixty-second quickstart (CLI)

Every command below is run against the sample data in `tests/data/amber/md_test_files/` — a real 64,528-atom glycoprotein system with a six-member NPT production sequence.

**Preview how a directory groups into stages — without writing anything:**

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
  7. ntp_prod_0005 [production]
     mdin: ntp_prod_0005.mdin
     mdout: ntp_prod_0005.mdout
     inpcrd: ntp_prod_0005.rst

Dry run complete; no files were written.
```

**Build the protocol straight from disk and print the reconstructed summary:**

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
  mdin: steps=5000000, dt=0.004 ps
  mdout: status=complete, steps=5000000, dt=0.004 ps, thermostat=Langevin @ 300 K, barostat=Berendsen, box=RECTILINEAR
  inpcrd: atoms=64528, box, time=20920 ps
  stats: frames=200, time=1020–20920 ps, temp=300.43 ± 1.25 K, density=1.0370 ± 0.0012 g/cc
  restart: .../ntp_prod_0001.rst
  evidence: INFO: Part of sequence 'ntp_prod' (item 2 of 6); INFO: stage_role inferred from mdin file
```

**Inspect a single file in depth:**

```text
$ ambermeta info tests/data/amber/md_test_files/CH3L1_HUMAN_6NAG.top

File Information: CH3L1_HUMAN_6NAG.top
============================================================
  natom: 64528
  nres: 15102
  total_charge: 8.02e-05
  is_neutral: True
  box_dimensions: [98.34, 76.05, 81.23]
  density: 0.8434
  solvent_type: Explicit Solvent
  simulation_category: Protein in Explicit Water
  hmr_active: False
  hmr_hydrogen_mass_summary: 1.008-1.008 amu across 32188 H
  hmr_detection_method: atomic_number
```

**Validate a set of files (exit code `0`/`1` for CI):**

```text
$ ambermeta validate tests/data/amber/md_test_files/*.{top,mdin,mdout,rst}

Validation Results
==================================================
OK: CH3L1_HUMAN_6NAG.top
OK: ntp_prod_0001.mdin
OK: ntp_prod_0001.mdout
OK: ntp_prod_0001.rst
==================================================
Validation PASSED
```

The full, manifest-driven workflow — bootstrap a manifest, then export the reproducibility artifacts — is in the [CLI reference](docs/cli.md) and the [tutorials](docs/tutorials.md).

---

## 4. The manifest

A manifest is the durable, hand-editable description of a protocol: an ordered list of stages, each pointing at its files, plus optional global topology and validation settings. AmberMeta reads four formats and writes one canonical form.

```yaml
# protocol.yaml
global_prmtop: systems/complex.prmtop
hmr_prmtop: systems/complex_hmr.prmtop
stages:
  - name: minimize
    stage_role: minimization
    mdin: mdin/min.in
    mdout: logs/min.out
  - name: prod1
    stage_role: production
    mdin: mdin/prod1.in
    mdout: logs/prod1.out
    mdcrd: traj/prod1.nc
    inpcrd: restarts/equil.rst7
    expected_gap_ps: 0.0
    gap_tolerance_ps: 0.1
```

```bash
ambermeta plan ./runs --manifest protocol.yaml --summary-path summary.json
```

The complete schema — every key, all four formats, gap configuration, environment-variable expansion, and role-inference rules — is documented in the [manifest schema reference](docs/manifest.md).

---

## 5. Python API

The same engine is a library. Parsers return a wrapper whose parsed fields live on `.details`; protocol assembly is one call.

```python
from ambermeta import auto_discover, load_protocol_from_manifest

# Reconstruct a protocol from a directory
protocol = auto_discover("runs/", recursive=True, auto_detect_restarts=True)
print(len(protocol.stages), protocol.totals())   # -> 7 {'steps': 25000000.0, 'time_ps': 100000.0}

# ...or from a manifest
protocol = load_protocol_from_manifest("protocol.yaml", directory="runs/")

# Per-file parsing — note the .details accessor
from ambermeta.parsers import PrmtopParser
result = PrmtopParser("system.prmtop").parse()
meta = result.details
print(meta.natom, meta.hmr_active, meta.solvent_type)
```

The full surface — `SimulationProtocol`, `SimulationStage`, `ProtocolBuilder`, the discovery functions, and every parser metadata field — is in the [Python API reference](docs/api.md).

---

## 6. GUI

```bash
ambermeta gui tests/data/amber/md_test_files          # opens http://127.0.0.1:8765
ambermeta gui runs/ --port 9000 --no-browser
```

A three-pane browser app — **Files** (left) · **Stages** (center) · **Properties** (right) — for assembling and auditing a manifest: drag files onto stage slots, one-click **Discover** to auto-group a directory, a **Validate** panel that jumps you to each issue, and **Open**/**Save** that read and write the *same canonical manifest* the CLI does. The server is single-user, **localhost-only**, and confines all file access to the directory you launched it in. Full walkthrough: [GUI guide](docs/gui.md).

---

## 7. Command reference

| Command | Purpose |
|---|---|
| `ambermeta plan` | Build and summarize a protocol from a manifest, recursive discovery, or interactive prompts; export summaries and stats |
| `ambermeta init` | Generate a manifest — a template, or `--auto` to bootstrap one from a directory |
| `ambermeta validate` | Validate one or more files without building a full protocol |
| `ambermeta info` | Print parsed metadata for a single file (text / JSON / YAML) |
| `ambermeta gui` | Launch the browser GUI |
| `ambermeta completion` | Emit a shell-completion script (bash / zsh / fish) |

Global options (`--log-level`, `--log-file`, `-q/--quiet`) and every flag are documented — and kept in sync with the parser by CI — in the [CLI reference](docs/cli.md).

---

## 8. Documentation

| Document | What's inside |
|---|---|
| [Architecture](docs/architecture.md) | How the engine is built: the manifest contract, protocol assembly, the parser layer, the validation model, and the GUI's single-engine bridge |
| [CLI reference](docs/cli.md) | Every command, flag, exit code, and environment variable |
| [Python API reference](docs/api.md) | Classes, functions, parser metadata fields, and worked examples |
| [Manifest schema](docs/manifest.md) | The full file format across YAML / JSON / TOML / CSV |
| [GUI guide](docs/gui.md) | The browser app, its API surface, and its security model |
| [Tutorials](docs/tutorials.md) | Task-oriented, step-by-step walkthroughs |
| [Recipes](docs/recipes.md) | Copy-paste CLI one-liners for common jobs |

---

## 9. Compatibility & limitations

- **AMBER engines:** parses output from both `pmemd`/`pmemd.cuda` and `sander`. Completion detection, GPU model, wall-time, and ns/day are read from the `mdout` footer where present.
- **NetCDF:** `.nc` trajectories and `.ncrst` restarts require the `netcdf` extra. Without it, ASCII trajectories/restarts still parse; NetCDF files are reported as unreadable rather than crashing the run.
- **Fault tolerance:** `ambermeta plan` is fault-tolerant by default — an unreadable or malformed file is skipped, the error is recorded against its stage, and the run still completes (exit `0`). Pass `--strict` to make the first bad file a hard error.
- **Role inference is heuristic.** When a stage omits `stage_role`, AmberMeta infers it from the `mdin`/`mdout` content first, then the path — and always records an `INFO` note saying it did so. Verify inferred roles before publishing.
- **Manifest formats:** YAML needs `pyyaml`; TOML needs `tomli` on Python < 3.11 (stdlib `tomllib` on 3.11+). JSON and CSV are always available.

---

## 10. License

AmberMeta is distributed under the **Business Source License 1.1 (BUSL-1.1)**. See [`LICENSE`](LICENSE) for the full terms.
