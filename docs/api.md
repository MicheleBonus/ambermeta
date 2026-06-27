# Python API reference

**AmberMeta is a library, not just a CLI.** Everything `ambermeta` does on the command line is one import away: parse a file, reconstruct a protocol from a directory or manifest, validate continuity, and export reproducibility artifacts.

The supported import surface (everything re-exported from `ambermeta/__init__.py`):

```python
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
> result.warnings              # ['...']  (on the wrapper, not .details)
> ```
>
> Field names are AMBER-flavored and differ from intuition: `hmr_active` (not `is_hmr`), `residue_composition` (not `residue_counts`), `temp_control`/`press_control`/`stage_role` on `mdin`. The exact field list per file type is in [§6](#6-parser-metadata-fields).

---

## 1. Discovery & assembly

These build a `SimulationProtocol` from files or a manifest. This is the top of the API — most programs call one of these and never touch a parser directly.

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

Discover and parse simulation files into an ordered protocol. With `manifest` provided, it parses the listed stages; with `manifest=None`, it discovers files on disk (`recursive=True` to descend). `strict=True` makes the first unreadable file a hard `AmberMetaError`; the default skips it and records a `FileLoadError`.

```python
from ambermeta import auto_discover

protocol = auto_discover("runs/", recursive=True, auto_detect_restarts=True)
print(len(protocol.stages), protocol.totals())
# 7 {'steps': 25000000.0, 'time_ps': 100000.0}
```

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

Load a manifest (YAML / JSON / TOML / CSV) and build a protocol. Relative paths resolve against `directory` (or the manifest's own directory). `skip_cross_stage_validation=None` defers to the manifest's `settings.strict_validation`.

```python
from ambermeta import load_protocol_from_manifest

protocol = load_protocol_from_manifest("protocol.yaml", directory="runs/")
```

### `load_manifest()`

```python
def load_manifest(manifest_path, expand_env: bool = True) -> Any
```

Parse a manifest file into normalized stage data (a list/dict) **without** building a protocol — format detected by extension, `${VAR}`/`$VAR` expanded unless `expand_env=False`, legacy keys normalized. Useful when you want the raw stage entries.

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
    .from_directory("runs/", recursive=True)
    .with_grouping_rules({r"min.*": "minimization", r"prod.*": "production"})
    .with_pattern_filter(r"prod_\d+")
    .auto_detect_restarts()
    .with_stage_tolerance("prod_001", expected_gap_ps=0.0, tolerance_ps=0.1)
    .build()
)
```

---

## 2. `SimulationProtocol`

The container for an ordered list of stages.

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
| `to_methods_dict` | `() -> Dict[str, Any]` | Publication-oriented summary (see [§7](#7-export-structures)) |

```python
protocol = auto_discover("runs/", recursive=True)
print(protocol.totals())                      # {'steps': 25000000.0, 'time_ps': 100000.0}
for stage in protocol.stages:
    print(stage.name, stage.summary()["result"])
```

---

## 3. `SimulationStage`

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

| Member | Signature | Notes |
|---|---|---|
| `degraded` | `property -> bool` | `True` when any file failed to parse (`load_errors` non-empty) |
| `validate` | `() -> None` | Per-stage checks (atom counts, box, timing) → `validation` notes |
| `summary` | `() -> Dict[str, str]` | Keys: `intent`, `result`, `expected_gap_ps`, `observed_gap_ps`, `continuity`, `evidence` |
| `to_dict` | `() -> Dict[str, Any]` | Serialized stage (summary + degradation + file metadata) |

Reach a parsed field through the file wrapper's `.details`:

```python
stage = protocol.stages[2]
if stage.mdout and stage.mdout.details:
    md = stage.mdout.details
    print(md.finished_properly, md.thermostat, md.stats.temp_stats.mean)
```

A real `summary()` (from the sample data's `ntp_prod_0001`):

```json
{
  "intent": "Production [NPT (isotropic)]",
  "result": "Completed",
  "expected_gap_ps": "",
  "observed_gap_ps": "",
  "continuity": "INFO: Cannot verify continuity between ntp_prod_0000 and ntp_prod_0001 (missing mdcrd from ntp_prod_0000)",
  "evidence": "INFO: Part of sequence 'ntp_prod' (item 2 of 6); INFO: stage_role inferred from mdin file; ..."
}
```

---

## 4. Parsers

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

## 5. Utility functions

Lower-level building blocks used by the assembly layer; useful directly for custom tooling.

```python
detect_numeric_sequences(filenames: List[str]) -> Dict[str, List[str]]
```
Group filenames into numbered families. Recognizes `name_001`, `name.001`, `name-001`, and `name001`.
```python
detect_numeric_sequences(["prod_001.out", "prod_002.out", "equil.out"])
# {'prod_': ['prod_001.out', 'prod_002.out']}
```

```python
smart_group_files(directory: str, pattern: Optional[str] = None,
                  recursive: bool = False) -> Dict[str, Dict[str, str]]
```
Bucket files by stem into `STAGE_FILE_KINDS` slots, with sequence metadata. Returns `{stem: {kind: path, ...}}`.

```python
auto_detect_restart_chain(stages: List[SimulationStage], directory: str,
                          recursive: bool = False) -> Dict[str, str]
```
Infer the restart chain (atom-count match + time continuity + sequence order). Returns `{stage_name: restart_path}`.

```python
infer_stage_role_from_content(mdin_data: Optional[MdinData] = None,
                              mdout_data: Optional[MdoutData] = None) -> Optional[str]
```
Infer a role (`minimization` / `heating` / `equilibration` / `production`) from parsed content. Returns `None` if undeterminable.

> Module constant: `ambermeta.protocol.HMR_TIMESTEP_THRESHOLD_PS = 0.003` — a timestep ≥ 3 fs is taken as evidence of hydrogen-mass repartitioning.

---

## 6. Parser metadata fields

These are the fields on `.details` — what `ambermeta info` prints and what your code reads. Each metadata class also carries `filename: str` and `warnings: List[str]`.

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
| `stage_role` | `str` | inferred |
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
md = MdoutParser("prod.mdout").parse().details
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

---

## 7. Export structures

### `to_dict()`

`SimulationProtocol.to_dict()` → `{"totals": {...}, "stages": [stage.to_dict(), ...]}` — the complete record, suitable for `json.dump`. This is what `plan --summary-path` writes.

### `to_methods_dict()`

A publication-oriented view: reproducibility-critical metadata, energies and bulk arrays dropped. The real top-level shape is `{"stage_sequence": [...], "stages": [...]}`. A production stage entry (verbatim from the sample data):

```json
{
  "name": "ntp_prod_0001",
  "role": "Production [NPT (isotropic)]",
  "software": [
    {"source": "mdout", "program": "PMEMD", "version": "22"}
  ],
  "md_engine": {
    "ensemble": "NPT (isotropic)",
    "thermostat": "Langevin Dynamics",
    "barostat": "Berendsen (Isotropic)",
    "cutoff": 9.0,
    "constraints": "H-bonds",
    "timestep_ps": 0.004,
    "run_length_steps": 5000000,
    "run_length_ps": 20000.0,
    "shake_active": true
  },
  "restraints": {"active": false},
  "system": {
    "atom_counts": {"inpcrd": 64528, "mdout": 64528},
    "box": {"type": "RECTILINEAR", "dimensions": [91.79, 70.98, 75.81], "angles": [90.0, 90.0, 90.0]},
    "composition": {
      "hmr_active": true,
      "hmr_inferred_from_timestep": true,
      "average_density": 1.037,
      "density_std": 0.00124
    }
  },
  "trajectory_output": { ... }
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

protocol = auto_discover("runs/", recursive=True)
with open("protocol.json", "w") as f:
    json.dump(protocol.to_dict(), f, indent=2)
with open("methods.json", "w") as f:
    json.dump(protocol.to_methods_dict(), f, indent=2)
```

---

## 8. Errors

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
Maps an exception to an `error_type`: `FileNotFoundError`→`"missing"`, `PermissionError`→`"permission"`, `UnicodeDecodeError`→`"decode"`, otherwise `"malformed"`.

---

## 9. Worked examples

**Audit completion and temperature stability across a project:**

```python
from ambermeta import auto_discover

protocol = auto_discover("runs/", recursive=True, auto_detect_restarts=True)
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

- [Architecture](architecture.md) — how these pieces fit together
- [CLI reference](cli.md) — the command-line surface over this API
- [Manifest schema](manifest.md) — the file format `load_*` consumes
- [Tutorials](tutorials.md) — task-oriented walkthroughs
