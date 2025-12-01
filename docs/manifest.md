# Manifest schema

AmberMeta supports manifest-driven planning for simulation protocols via YAML or
JSON files. Manifests feed `load_protocol_from_manifest`, `auto_discover`, and
the `ambermeta plan` CLI to assemble ordered `SimulationStage` objects and run
per-stage and cross-stage validation.

## Top-level structure

- **Accepted types:** the manifest must be either a list of stage dictionaries
  or a mapping whose keys are stage names and whose values are dictionaries.
  Mixed or other types raise an error.
- **Stage dictionaries:** each stage entry is a mapping of metadata and file
  pointers. When the manifest is a mapping, the stage name key is copied into
  the stage entry when no explicit `name` is present.
- **Relative paths:** any relative file paths are resolved against the manifest
  directory when using `load_protocol_from_manifest` or the optional `directory`
  argument passed to `auto_discover`. The `ambermeta plan --manifest` command
  forwards its positional `directory` argument for this purpose.

## Required and optional keys per stage

- **Required**
  - `name`: unique identifier used for ordering and restart lookups.
  - `stage_role`: high-level intent (e.g., `minimization`, `equilibration`,
    `production`). If omitted, the role may be inferred from parsed `mdin`
    metadata when available; otherwise intent is reported as unknown.
- **Files (may be under `files` or as top-level keys inside the stage):**
  - `prmtop`, `mdin`, `mdout`, `inpcrd`, `mdcrd`. Only these keys are consumed;
    others are ignored. At least one recognized file is recommended so the stage
    can be parsed and validated.
- **Optional metadata**
  - `notes`: string or list of strings that become validation notes.
  - `gaps` / `gap`: describes expected discontinuities before the stage. Accepts
    a mapping with `expected`/`expected_ps` and optional `tolerance`/
    `tolerance_ps`, plus free-form `notes` (string or list). A bare number sets
    `expected_gap_ps`, while a string or list is treated as additional notes.
  - **Restart sources:** providing `inpcrd` marks the restart used for the
    stage. Programmatic callers may also pass a `restart_files` mapping to
    `auto_discover`/`load_protocol_from_manifest` to inject restarts by stage
    `name` or `stage_role` when absent from the manifest.

## Behavior in consumers

- **`load_protocol_from_manifest`** loads YAML (requires the optional `pyyaml`
  extra) or JSON, resolves relative paths, and feeds the normalized manifest to
  `auto_discover`.
- **`auto_discover`** parses each referenced file into a `SimulationStage`,
  attaches restart paths, applies gap expectations, and runs validation. When
  `manifest` is `None`, it discovers files on disk instead.
- **`ambermeta plan`** uses the manifest path when provided; otherwise it
  prompts for the same stage keys interactively. `--skip-cross-stage-validation`
  disables continuity checks (useful for non-contiguous protocols).

## Example manifests

### YAML list with full field set and continuity edge cases

```yaml
# protocol.yaml
- name: minim
  stage_role: minimization
  prmtop: systems/complex.prmtop
  inpcrd: systems/complex.inpcrd
  mdin: mdin/minim.in
  mdout: logs/minim.out
  notes: Single-point minimization; no trajectory expected.

- name: equil1
  stage_role: equilibration
  files:
    mdin: mdin/equil1.mdin
    mdout: logs/equil1.mdout
    mdcrd: traj/equil1.mdcrd
  gaps:
    expected_ps: 0
    tolerance_ps: 0.5
    notes:
      - Uses minim restart implicitly
      - Box data only in mdcrd

- name: prod1
  stage_role: production
  mdin: mdin/prod1.in
  mdout: logs/prod1.out
  mdcrd: traj/prod1.nc
  inpcrd: restarts/prod0.rst7  # explicit restart source

- name: prod2
  stage_role: production
  files:
    mdin: mdin/prod2.in
    mdout: logs/prod2.out
  gaps: 250  # non-contiguous: expect ~250 ps jump before this stage
  notes:
    - Trajectory intentionally omitted
```

- `equil1` omits `prmtop`/`inpcrd` but still participates; validation will note
  missing atom counts when needed.
- `prod2` demonstrates a non-contiguous stage with an expected gap.

### JSON mapping keyed by stage name with restart chaining

```json
// protocol.json
{
  "equil1": {
    "stage_role": "equilibration",
    "prmtop": "systems/complex.prmtop",
    "mdin": "mdin/equil1.in",
    "mdout": "logs/equil1.out"
  },
  "equil2": {
    "stage_role": "equilibration",
    "mdin": "mdin/equil2.in",
    "mdout": "logs/equil2.out",
    "inpcrd": "restarts/equil1.rst"  
  },
  "prod": {
    "stage_role": "production",
    "files": {
      "mdin": "mdin/prod.in",
      "mdout": "logs/prod.out",
      "mdcrd": "traj/prod.nc"
    },
    "gaps": {
      "expected": 0,
      "tolerance": 0.1
    }
  }
}
```

When used with `auto_discover(..., restart_files={"production": "restarts/prod.rst"})`,
`prod` will inherit the restart path even if `inpcrd` is absent from the entry.
