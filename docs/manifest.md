# Manifest schema

**A manifest is the durable, hand-editable description of a protocol** — an ordered list of stages, each pointing at its files, plus optional global topology and validation settings. AmberMeta is *tolerant* about what it reads (four formats, several shapes, legacy key aliases) and *canonical* about what it writes (one deterministic form). The CLI's `init --auto`/`plan` and the GUI's **Save** produce byte-identical output.

Manifests feed `load_manifest`, `load_protocol_from_manifest`, `auto_discover`, and `ambermeta plan`. See [architecture §4](architecture.md#4-the-manifest-contract) for the design rationale.

---

## 1. Formats

Format is detected from the file extension.

| Format | Extension | Requires |
|---|---|---|
| YAML | `.yaml`, `.yml` | `pyyaml` (the `yaml` extra) |
| JSON | `.json` | stdlib — always available |
| TOML | `.toml` | stdlib `tomllib` (Python 3.11+) or `tomli` (the `toml` extra) |
| CSV | `.csv` | stdlib — always available |

---

## 2. Top-level structure

A manifest is **either** a list of stage dictionaries **or** a mapping of stage-name → stage dictionary. Any other shape is an error.

```yaml
# list form (recommended)
global_prmtop: systems/complex.prmtop
hmr_prmtop: systems/complex_hmr.prmtop
stages:
  - name: minimize
    stage_role: minimization
    mdin: mdin/min.in
    mdout: logs/min.out
```

```yaml
# mapping form — the key becomes the stage name
minimize:
  stage_role: minimization
  mdin: mdin/min.in
  mdout: logs/min.out
```

| Top-level key | Purpose |
|---|---|
| `global_prmtop` | Shared topology for stages that don't set their own |
| `hmr_prmtop` | HMR topology (used when a stage's timestep warrants it) |
| `prmtop` | Legacy alias for `global_prmtop`, still accepted on read |
| `stages` | The stage list (list form) |
| `settings` | Validation behavior (see §5) |
| `stage_role_rules` | Name-based role inference (see §5) |

**Relative paths** resolve against the manifest's directory (or the `directory` argument to `load_protocol_from_manifest`/`auto_discover`; `ambermeta plan` forwards its positional directory).

---

## 3. Stage keys

A stage recognizes exactly five file slots — `STAGE_FILE_KINDS = (prmtop, mdin, mdout, mdcrd, inpcrd)` — given either under a `files` mapping or as top-level keys on the stage. Unrecognized keys are ignored.

| Key | Required | Meaning |
|---|---|---|
| `name` | **yes** | Unique identifier; used for ordering and restart lookup |
| `stage_role` | no | `minimization` / `heating` / `equilibration` / `production`; inferred from content/path if omitted (always with an `INFO` note) |
| `prmtop`, `mdin`, `mdout`, `mdcrd`, `inpcrd` | no | File paths (provide at least one parseable file) |
| `notes` | no | String or list of strings → validation notes |
| `gaps` / `gap` | no | Expected discontinuity before this stage (see §4) |
| `expected_gap_ps` | no | Flat alternative to nested `gaps` |
| `gap_tolerance_ps` | no | Flat tolerance for gap validation |

Providing `inpcrd` marks the restart used for the stage. Programmatic callers may also inject restarts via the `restart_files` argument (keyed by stage `name` or `stage_role`).

---

## 4. Gap configuration

`gaps` (or `gap`) describes an expected time discontinuity before a stage. It accepts several shapes:

```yaml
# full form
gaps:
  expected: 100.0       # or expected_ps
  tolerance: 0.5        # or tolerance_ps
  notes:
    - "Restart from backup checkpoint"

# shorthand: just the expected gap in ps
gaps: 100.0

# notes only
gaps: "Manual restart from backup"
```

Validation behavior: within tolerance → an `INFO` note confirming the gap; outside tolerance → a `WARNING`. With no expectation set, sub-tolerance gaps are normalized to 0 and a larger gap produces a note to verify continuity.

---

## 5. `settings` and `stage_role_rules`

### `settings`

| Key | Default | Effect |
|---|---|---|
| `strict_validation` | `true` | `true` runs cross-stage continuity checks; `false` skips them (≡ `skip_cross_stage_validation`) |
| `allow_gaps` | `false` | When `true` (and validation is on), unconfigured positive gaps are recorded as info, not warnings |

The CLI flag `--skip-cross-stage-validation` overrides `settings.strict_validation` unconditionally.

### `stage_role_rules`

Name-based inference applied when a stage omits `stage_role`. Two accepted forms:

```yaml
# list form (evaluated in order)
stage_role_rules:
  - pattern: "^min"
    role: minimization
  - pattern: "^heat"
    role: heating

# mapping form
stage_role_rules:
  "^min": minimization
  "^heat": heating
```

Invalid regexes are treated as literal strings.

---

## 6. Environment-variable expansion

File paths support `${VAR}` and `$VAR`, expanded at load time (undefined variables are left unchanged). Disable with `expand_env=False` (API) or `--no-expand-env` (CLI).

```yaml
- name: production
  prmtop: ${PROJECT_ROOT}/systems/complex.prmtop
  mdin:   $HOME/templates/prod.in
  mdout:  ${OUTPUT_DIR}/prod.out
```

---

## 7. Format examples

### YAML

```yaml
global_prmtop: systems/complex.prmtop
hmr_prmtop: systems/complex_hmr.prmtop
stages:
  - name: minimize
    stage_role: minimization
    inpcrd: systems/complex.inpcrd
    mdin: mdin/min.in
    mdout: logs/min.out
    notes: Single-point minimization; no trajectory expected.

  - name: equilibrate
    stage_role: equilibration
    files:
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
```

### JSON

```json
[
  { "name": "minimize", "stage_role": "minimization",
    "prmtop": "systems/complex.prmtop", "mdin": "mdin/min.in", "mdout": "logs/min.out" },
  { "name": "production", "stage_role": "production",
    "files": { "mdin": "mdin/prod.in", "mdout": "logs/prod.out", "mdcrd": "traj/prod.nc" },
    "gaps": { "expected": 0, "tolerance": 0.1 } }
]
```

### TOML

```toml
global_prmtop = "systems/complex.prmtop"
hmr_prmtop = "systems/complex_hmr.prmtop"

[[stages]]
name = "minimize"
stage_role = "minimization"
mdin = "mdin/min.in"
mdout = "logs/min.out"

[[stages]]
name = "production"
stage_role = "production"
mdin = "mdin/prod.in"
mdout = "logs/prod.out"
mdcrd = "traj/prod.nc"
inpcrd = "restarts/equil.rst7"
expected_gap_ps = 0.0
gap_tolerance_ps = 0.1
```

### CSV

The canonical header is `CSV_COLUMNS`:

```csv
name,stage_role,prmtop,mdin,mdout,mdcrd,inpcrd,expected_gap_ps,gap_tolerance_ps,notes
minimize,minimization,system.prmtop,min.in,min.out,,,,,"Initial minimization"
equilibrate,equilibration,system.prmtop,equil.in,equil.out,equil.nc,heat.rst7,0,0.1,"NVT equilibration"
production,production,system.prmtop,prod.in,prod.out,prod.nc,equil.rst7,0,0.1,"Main production run"
```

CSV notes: column order is flexible (driven by the header); empty cells are missing values; the notes field accepts semicolon-separated entries; the reader also accepts legacy column names `stage` (→ `name`) and `role` (→ `stage_role`).

> ⚠️ CSV cannot represent a separate `hmr_prmtop` alongside `global_prmtop`. Saving an HMR-bearing protocol to CSV emits a warning — use YAML/JSON/TOML when HMR topology matters.

---

## 8. Consumers

| Entry point | Behavior |
|---|---|
| `load_manifest(path, expand_env=True)` | Parse + normalize stage entries; returns raw data (no protocol) |
| `load_protocol_from_manifest(path, directory=…)` | Parse, build, validate → `SimulationProtocol` |
| `auto_discover(directory, manifest=…)` | With a manifest, parse the listed stages; with `manifest=None`, discover on disk |
| `ambermeta plan --manifest …` | The CLI front end over `load_protocol_from_manifest` |

### Programmatic restart injection

```python
from ambermeta import auto_discover

protocol = auto_discover(
    "runs/",
    manifest=manifest_data,
    restart_files={"prod1": "runs/equil.rst7"},   # by stage name or role
)
```

### Builder with per-stage tolerances

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

## 9. Authoring a manifest without writing one

```bash
ambermeta init runs/ --auto --output manifest.yaml --force   # bootstrap from a directory
ambermeta gui runs/                                          # build it in the browser
```

Both discover files, group them into stages, infer roles, and write the canonical manifest in YAML / JSON / TOML / CSV. See the [GUI guide](gui.md) and [CLI reference](cli.md).

---

## 10. Errors

| Error | Cause | Fix |
|---|---|---|
| `FileNotFoundError` | Manifest (or a referenced file) missing | Check the path / the stage's file paths |
| `ImportError` (YAML) | `pyyaml` not installed | `pip install -e ".[yaml]"` |
| `ImportError` (TOML) | `tomli` missing on Python < 3.11 | `pip install -e ".[toml]"` |
| `TypeError` | Manifest is neither list nor mapping of stages | Use one of the two top-level shapes (§2) |
| `ValueError` | A stage has no `name` | Add `name` to each stage |

Validation produces **warnings**, not errors, for: missing files that block a check, atom-count mismatches, timing/box inconsistencies, and unexpected inter-stage gaps.
