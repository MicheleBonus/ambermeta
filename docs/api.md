# Python API reference

**AmberMeta is a library, not just a CLI.** Everything `ambermeta` does on the command line is one import away.

There are **two layers**, and it matters which one you reach for:

1. **`ambermeta.simulation`** — the new Simulation → Phase → Step model (plain dataclasses). Read/write manifest v2, round-trip a `Simulation` object, hand it to the GUI's own helpers. **Not yet re-exported at the `ambermeta` top level** — import it from `ambermeta.simulation` explicitly.
2. **Top-level `ambermeta.*`** — the retained parsing/assembly engine that powers file parsing, the legacy flat `plan --recursive` path, and everything under the hood of layer 1. This is where the parsers, `SimulationProtocol`/`SimulationStage`, and the discovery utilities live. Nothing here was removed; it is still the public `__all__`.

```python
# Layer 1 — the new model
from ambermeta.simulation import (
    load_simulation, write_simulation,
    simulation_to_payload, payload_to_simulation,
    Simulation, Phase, Step, Topology, InputCoords,
)

# Layer 2 — the retained parsing/assembly engine (ambermeta/__init__.py __all__)
from ambermeta import (
    SimulationProtocol, SimulationStage, ProtocolBuilder,
    auto_discover, load_protocol_from_manifest, load_manifest,
    detect_numeric_sequences, smart_group_files,
    auto_detect_restart_chain, infer_stage_role_from_content,
    AmberMetaError, FileLoadError, __version__,
)
from ambermeta.parsers import (
    PrmtopParser, MdinParser, MdoutParser, MdcrdParser, InpcrdParser,
)
```

> ⚠️ **The one thing to get right.** A parser's `parse()` returns a small wrapper (`PrmtopData`, `MdinData`, …) that carries `filename` and `warnings`. **The parsed metadata lives on `.details`.**
>
> ```python
> result = PrmtopParser("system.prmtop").parse()
> meta = result.details        # <-- the metadata object
> meta.natom                   # 64528
> result.warnings              # [] (on the wrapper, not .details)
> ```
>
> Field names are AMBER-flavored and differ from intuition: `hmr_active` (not `is_hmr`), `residue_composition` (not `residue_counts`), `temp_control`/`press_control`/`stage_role` on `mdin`. The exact field list per file type is in [§7](#7-parser-metadata-fields).

Examples below run against the sample data shipped in the repo: `tests/data/amber/md_test_files/` — a 64,528-atom glycoprotein system (`CH3L1_HUMAN_6NAG.top`/`.crd`) with a six-member NPT production sequence `ntp_prod_0000..0005`.

---

## 1. The `ambermeta.simulation` model

Plain dataclasses mirroring [manifest v2](manifest.md): a `Simulation` owns a **topology pool** and a **starting structure**; it contains `Phase`s; each `Phase` contains `Step`s.

```python
@dataclass
class Topology:
    id: str
    path: str
    kind: str = "normal"          # "normal" | "hmr"

@dataclass
class InputCoords:
    source: str = "starting_structure"   # "starting_structure" | "step" | "path"
    ref: Optional[str] = None             # Step.id when source == "step"
    path: Optional[str] = None            # explicit path when source == "path"

@dataclass
class Step:
    id: str
    name: str
    topology: Optional[str] = None        # Topology.id
    input_coords: InputCoords = field(default_factory=InputCoords)
    mdin: Optional[str] = None
    mdout: Optional[str] = None
    mdcrd: Optional[str] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: List[str] = field(default_factory=list)

@dataclass
class Phase:
    id: str
    name: str
    role: str = ""                        # "minimization" | "heating" | "equilibration" | "production" | ""
    steps: List[Step] = field(default_factory=list)

@dataclass
class Simulation:
    version: int = 2
    topologies: List[Topology] = field(default_factory=list)
    starting_structure: Optional[str] = None
    phases: List[Phase] = field(default_factory=list)
```

### `load_simulation()`

```python
def load_simulation(path: str) -> Simulation
```

Reads any manifest — v2, or a **v1 flat manifest**, which is auto-migrated in memory (each stage becomes a `Step`; contiguous same-role stages coalesce into one `Phase`; `global_prmtop`/`hmr_prmtop` become pool entries; `initial_coordinates` becomes the starting structure). See the [manifest schema](manifest.md) for the exact migration table.

### `write_simulation()`

```python
def write_simulation(sim: Simulation, path: str, fmt: str) -> None
```

Writes a `Simulation` as a v2 manifest. `fmt` is `"json"` or `"yaml"` **only** — v2 has no TOML/CSV writer (use `export --to legacy` for those, which flattens to the v1 shape first).

### `simulation_to_payload()` / `payload_to_simulation()`

```python
def simulation_to_payload(sim: Simulation) -> Dict[str, Any]
def payload_to_simulation(payload: Dict[str, Any]) -> Simulation
```

The v2 dict round-trip `write_simulation`/`load_simulation` use internally — reach for these directly when you want the dict (e.g. to `json.dumps` it yourself, hand it to a web response, or inspect it without touching disk).

### Worked example: discover, inspect, round-trip

```python
import os
from ambermeta.gui.api.core_bridge import discover_draft
from ambermeta.simulation import simulation_to_payload, write_simulation, load_simulation

base = os.path.abspath("tests/data/amber/md_test_files")
result = discover_draft(base)
sim = result["simulation"]

[(t.id, t.path, t.kind) for t in sim.topologies]
# [('top_CH3L1_HUMAN_6NAG', 'CH3L1_HUMAN_6NAG.top', 'normal')]

sim.starting_structure
# 'CH3L1_HUMAN_6NAG.crd'

sim.phases[0].name, sim.phases[0].role, len(sim.phases[0].steps)
# ('Production', 'production', 5)

sim.phases[0].steps[0].input_coords
# InputCoords(source='starting_structure', ref=None, path=None)

sim.phases[0].steps[1].input_coords
# InputCoords(source='step', ref='4a09deaa', path='ntp_prod_0001.rst')

write_simulation(sim, "simulation.json", "json")
sim2 = load_simulation("simulation.json")
len(sim2.phases) == len(sim.phases)
# True
```

`input_coords` on the first step of a phase resolves to the Simulation's starting structure; every later step chains from the previous step's output restart — `discover_draft` already resolves that restart's path into `input_coords.path` so continuity can read its time without re-scanning the directory.

---

## 2. Advanced/shared helpers — `ambermeta.gui.api.core_bridge`

Pure functions the CLI and GUI both call — this module is the **only** place in `ambermeta.gui` that imports the parsing/assembly engine, so it is the ground truth for how `discover`/`validate --manifest` actually work. Useful directly if you're building your own tooling on top of the same engine the GUI uses.

### `discover_draft()`

```python
def discover_draft(
    base_directory: str,
    recursive: bool = True,
    pattern: Optional[str] = None,
) -> Dict[str, Any]   # {"simulation": Simulation, "suggestions": [...], "warnings": [...]}
```

Scans a directory into a **Simulation draft**: builds the topology pool (HMR detected from timestep, `ambermeta.topology_pool.classify_topology_pool`), finds a starting structure (a single-frame coordinate file outside any run group), groups runs into phases by inferred role (`ambermeta.roles.classify_role` — the one classifier shared by CLI and GUI), and chains each step's `input_coords` off the previous step. This is what `ambermeta discover` calls; see [§1](#1-the-ambermetasimulation-model) for a full run.

### `validate_simulation()`

```python
def validate_simulation(
    sim: Simulation,
    settings: dict,
    base_directory: str,
) -> Dict[str, Any]
```

Flattens the `Simulation` back to the stage shape the retained engine validates (`_flatten_simulation` internally, then `auto_discover(..., manifest=flat_stages)`), and layers on continuity/sequence-hole suggestions. Returns a report with `ok`, `totals`, `protocol_issues`, `stage_issues`, and `suggestions`. This is what `ambermeta validate --manifest` calls.

```python
report = validate_simulation(sim, {}, base)
report["ok"]
# True
report["totals"]
# {'steps': 25000000.0, 'time_ps': 100000.0, 'stage_count': 5}
report["suggestions"]
# [{'id': 'sug_1', 'kind': 'starting_structure', 'severity': 'applied',
#   'title': 'CH3L1_HUMAN_6NAG.crd set as the starting structure',
#   'evidence': 'single-frame coordinates; feeds the first run', 'actions': ['Undo']},
#  {'id': 'sug_2', 'kind': 'role_guess', 'severity': 'applied',
#   'title': 'Phase roles inferred from file content/names',
#   'evidence': 'Production->production', 'actions': ['Undo']}]
```

Each suggestion carries a `kind` (`missing_run`, `topology_confirm`, `starting_structure`, `role_guess`, `continuity_gap`), a `severity` (`applied` — already assumed, reversible; `needs_you` — a real decision), and `evidence` explaining why it fired. This is the same list the GUI's suggestions tray renders.

Other `core_bridge` entry points worth knowing about: `file_metadata(path)` (parse-and-serialize one file by extension), `read_file_head(path, max_bytes=4096)` (raw text preview), and `open_simulation`/`save_simulation`/`preview_simulation` (thin wrappers over `load_simulation`/`write_simulation` behind the GUI's document endpoints — see the [GUI guide](gui.md) for the HTTP API surface).

---

## 3. The retained engine: discovery & assembly

These build a `SimulationProtocol` from files or a manifest — the layer that predates the Simulation/Phase/Step model and still does all the actual file parsing and cross-run validation underneath it. Most programs that only need "read these files and tell me what happened" call one of these directly and never touch a parser.

### `auto_discover()`

```python
def auto_discover(
    directory: str,
    manifest: Optional[Dict | List] = None,
    grouping_rules: Optional[Dict[str, str]] = None,
    include_roles: Optional[List[str]] = None,
    include_stems: Optional[List[str]] = None,
    restart_files: Optional[Dict[str, str]] = None,
    skip_cross_stage_validation: bool = False,
    recursive: bool = False,
    auto_detect_restarts: bool = False,
    pattern_filter: Optional[str] = None,
    global_prmtop: Optional[str] = None,
    hmr_prmtop: Optional[str] = None,
    allow_unexpected_gaps: bool = False,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    strict: bool = False,
) -> SimulationProtocol
```

Discover and parse simulation files into an ordered protocol. With `manifest` provided, it parses the listed stages; with `manifest=None`, it discovers files on disk (`recursive=True` to descend) — note this directory-scan path builds one stage per **file group** (stem), including non-run groups such as a bare topology+coordinate pair, unlike `discover_draft` which only emits steps for groups with an `mdin`/`mdout`. `strict=True` makes the first unreadable file a hard `AmberMetaError`; the default skips it and records a `FileLoadError`.

```python
from ambermeta import auto_discover

protocol = auto_discover("tests/data/amber/md_test_files", recursive=True, auto_detect_restarts=True)
print(len(protocol.stages), protocol.totals())
# 7 {'steps': 25000000.0, 'time_ps': 100000.0}
```

(Seven stages: the bare `CH3L1_HUMAN_6NAG` topology/coordinate pair, the starting `ntp_prod_0000` restart, and the five `ntp_prod_0001..0005` production runs.)

### `load_protocol_from_manifest()`

```python
def load_protocol_from_manifest(
    manifest_path: str | os.PathLike,
    *,
    directory: Optional[str] = None,
    include_roles: Optional[List[str]] = None,
    include_stems: Optional[List[str]] = None,
    restart_files: Optional[Dict[str, str]] = None,
    skip_cross_stage_validation: Optional[bool] = None,
    recursive: bool = False,
    expand_env: bool = True,
    global_prmtop: Optional[str] = None,
    hmr_prmtop: Optional[str] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    strict: bool = False,
) -> SimulationProtocol
```

Load a **v1 flat** manifest (YAML / JSON / TOML / CSV) and build a protocol directly, bypassing the Simulation/Phase/Step model entirely. Relative paths resolve against `directory` (or the manifest's own directory). `skip_cross_stage_validation=None` defers to the manifest's `settings.strict_validation`.

```python
from ambermeta import load_protocol_from_manifest

protocol = load_protocol_from_manifest("legacy_protocol.yaml", directory="runs/")
```

> To load a **v2** manifest (or a v1 manifest into the new model), use `ambermeta.simulation.load_simulation` instead ([§1](#1-the-ambermetasimulation-model)).

### `load_manifest()`

```python
def load_manifest(manifest_path, expand_env: bool = True) -> Any
```

Parse a v1-shaped manifest file into normalized stage data (a list/dict) **without** building a protocol — format detected by extension, `${VAR}`/`$VAR` expanded unless `expand_env=False`, legacy keys normalized. Useful when you want the raw stage entries.

### `ProtocolBuilder`

A fluent builder for the same assembly, when you want to compose options programmatically. Every method returns `self`; `build()` is terminal.

| Method | Signature |
|---|---|
| `from_directory` | `(directory: str, recursive: bool = False)` |
| `from_manifest` | `(manifest_path: str, directory: Optional[str] = None, expand_env: bool = True)` |
| `with_grouping_rules` | `(rules: Dict[str, str])` — regex → role |
| `with_pattern_filter` | `(pattern: str)` — keep only matching files |
| `include_roles` | `(roles: List[str])` |
| `include_stems` | `(stems: List[str])` |
| `with_restart_files` | `(restart_files: Dict[str, str])` — by stage name or role |
| `auto_detect_restarts` | `(enable: bool = True)` |
| `skip_validation` | `(skip: bool = True)` |
| `with_stage_tolerance` | `(stage_name: str, expected_gap_ps: float, tolerance_ps: float = 0.1)` |
| `add_stage` | `(name, stage_role=None, prmtop=None, mdin=None, mdout=None, mdcrd=None, inpcrd=None, expected_gap_ps=None, gap_tolerance_ps=None)` |
| `build` | `() -> SimulationProtocol` |

```python
from ambermeta import ProtocolBuilder

protocol = (
    ProtocolBuilder()
    .from_directory("tests/data/amber/md_test_files", recursive=True)
    .with_grouping_rules({r"ntp_prod.*": "production"})
    .with_pattern_filter(r"ntp_prod_\d+")
    .auto_detect_restarts()
    .with_stage_tolerance("ntp_prod_0001", expected_gap_ps=0.0, tolerance_ps=0.1)
    .build()
)
```

---

## 4. `SimulationProtocol`

The container for an ordered list of stages (a "stage" is the pre-Phase/Step unit — one actual run, same concept as today's `Step`).

```python
@dataclass
class SimulationProtocol:
    stages: List[SimulationStage]
```

| Member | Signature | Returns |
|---|---|---|
| `validate` | `(cross_stage: bool = True, allow_unexpected_gaps: bool = False) -> None` | Runs per-stage + (optionally) cross-stage checks, attaching notes to each stage |
| `totals` | `() -> Dict[str, float]` | `{"steps": float, "time_ps": float}` summed across stages |
| `to_dict` | `() -> Dict[str, Any]` | `totals` + each stage's `to_dict()` — the full protocol summary |
| `to_methods_dict` | `() -> Dict[str, Any]` | Publication-oriented summary (see [§8](#8-export-structures)) |

```python
protocol = auto_discover("tests/data/amber/md_test_files", recursive=True)
print(protocol.totals())                      # {'steps': 25000000.0, 'time_ps': 100000.0}
for stage in protocol.stages:
    print(stage.name, stage.summary()["result"])
```

---

## 5. `SimulationStage`

One stage: its files (as parsed wrappers), its expectations, and its accumulated validation.

```python
@dataclass
class SimulationStage:
    name: str
    stage_role: Optional[str] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    observed_gap_ps: Optional[float] = None
    prmtop: Optional[PrmtopData] = None      # .details -> PrmtopMetadata
    inpcrd: Optional[InpcrdData] = None
    mdin:   Optional[MdinData]   = None
    mdout:  Optional[MdoutData]  = None
    mdcrd:  Optional[MdcrdData]  = None
    restart_path: Optional[str] = None
    validation: List[str] = field(default_factory=list)
    continuity: List[str] = field(default_factory=list)
    load_errors: List[FileLoadError] = field(default_factory=list)
```

`stage_role` holds the canonical short token (`"minimization" | "heating" | "equilibration" | "production" | ""`, from `ambermeta.roles.classify_role` — the same classifier the Phase/Step model and the GUI use) once inferred, not the free-text `stage_role` string `MdinMetadata` derives from the AMBER namelist (e.g. `"Production [NPT (isotropic)]"`); `summary()`'s `intent` prefers the canonical token when set.

| Member | Signature | Notes |
|---|---|---|
| `degraded` | `property -> bool` | `True` when any file failed to parse (`load_errors` non-empty) |
| `validate` | `() -> None` | Per-stage checks (atom counts, box, timing) → `validation` notes |
| `summary` | `() -> Dict[str, str]` | Keys: `intent`, `result`, `expected_gap_ps`, `observed_gap_ps`, `continuity`, `evidence` |
| `to_dict` | `() -> Dict[str, Any]` | Serialized stage (summary + degradation + file metadata) |

Reach a parsed field through the file wrapper's `.details`:

```python
stage = protocol.stages[2]   # ntp_prod_0001
if stage.mdout and stage.mdout.details:
    md = stage.mdout.details
    print(md.finished_properly, md.thermostat, md.stats.temp_stats.mean)
```

A real `summary()` (from the sample data's `ntp_prod_0001`, via `auto_discover(..., recursive=True, auto_detect_restarts=True)`):

```json
{
  "intent": "production",
  "result": "Completed",
  "expected_gap_ps": "",
  "observed_gap_ps": "",
  "continuity": "INFO: Cannot verify continuity between ntp_prod_0000 and ntp_prod_0001 (missing end time from ntp_prod_0000 (no mdcrd/mdout))",
  "evidence": "INFO: Part of sequence 'ntp_prod' (item 2 of 6); INFO: stage_role 'production' inferred from mdin file; INFO: Cannot verify continuity between ntp_prod_0000 and ntp_prod_0001 (missing end time from ntp_prod_0000 (no mdcrd/mdout))"
}
```

(`ntp_prod_0000` has only a `.rst` restart in the sample data — no `mdcrd`/`mdout` — so its end time can't be read; continuity resumes reporting normally from `ntp_prod_0002` onward, where the previous step's own `mdout` supplies an end time.)

---

## 6. Parsers

All five parsers share one shape: construct with a path, call `parse()`, read `.details`.

```python
from ambermeta.parsers import PrmtopParser   # or Mdin/Mdout/Mdcrd/Inpcrd

result = PrmtopParser("system.prmtop").parse()
result.filename       # str
result.warnings       # List[str]
result.details        # the metadata object (None if parsing failed hard)
```

| Parser | `parse()` returns | `.details` is |
|---|---|---|
| `PrmtopParser` | `PrmtopData` | `PrmtopMetadata` |
| `MdinParser` | `MdinData` | `MdinMetadata` |
| `MdoutParser` | `MdoutData` | `MdoutMetadata` |
| `MdcrdParser` | `MdcrdData` | `TrajectoryMetadata` |
| `InpcrdParser` | `InpcrdData` | `InpcrdMetadata` |

> NetCDF trajectories (`.nc`) and NetCDF restarts (`.ncrst`) require the `netcdf` extra. Without it those files parse to a wrapper with a warning rather than raising.

---

## 7. Parser metadata fields

These are the fields on `.details` — what `ambermeta info` prints and what your code reads. Each metadata class also carries `filename: str` and `warnings: List[str]`. This layer is unchanged from v1.

### `PrmtopMetadata` (`prmtop`)

| Field | Type | Meaning |
|---|---|---|
| `natom` / `n_atoms` | `int` | Atom count (`n_atoms` is a property alias) |
| `nres` | `int` | Residue count |
| `nbond` | `int` | Bond count |
| `version`, `title` | `str` | Topology version / title |
| `force_field_type` | `Optional[str]` | Detected force field |
| `force_field_features` | `List[str]` | e.g. `['CMAP Correction', 'Orthorhombic Box', 'Contains Ions (72)']` |
| `total_mass`, `total_charge` | `float` | System mass / net charge |
| `is_neutral` | `bool` | Net charge ≈ 0 |
| `box_dimensions` | `List[float]` | `[a, b, c]` (Å) |
| `box_angles` | `List[float]` | `[α, β, γ]` (deg) |
| `box_volume`, `density` | `float` | Å³ / g·cm⁻³ |
| `solvent_type` | `str` | e.g. `Explicit Solvent`, `Vacuum` |
| `simulation_category` | `str` | e.g. `Protein in Explicit Water` |
| `residue_composition` | `Dict[str, int]` | Residue-name → count (includes ions, water) |
| `num_solvent_molecules` | `int` | Solvent molecule count |
| `num_solute_residues` | `int` | Solute residue count |
| `hmr_active` | `Optional[bool]` | HMR detected from masses |
| `hmr_hydrogen_mass_range` | `Optional[Tuple[float, float]]` | (min, max) H mass |
| `hmr_hydrogen_mass_summary` | `Optional[str]` | e.g. `1.008-1.008 amu across 32188 H` |
| `hmr_detection_method` | `Optional[str]` | `atomic_number` or fallback |

### `MdinMetadata` (`mdin`)

| Field | Type | AMBER key |
|---|---|---|
| `title` | `str` | — |
| `simulation_type` | `str` | imin |
| `length_steps` | `int\|str` | `nstlim` (or `maxcyc`) |
| `dt` | `float\|str` | `dt` (ps) |
| `restart_flag` | `int\|str` | `irest` |
| `ensemble` | `str` | derived (NVE/NVT/NPT) |
| `stage_role` | `str` | inferred (free text, e.g. `"Production [NPT (isotropic)]"`) |
| `energy_freq` / `coord_freq` / `restart_freq` | `int\|str` | `ntpr` / `ntwx` / `ntwr` |
| `traj_format` | `str` | `ioutfm` |
| `cutoff` | `float\|str` | `cut` |
| `temp_control` | `str` | `ntt` |
| `target_temp` | `float\|str` | `temp0` |
| `press_control` | `str` | `ntp` |
| `pbc` | `str` | `ntb` |
| `constraints` | `str` | `ntc` |
| `implicit_solvent` | `str` | `igb` |
| `restraints_active` / `nmr_options` / `qmmm_active` | `bool` | `ntr` / `nmropt` / `ifqnt` |
| `uses_free_energy` / `uses_constant_pH` / `uses_gamd` / `uses_remd` / … | `bool` | feature flags |
| `cntrl_parameters` | `Dict[str, Any]` | raw `&cntrl` namelist |
| `additional_namelists` | `List[Dict]` | other namelists |
| `wt_schedules` | `List[WtScheduleEntry]` | `&wt` schedule rows |
| `restraint_definitions` | `List[str]` | restraint cards |

### `MdoutMetadata` (`mdout`)

| Field | Type | Meaning |
|---|---|---|
| `program`, `version` | `str` | e.g. `PMEMD`, `22` |
| `run_date`, `gpu_model` | `str` | from the header/footer |
| `natoms` / `n_atoms`, `nres` | `int` | system size |
| `box_type` | `str` | e.g. `RECTILINEAR` |
| `run_type` | `str` | MD / minimization |
| `dt`, `nstlim`, `cutoff` | `float`/`int`/`float` | run config |
| `thermostat`, `barostat` | `str` | e.g. `Langevin`, `Berendsen` |
| `target_temp` | `float` | K |
| `shake_active` | `bool` | SHAKE on |
| `stats` | `ThermoStats` | streaming thermodynamics (below) |
| `wall_time_seconds`, `ns_per_day` | `float` | performance |
| `finished_properly` | `bool` | completion |

**`ThermoStats`** — Welford-accumulated thermodynamics. Per-quantity stats are `StreamingStats` objects exposing `.mean`, `.stdev`, `.variance`, `.count`:

| Member | Meaning |
|---|---|
| `count`, `time_start`, `time_end` | frames; ps |
| `temp_stats`, `pressure_stats`, `density_stats`, `etot_stats`, `volume_stats` | `StreamingStats` per quantity |
| `duration_ns`, `avg_interval_ps`, `true_coverage_ns` | derived timing |
| `first_density` / `last_density` / `first_volume` / `last_volume` | endpoints |
| `sum_bond` / `sum_angle` / `sum_dihed` / `sum_vdw` / `sum_elec` | energy-term sums |

```python
md = MdoutParser("tests/data/amber/md_test_files/ntp_prod_0001.mdout").parse().details
print(md.stats.count)                  # 200
print(md.stats.temp_stats.mean)        # 300.43200000000013
print(md.stats.temp_stats.stdev)       # 1.2504190252445306
print(md.stats.density_stats.mean)     # 1.0369550000000003
```

### `TrajectoryMetadata` (`mdcrd`)

| Field | Type | Meaning |
|---|---|---|
| `file_format` | `str` | `NetCDF` or `ASCII` |
| `n_atoms`, `n_frames` | `int` | size |
| `has_time`, `time_start`, `time_end`, `avg_dt`, `total_duration` | timing |
| `has_box`, `box_type` | box presence/geometry |
| `volume_stats` | `Optional[Tuple]` | (min, max, avg) volume |
| `has_coordinates` / `has_velocities` / `has_forces` | `bool` | contents |
| `is_remd`, `remd_types`, `remd_temp_stats` | replica-exchange info |

### `InpcrdMetadata` (`inpcrd` / restart)

| Field | Type | Meaning |
|---|---|---|
| `file_format` | `str` | `Formatted ASCII` or `NetCDF` |
| `natoms` / `n_atoms`, `nres` | `int` | size |
| `time` | `Optional[float]` | simulation time (ps) — drives continuity |
| `has_coordinates` / `has_velocities` / `has_forces` | `bool` | contents |
| `has_box`, `box_dimensions`, `box_angles`, `box_volume` | box info |
| `program`, `program_version`, `conventions` | provenance |

```python
r = InpcrdParser("tests/data/amber/md_test_files/ntp_prod_0001.rst").parse().details
r.file_format, r.natoms, r.time
# ('NetCDF', 64528, 20920.00000242704)
r.has_box, r.box_dimensions
# (True, [91.78526594551442, 70.98306005877042, 75.81276343991902])
```

---

## 8. Export structures

### `to_dict()`

`SimulationProtocol.to_dict()` → `{"totals": {...}, "stages": [stage.to_dict(), ...]}` — the complete record, suitable for `json.dump`. This is what `plan --summary-path` writes.

### `to_methods_dict()`

A publication-oriented view: reproducibility-critical metadata, energies and bulk arrays dropped. The real top-level shape is `{"stage_sequence": [...], "stages": [...]}`. A production stage entry (real output, `ntp_prod_0001` from the sample data):

```json
{
  "name": "ntp_prod_0001",
  "role": "production",
  "software": [
    {"source": "mdout", "program": "PMEMD", "version": "22"},
    {"source": "inpcrd", "program": "pmemd", "version": "Version 22"}
  ],
  "md_engine": {
    "ensemble": "NPT (isotropic)",
    "thermostat": "Langevin Dynamics",
    "barostat": "Berendsen (Isotropic)",
    "cutoff": 9.0,
    "constraints": "H-bonds",
    "pbc": "PBC / Constant Pressure",
    "timestep_ps": 0.004,
    "run_length_steps": 5000000,
    "cntrl_parameters": { "ntx": 5, "irest": 1, "nstlim": 5000000, "dt": 0.004, "ntt": 3, "ntp": 1, "ntc": 2, "ntb": 2, "cut": 9.0, "_namelist": "cntrl" },
    "shake_active": true,
    "run_length_ps": 20000.0
  },
  "restraints": {"active": false},
  "system": {
    "atom_counts": {"inpcrd": 64528, "mdout": 64528},
    "box": {"type": "RECTILINEAR", "dimensions": [91.79, 70.98, 75.81], "angles": [90.0, 90.0, 90.0]},
    "composition": {
      "hmr_active": true,
      "hmr_inferred_from_timestep": true,
      "average_density": 1.037,
      "density_std": 0.00124,
      "density": 1.037,
      "first_density": 1.0348,
      "final_density": 1.0374
    }
  },
  "trajectory_output": {"coord_write_interval_steps": 25000, "traj_format": "NetCDF"}
}
```

### Statistics CSV

`plan --stats-csv` writes one row per stage with this exact header:

```text
stage_name,stage_role,time_start_ps,time_end_ps,duration_ns,frame_count,temp_avg,temp_std,pressure_avg,pressure_std,density_avg,density_std,etot_avg,etot_std
```

```python
import json
from ambermeta import auto_discover

protocol = auto_discover("tests/data/amber/md_test_files", recursive=True)
with open("protocol.json", "w") as f:
    json.dump(protocol.to_dict(), f, indent=2)
with open("methods.json", "w") as f:
    json.dump(protocol.to_methods_dict(), f, indent=2)
```

---

## 9. Errors

```python
class AmberMetaError(Exception): ...        # base for clean, expected failures
```

`AmberMetaError` is raised for failures the CLI turns into a one-line message + exit `1` (no traceback). Catch it in your own tooling for the same effect.

```python
@dataclass
class FileLoadError:
    kind: str          # "prmtop" | "mdin" | "mdout" | "mdcrd" | "inpcrd"
    path: str
    error_type: str    # "missing" | "permission" | "decode" | "malformed"
    message: str
    def to_dict(self) -> dict: ...
```

A single file's failure, captured as data (not raised) under the default fault-tolerant mode. It accumulates on `SimulationStage.load_errors` and drives the `degraded` flag.

```python
def classify_exception(exc: BaseException) -> str
```

Maps an exception to an `error_type`: `FileNotFoundError`→`"missing"`, `PermissionError`→`"permission"`, `UnicodeDecodeError`→`"decode"`, otherwise `"malformed"`. Lives in `ambermeta.errors`, not top-level `ambermeta`.

---

## 10. Worked examples

**Discover a directory into a v2 manifest, then validate it (the new model, end to end):**

```python
import os
from ambermeta.gui.api.core_bridge import discover_draft, validate_simulation
from ambermeta.simulation import write_simulation

base = os.path.abspath("tests/data/amber/md_test_files")
draft = discover_draft(base)
sim = draft["simulation"]

write_simulation(sim, "simulation.json", "json")

report = validate_simulation(sim, {}, base)
if not report["ok"]:
    for issue in report["stage_issues"]:
        if not issue["ok"]:
            print(issue["name"], issue["errors"])
```

**Audit completion and temperature stability across a project (the retained engine):**

```python
from ambermeta import auto_discover

protocol = auto_discover("tests/data/amber/md_test_files", recursive=True, auto_detect_restarts=True)
for stage in protocol.stages:
    md = stage.mdout.details if stage.mdout else None
    if not md:
        continue
    flag = "OK" if md.finished_properly else "INCOMPLETE"
    temp = md.stats.temp_stats
    print(f"{stage.name:16} {flag:11} T = {temp.mean:6.2f} ± {temp.stdev:.2f} K")
```

**Process many project directories into per-project summaries:**

```python
import json
from pathlib import Path
from ambermeta import auto_discover, AmberMetaError

for d in Path("all_projects").iterdir():
    if not d.is_dir():
        continue
    try:
        protocol = auto_discover(str(d), recursive=True, auto_detect_restarts=True)
        out = {"project": d.name, "stages": len(protocol.stages), **protocol.totals()}
        Path(f"{d.name}.json").write_text(json.dumps(out, indent=2))
    except AmberMetaError as e:
        print(f"{d.name}: {e}")
```

---

## See also

- [Architecture](architecture.md) — how these pieces fit together, and the v1→v2 migration mechanics
- [CLI reference](cli.md) — the command-line surface over this API
- [Manifest schema](manifest.md) — the v2 file format `load_simulation`/`write_simulation` read and write, and the v1 auto-migration table
- [GUI](gui.md) — the HTTP API that wraps `core_bridge`
- [Tutorials](tutorials.md) — task-oriented walkthroughs
