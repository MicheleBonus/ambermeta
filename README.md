# AmberMeta

**AmberMeta is a provenance engine for AMBER molecular-dynamics workflows. It reads the files a run already produced — `prmtop`, `mdin`, `mdout`, `mdcrd`, `inpcrd` — reconstructs the simulation behind them as a `Simulation → Phase → Step` document, validates that the steps actually connect, and exports a machine-readable record you can drop into a methods section or a downstream pipeline.**

You point it at a directory (or a manifest), and it answers the questions that are tedious to answer by hand: *What was actually run? In what order? Do the restarts line up? Is any topology hydrogen-mass-repartitioned? What were the ensemble, thermostat, barostat, and cutoff? Did the run finish? Is a member of a numbered sequence missing?*

- **Version:** 1.1.0 · **Python:** 3.9+ · **License:** BUSL-1.1
- **Repository:** <https://github.com/MicheleBonus/ambermeta>

---

## 1. The model

A **Simulation** is the whole document. It owns a **topology pool** (one or more prmtops, each labeled `normal` or `hmr`) and a single **starting structure**. A **Phase** is a named, role-bearing container — minimization / heating / equilibration / production — that groups related runs. A **Step** is one actual run: it binds one topology from the pool, names its `mdin`/`mdout`/`mdcrd`, and declares where its input coordinates come from (the Simulation's starting structure, a previous step's output restart, or an explicit path).

That last part is what makes continuity checking exact: AmberMeta follows the declared input-coordinate chain from step to step, compares each hand-off's timing against a frame-interval-based tolerance, and flags both broken continuity and holes in numbered sequences (`prod_0001, prod_0002, prod_0004, …` → `0003` is missing) as first-class findings — not as an afterthought bolted onto a flat stage list.

| Capability | What you get |
|---|---|
| **Metadata extraction** | Per-file parsers for topology, input, output, trajectory, and restart files. Atom/residue counts, box geometry, density, solvent model, HMR status, ensemble, thermostat/barostat, cutoff, SHAKE, completion status, and streaming thermodynamic statistics (temperature/pressure/density/energy, mean ± σ). |
| **Simulation discovery** | Scans a directory into a `Simulation` draft: builds the topology pool, detects numbered sequences, infers each step's role (minimization / heating / equilibration / production) from content then path, and resolves the input-coordinate chain — all as explainable, one-click-undoable suggestions. |
| **Continuity & sequence validation** | Per-file checks (atom-count agreement, box sanity) and whole-simulation checks (timing gaps between chained steps against a tolerance, missing members of a numbered run), with configurable per-step tolerances. |
| **Manifest format v2** | A *tolerant reader* that opens v2 manifests natively and auto-migrates legacy v1 flat manifests in memory, plus a *canonical writer* (JSON or YAML). The GUI and CLI share the same document. |
| **Reproducibility exports** | A full simulation/protocol summary (JSON/YAML), a Materials-&-Methods-ready summary that keeps the reproducibility-critical metadata and drops the noise, and a per-stage statistics CSV. |

Two interfaces sit on one shared core:

| Surface | Use it when | Entry point |
|---|---|---|
| **CLI** | Scripting, CI, SSH/cluster, headless batch processing | `ambermeta <command>` |
| **GUI** | Interactively assembling or auditing a manifest in a browser | `ambermeta gui` |

> The CLI is the complete, headless interface — everything AmberMeta does is reachable without the GUI. The GUI is an optional, offline, localhost-only manifest editor built on the same engine (it imports the core through a single bridge module, `ambermeta.gui.api.core_bridge`; it does not re-implement any logic). There is no separate TUI.

---

## 2. Install

AmberMeta requires **Python 3.9+**. The base install is dependency-light; optional features live behind extras.

```bash
python -m pip install -e .
```

| Extra | Pulls in | Enables |
|---|---|---|
| _(base)_ | stdlib only | All parsers except NetCDF; JSON & CSV manifests; full CLI |
| `netcdf` | `netCDF4`, `scipy`, `numpy` | NetCDF trajectory (`.nc`) and NetCDF restart (`.ncrst`) parsing |
| `gui` | `fastapi`, `uvicorn`, `websockets`, `python-multipart`, `pyyaml` | The browser GUI (`ambermeta gui`) |
| `yaml` | `pyyaml` | YAML manifests |
| `toml` | `tomli` (only on Python < 3.11; 3.11+ uses stdlib `tomllib`) | TOML manifests (legacy flat export only — see §4) |
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

**Discover the directory into a Simulation draft and save it as a v2 manifest:**

```text
$ ambermeta discover tests/data/amber/md_test_files --write sim.yaml

Simulation summary
==================
Topologies (pool): 1
  - top_CH3L1_HUMAN_6NAG [normal]  CH3L1_HUMAN_6NAG.top
Starting structure: CH3L1_HUMAN_6NAG.crd
Phases: 1

Phase: Production [production]
  - ntp_prod_0001  topology=CH3L1_HUMAN_6NAG.top  input=starting structure  (mdin=ntp_prod_0001.mdin, mdout=ntp_prod_0001.mdout)
  - ntp_prod_0002  topology=CH3L1_HUMAN_6NAG.top  input=step ffb5de6a  (mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)
  - ntp_prod_0003  topology=CH3L1_HUMAN_6NAG.top  input=step 295e0a9f  (mdin=ntp_prod_0003.mdin, mdout=ntp_prod_0003.mdout)
  - ntp_prod_0004  topology=CH3L1_HUMAN_6NAG.top  input=step 9ab831d9  (mdin=ntp_prod_0004.mdin, mdout=ntp_prod_0004.mdout)
  - ntp_prod_0005  topology=CH3L1_HUMAN_6NAG.top  input=step f0eb600f  (mdin=ntp_prod_0005.mdin, mdout=ntp_prod_0005.mdout)

Suggestions:
  - [applied] CH3L1_HUMAN_6NAG.crd set as the starting structure
  - [applied] Phase roles inferred from file content/names

Wrote v2 draft manifest: tests/data/amber/md_test_files/sim.yaml (yaml)
```

**Inspect a single file in depth:**

```text
$ ambermeta info tests/data/amber/md_test_files/CH3L1_HUMAN_6NAG.top

File Information: CH3L1_HUMAN_6NAG.top
============================================================
  natom: 64528
  nres: 15102
  nbond: 64539
  total_charge: 8.020996347271433e-05
  is_neutral: True
  box_dimensions: [98.3405545, 76.0526585, 81.2272985]
  density: 0.8433970648221194
  solvent_type: Explicit Solvent
  simulation_category: Protein / Ligand in Explicit Water
  num_solvent_molecules: 14659
  num_solute_residues: 443
  hmr_active: False
  hmr_hydrogen_mass_summary: 1.008-1.008 amu across 32188 H
  hmr_detection_method: atomic_number
  ... (also: version, title, force_field_features, total_mass, box_angles,
      box_volume, box_is_topology_time, residue_composition — run it yourself for
      the full field list)
```

**Validate the whole Simulation — continuity, sequence holes, and suggestions (exit code `0`/`1` for CI):**

```text
$ ambermeta validate --manifest sim.yaml

Simulation validation

Validation: OK
```

**Export the manifest — here, downgrading it to the legacy flat form some downstream tooling still expects:**

```text
$ ambermeta export sim.yaml --to legacy -o legacy.yaml

Wrote legacy manifest: tests/data/amber/md_test_files/legacy.yaml (yaml)
```

The full, manifest-driven workflow — editing a manifest by hand, re-validating, and exporting reproducibility artifacts — is in the [CLI reference](docs/cli.md) and the [tutorials](docs/tutorials.md).

---

## 4. The manifest

A manifest is the durable, hand-editable description of a simulation: a topology pool, a starting structure, an ordered list of phases, and the steps inside them. This is **manifest format v2** — the canonical, current shape:

```yaml
version: 2
simulation:
  topologies:
    - id: top_wt
      path: wt.prmtop
      kind: normal          # "normal" | "hmr" (detected, overridable)
    - id: top_wt_hmr
      path: wt_hmr.prmtop
      kind: hmr
  starting_structure: wt.inpcrd
phases:
  - { id: ph_min,  name: Minimization, role: minimization, order: 0 }
  - { id: ph_prod, name: Production,    role: production,   order: 1 }
steps:
  - id: st_min
    name: minimize
    phase: ph_min
    order: 0
    topology: top_wt                              # reference into the pool
    input_coords: { source: starting_structure }
    mdin: min.in
    mdout: min.out
  - id: st_prod_001
    name: prod_001
    phase: ph_prod
    order: 0
    topology: top_wt_hmr
    input_coords: { source: step, ref: st_min }   # or { source: path, path: "..." }
    mdin: prod_001.in
    mdout: prod_001.out
    mdcrd: prod_001.nc
    gaps: { expected: null, tolerance: null }
```

Each step's `input_coords.source` is one of `starting_structure`, `step` (with `ref: <step id>`), or `path` (with an explicit `path:`) — that's the continuity anchor the validator walks. `gaps.expected`/`gaps.tolerance` are the per-step expected inter-run gap and tolerance, in ps; both may be `null`.

**v2 is written as JSON or YAML** (`write_simulation`). The legacy flat form (`export --to legacy`) can additionally write TOML or CSV, for tooling that hasn't moved to v2 yet.

```bash
ambermeta validate --manifest simulation.yaml --summary-path summary.json
```

The complete schema — every key, all input-coordinate sources, gap configuration, environment-variable expansion, role tokens, and the v1→v2 auto-migration table — is documented in the [manifest schema reference](docs/manifest.md).

### Coming from v1?

v1's flat `stages:` manifest — `global_prmtop`/`hmr_prmtop`, `initial_coordinates`, one stage per run — **still opens**. AmberMeta's reader detects it and auto-migrates it to a `Simulation` in memory: each stage becomes a step, contiguous same-role stages coalesce into a phase, `global_prmtop`/`hmr_prmtop` become pool entries, `initial_coordinates` becomes the starting structure, and the first step reads it while every later step chains from the previous step's restart. Saving always writes v2.

Given this v1 manifest:

```yaml
global_prmtop: CH3L1_HUMAN_6NAG.top
stages:
  - name: prod1
    stage_role: production
    mdin: ntp_prod_0001.mdin
    mdout: ntp_prod_0001.mdout
    inpcrd: ntp_prod_0000.rst
  - name: prod2
    stage_role: production
    mdin: ntp_prod_0002.mdin
    mdout: ntp_prod_0002.mdout
    inpcrd: ntp_prod_0001.rst
```

`ambermeta export protocol.yaml --to v2` prints the migrated v2 document:

```json
{
  "version": 2,
  "simulation": { "topologies": [{"id": "top_0", "path": "CH3L1_HUMAN_6NAG.top", "kind": "normal"}], "starting_structure": null },
  "phases": [{ "id": "ph_0", "name": "Production", "role": "production", "order": 0 }],
  "steps": [
    { "id": "st_0", "name": "prod1", "phase": "ph_0", "order": 0, "topology": "top_0",
      "input_coords": {"source": "path", "path": "ntp_prod_0000.rst"},
      "mdin": "ntp_prod_0001.mdin", "mdout": "ntp_prod_0001.mdout", "mdcrd": null, "notes": [] },
    { "id": "st_1", "name": "prod2", "phase": "ph_0", "order": 1, "topology": "top_0",
      "input_coords": {"source": "step", "ref": "st_0"},
      "mdin": "ntp_prod_0002.mdin", "mdout": "ntp_prod_0002.mdout", "mdcrd": null, "notes": [] }
  ]
}
```

Note that the second step's coordinate source resolved to `{"source": "step", "ref": "st_0"}` — the migrator recognized `ntp_prod_0001.rst` as the first step's own restart output and rewired it into an explicit continuity edge instead of leaving it as a bare path. `ambermeta plan`/`validate` still read v1 manifests directly too, and `ambermeta init --v2` generates a fresh v2 template if you'd rather start clean.

---

## 5. Python API

The same engine is a library, with two layers. For the new model, work with `ambermeta.simulation` directly — it is not (yet) re-exported at the `ambermeta` top level:

```python
from ambermeta.simulation import load_simulation

sim = load_simulation("sim.yaml")   # v1 manifests auto-migrate on read
print(sim.topologies)
# -> [Topology(id='top_CH3L1_HUMAN_6NAG', path='CH3L1_HUMAN_6NAG.top', kind='normal')]
print(sim.starting_structure)
# -> CH3L1_HUMAN_6NAG.crd
for phase in sim.phases:
    print(phase.name, phase.role, [s.name for s in phase.steps])
# -> Production production ['ntp_prod_0001', 'ntp_prod_0002', 'ntp_prod_0003', 'ntp_prod_0004', 'ntp_prod_0005']
```

`write_simulation(sim, path, fmt)` (`fmt` is `"json"` or `"yaml"`) writes it back out; `simulation_to_payload`/`payload_to_simulation` round-trip a `Simulation` through the same JSON-shaped dict the GUI's HTTP API uses.

The retained parsing engine — file discovery, the flat `SimulationProtocol`/`SimulationStage` model, and the per-file parsers — is still the public top-level `ambermeta.*` surface, and still powers `discover`/`validate --manifest` under the hood via `ambermeta.gui.api.core_bridge`:

```python
from ambermeta import auto_discover, load_protocol_from_manifest

# Reconstruct a flat protocol from a directory (the legacy path `plan --recursive` uses)
protocol = auto_discover("runs/", recursive=True, auto_detect_restarts=True)
print(len(protocol.stages), protocol.totals())

# Per-file parsing — note the .details accessor
from ambermeta.parsers import PrmtopParser
result = PrmtopParser("system.prmtop").parse()
meta = result.details
print(meta.natom, meta.hmr_active, meta.solvent_type)
```

The full surface — every `ambermeta.simulation` dataclass, the retained `SimulationProtocol`/`SimulationStage`/`ProtocolBuilder`, the `core_bridge.discover_draft`/`validate_simulation` helpers that back the CLI and GUI, and every parser metadata field — is in the [Python API reference](docs/api.md).

---

## 6. GUI

```bash
ambermeta gui tests/data/amber/md_test_files          # opens http://127.0.0.1:8765
ambermeta gui runs/ --port 9000 --no-browser
```

A rebuilt three-pane browser app for assembling and auditing a Simulation:

- **Files** (left) — a searchable file list; drag a file onto the topology pool, the starting-structure slot, a step's topology, or a step's `mdin`/`mdout`/`mdcrd` slot.
- **Canvas** (center) — a continuous vertical timeline: phases as sections, steps as cards showing their bound topology and input-coordinate source, continuity arrows between chained steps (amber where a real gap exists), and ghost cards for missing members of a numbered sequence. Drag to reorder steps, move a step across phases, or reorder phases.
- **Inspector** (right) — peek and full-details/raw tabs for whatever's selected, plus assign actions. The step/phase inline editors are still stubs — edit those fields by dragging files or via the manifest for now.

A **Suggestions** tray surfaces every inferred thing (roles, HMR topology, starting structure, sequence holes, continuity gaps) as an explainable, undoable suggestion rather than applying it silently. **Discover** re-runs discover-as-draft on the launch directory; **Open**/**Save** read and write the same v2 manifest the CLI does; **Validate** lists issues.

The server is server-authoritative (a single document held server-side; every mutation returns the new document; undo/redo call the server), single-user, **localhost-only**, and confines all file access to the launch directory. Full walkthrough, including the HTTP API surface: [GUI guide](docs/gui.md).

---

## 7. Command reference

| Command | Purpose |
|---|---|
| `ambermeta discover` | Scan a directory into a Simulation draft (topology pool, phases, steps with input-coord sources) and optionally write a v2 manifest |
| `ambermeta plan` | Build and summarize a Simulation (v2, or auto-migrated v1) from a manifest, or a flat protocol via recursive discovery / interactive prompts; export summaries and stats |
| `ambermeta validate` | Validate individual files, or a whole Simulation manifest (`--manifest`) for continuity and sequence holes |
| `ambermeta export` | Convert a manifest (v1 auto-migrated) to canonical v2, or to a legacy flat manifest for older tooling |
| `ambermeta init` | Generate a manifest — v1 or v2 templates (`--v2`), or `--auto` to bootstrap a v1 flat manifest from a directory |
| `ambermeta info` | Print parsed metadata for a single file (text / JSON / YAML) |
| `ambermeta gui` | Launch the browser GUI |
| `ambermeta completion` | Emit a shell-completion script (bash / zsh / fish) |

Global options (`--log-level`, `--log-file`, `-q/--quiet`) and every flag are documented — and kept in sync with the parser by CI — in the [CLI reference](docs/cli.md).

---

## 8. Documentation

| Document | What's inside |
|---|---|
| [Architecture](docs/architecture.md) | How the engine is built: the Simulation → Phase → Step model, the topology pool and input-coordinate sources, continuity/sequence detection, manifest v2 and the auto-migrating reader, the shared role classifier, the parser layer, and the GUI's single-engine bridge |
| [CLI reference](docs/cli.md) | Every command, flag, exit code, and environment variable |
| [Python API reference](docs/api.md) | Classes, functions, parser metadata fields, and worked examples |
| [Manifest schema](docs/manifest.md) | The full v2 schema, the four input formats, v1→v2 auto-migration, environment-variable expansion, and role tokens |
| [GUI guide](docs/gui.md) | The browser app, its API surface, and its security model |
| [Tutorials](docs/tutorials.md) | Task-oriented, step-by-step walkthroughs |
| [Recipes](docs/recipes.md) | Copy-paste CLI one-liners for common jobs |

A single-page, fully offline HTML version of these docs lives at [`docs/ambermeta.html`](docs/ambermeta.html) — open it in any browser (no server, no network).

---

## 9. Compatibility & limitations

- **v1 manifests still open.** A bare `stages:` list or a `global_prmtop`/`hmr_prmtop`/`initial_coordinates` manifest is auto-migrated to the v2 model on read; saving always writes v2. See [Coming from v1?](#coming-from-v1) above and the migration table in the [manifest reference](docs/manifest.md).
- **AMBER engines:** parses output from both `pmemd`/`pmemd.cuda` and `sander`. Completion detection, GPU model, wall-time, and ns/day are read from the `mdout` footer where present.
- **NetCDF:** `.nc` trajectories and `.ncrst` restarts require the `netcdf` extra. Without it, ASCII trajectories/restarts still parse; NetCDF files are reported as unreadable rather than crashing the run.
- **Fault tolerance:** `ambermeta plan` is fault-tolerant by default — an unreadable or malformed file is skipped, the error is recorded against its stage/step, and the run still completes (exit `0`). Pass `--strict` to make the first bad file a hard error.
- **Role inference is heuristic.** When a phase or stage omits its role, AmberMeta infers it from the `mdin`/`mdout` content first, then the file/path name (word-boundary matching, via the shared classifier in `ambermeta/roles.py`) — and records that it did so. Verify inferred roles before publishing.
- **The GUI's Inspector editors are stubs.** You can drag files onto slots and reorder phases/steps on the canvas, but there's no inline form yet for hand-editing a step's or phase's fields — do that in the manifest, or via the HTTP API.
- **Manifest formats:** v2 is JSON or YAML only. The legacy flat form also supports TOML (needs `tomli` on Python < 3.11; stdlib `tomllib` on 3.11+) and CSV.

---

## 10. License

AmberMeta is distributed under the **Business Source License 1.1 (BUSL-1.1)**. See [`LICENSE`](LICENSE) for the full terms.
