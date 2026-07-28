# Manifest schema

**A manifest is the durable, hand-editable description of a Simulation** — a topology pool, a starting
structure, an ordered set of Phases, and the Steps inside them, each pointing at its own files and its own
input-coordinate source. This is the **v2** format (`version: 2`), the shared CLI↔GUI contract for the
[Simulation → Phase → Step](architecture.md#2-the-model-simulation--phase--step) model.

AmberMeta is *tolerant* about what it reads and *canonical* about what it writes. It still opens the old
**v1** flat `stages:` manifests — see [§9](#9-legacy-v1-format-still-read-auto-migrated) — auto-migrating
them to a `Simulation` in memory; saving or exporting always writes v2. `ambermeta discover --write`,
`ambermeta export`, `ambermeta init --v2`, and the GUI's **Save** all write through the same
`write_simulation` function, so their output is byte-identical for the same document.

Manifests are read by `load_simulation` (v2 model) and, for the retained flat engine, by `load_manifest` /
`load_protocol_from_manifest` / `auto_discover` (see [api.md](api.md)). See
[architecture §5](architecture.md#5-manifest-format-v2-and-the-tolerant-auto-migrating-reader) for the
tolerant-reader/auto-migration design rationale.

---

## 1. Formats

Format is detected from the file extension.

| Format | Extension | Requires |
|---|---|---|
| YAML | `.yaml`, `.yml` | `pyyaml` (the `yaml` extra) |
| JSON | `.json` | stdlib — always available |
| TOML | `.toml` | stdlib `tomllib` (Python 3.11+) or `tomli` (the `toml` extra) |
| CSV | `.csv` | stdlib — always available |

**Reading** is format-agnostic for all four: the loader parses any of them to a plain Python
dict/list *before* it decides whether the result is v1 or v2 shaped. A hand-written v2-shaped `.toml` file
(nested `[simulation]`/`[[phases]]`/`[[steps]]` tables) loads correctly as a `Simulation`. CSV is the one
exception in practice — its rows are inherently flat, so a CSV manifest can only ever express the v1 stage
list, never the nested v2 structure.

**Writing** is asymmetric by design:

| Writer | Formats |
|---|---|
| `write_simulation` (v2 canonical — `discover --write`, `export --to v2`, GUI Save) | **JSON, YAML only** |
| `write_manifest` (legacy flat — `export --to legacy`) | JSON, YAML, **TOML, CSV** |

Asking `write_simulation` for `toml` or `csv` raises `ValueError: v2 write supports json/yaml only, got: <fmt>`.
If you need a TOML or CSV artifact for a downstream tool, run `ambermeta export sim.yaml --to legacy -o out.toml`
(or `.csv`) — this flattens the Simulation back to the v1 stage-list shape first (see
[§8](#8-export---to-legacy-flattening-back-to-v1) for exactly what survives that trip).

---

## 2. Top-level structure

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
    topology: top_wt
    input_coords: { source: starting_structure }
    mdin: min.in
    mdout: min.out
  - id: st_prod_001
    name: prod_001
    phase: ph_prod
    order: 0
    topology: top_wt_hmr
    input_coords: { source: step, ref: st_min }
    mdin: prod_001.in
    mdout: prod_001.out
    mdcrd: prod_001.nc
    gaps: { expected: null, tolerance: null }
```

| Top-level key | Type | Meaning |
|---|---|---|
| `version` | int | `2` for the current format. `payload_to_simulation` treats anything with a `phases` or `simulation` key as v2 even if `version` is absent, but always write `2` explicitly. |
| `simulation` | mapping | The topology pool + the starting structure (§3). |
| `phases` | list | Ordered Phase records (§4). |
| `steps` | list | Ordered Step records, each tagged with the `phase` id it belongs to (§5). |

**Relative paths** (topology paths, `starting_structure`, `mdin`/`mdout`/`mdcrd`, an explicit
`input_coords.path`) resolve against the manifest's directory — the same convention as v1.

---

## 3. `simulation`: the topology pool and starting structure

```yaml
simulation:
  topologies:
    - id: top_wt
      path: wt.prmtop
      kind: normal
    - id: top_wt_hmr
      path: wt_hmr.prmtop
      kind: hmr
  starting_structure: wt.inpcrd
```

| Field | Required | Meaning |
|---|---|---|
| `topologies` | no (may be empty) | The pool. Every prmtop the Simulation uses lives here **once**; Steps bind to one by `id` instead of each stage carrying its own copy. |
| `starting_structure` | no | The initial coordinate file that feeds the **first** Step whose `input_coords.source` is `starting_structure`. |

Each `topologies[]` entry is a `Topology`:

| Field | Required | Meaning |
|---|---|---|
| `id` | **yes** | Unique identifier; referenced by `steps[].topology`. Hand-written manifests typically use a descriptive slug (`top_wt`); `discover` generates one from the filename (`top_CH3L1_HUMAN_6NAG`) or, on migration from v1, `top_0`, `top_1`, … |
| `path` | **yes** | Path to the prmtop file. |
| `kind` | no (default `"normal"`) | `"normal"` or `"hmr"` (hydrogen-mass-repartitioned). Auto-detected from the topology's hydrogen masses when discovered from disk; always overridable by hand. |

A pool may hold any number of topologies — including more than one `normal`/`hmr` pair for genuinely
distinct chemical systems, which the old two-bucket `global_prmtop`/`hmr_prmtop` scheme could not represent.

---

## 4. `phases[]`

```yaml
phases:
  - { id: ph_min,  name: Minimization, role: minimization, order: 0 }
  - { id: ph_prod, name: Production,    role: production,   order: 1 }
```

| Field | Required | Meaning |
|---|---|---|
| `id` | **yes** | Unique identifier; referenced by `steps[].phase`. |
| `name` | no | Display name. |
| `role` | no (default `""`) | One of the [canonical role tokens](#7-canonical-role-tokens), or empty. |
| `order` | no | Sort key among phases. `payload_to_simulation` sorts phases by `order` on read; if omitted it defaults to `0`, so give every phase an explicit, distinct `order` in a multi-phase manifest. |

A Phase is a grouping/convenience level — it carries no files or topology of its own. (The GUI can cascade
"set this topology for every Step in me" onto a Phase's Steps as a bulk action, but that only ever writes
`topology` onto the Steps; the Phase record itself stores nothing extra.)

---

## 5. `steps[]`

```yaml
steps:
  - id: st_prod_001
    name: prod_001
    phase: ph_prod
    order: 0
    topology: top_wt_hmr
    input_coords: { source: step, ref: st_min }
    mdin: prod_001.in
    mdout: prod_001.out
    mdcrd: prod_001.nc
    notes: []
    gaps: { expected: null, tolerance: null }
```

| Field | Required | Meaning |
|---|---|---|
| `id` | **yes** | Unique identifier; referenced by other Steps' `input_coords.ref`. |
| `name` | no (default `""`) | Display name / the run's stem. |
| `phase` | **yes** | The owning Phase's `id`. |
| `order` | no | Sort key among Steps within the same phase. |
| `topology` | no | A `Topology.id` from the pool — the one prmtop this Step runs against. May be `null` if not yet assigned (a discover-draft gap). |
| `input_coords` | no (default `{source: starting_structure}`) | Where this Step's initial coordinates come from — see §6. |
| `mdin`, `mdout`, `mdcrd` | no | File paths for this run. Provide at least one parseable file for `plan`/`validate` to do anything useful with the Step. |
| `rst` | no | The restart this run **writes** (`-r restrt`). It is what the next Step reads — see §6. Omitted entirely when unset, so a Step that records no restart round-trips as no key. |
| `notes` | no (default `[]`) | List of free-text strings. |
| `gaps` | no | `{expected, tolerance}` in ps — see below. Omitted entirely when both are unset (round-trips as no key, not as `null`s, unless you write it explicitly as in the template). |

A Step is one actual run — what v1 called a "stage." It is the only level that binds a topology and names
files; Phases and the Simulation exist to give Steps shared context (a role, a topology pool, a starting
structure).

### `gaps`

Unlike v1 (§9.3), v2 has exactly **one** shape for `gaps` — a mapping with two optional numeric keys, no
shorthand:

```yaml
gaps: { expected: 100.0, tolerance: 0.5 }
```

| Key | Meaning |
|---|---|
| `expected` | Expected inter-run time discontinuity before this Step, in ps. `null`/omitted if none expected. |
| `tolerance` | Tolerance around `expected` for the continuity check. `null`/omitted to use the frame-interval-based default (see [architecture §3](architecture.md#3-continuity-and-sequence-hole-detection)). |

These are equivalent to `Step.expected_gap_ps` / `Step.gap_tolerance_ps` in the
[Python API](api.md#1-the-ambermetasimulation-model).

---

## 6. `input_coords`: the continuity anchor

```yaml
input_coords: { source: starting_structure }
input_coords: { source: step, ref: st_min }
input_coords: { source: path, path: "restarts/custom.rst7" }
```

| `source` | Requires | Resolves to |
|---|---|---|
| `starting_structure` | — | The Simulation's `starting_structure`. Normally only the first Step in a chain uses this. |
| `step` | `ref: <step id>` | The **`rst` of the referenced Step** — the restart that Step wrote. This is the continuity chain: Step *N*'s input is Step *N−1*'s output. |
| `path` | `path: "..."` | An explicit coordinate file, bypassing both of the above (e.g. a restart from outside this Simulation). |

The file that joins two Steps is written once, on the Step that **produces** it:

```yaml
- { id: st_min, name: 01_min, phase: ph_eq, order: 0, mdin: 01_min.mdin, rst: 01_min.rst,
    input_coords: { source: starting_structure } }
- { id: st_nvt, name: 02_nvt, phase: ph_eq, order: 1, mdin: 02_nvt.mdin, rst: 02_nvt.rst,
    input_coords: { source: step, ref: st_min } }
```

`st_nvt` reads `01_min.rst` because that is `st_min`'s `rst`. Nothing repeats the path, so renaming the
restart is a one-line edit, and reordering or deleting Steps cannot leave a stale copy pointing at the
wrong neighbour. When you hand-author a manifest you only set `ref`.

Manifests written before `rst` existed stored the resolved restart on the *consuming* Step, as a `path`
beside the `ref`. Those are **normalised on load**: the filename is moved onto the producing Step's `rst`
and dropped from the consumer, so the document you save back is in the current shape and no later edit can
lose the filename. A `path` that cannot be normalised — the `ref` names a Step that is not in the document
— is still honoured as a fallback when resolving.

Real example — running `discover` on the sample production sequence in
`tests/data/amber/md_test_files/` (five `ntp_prod_000N` runs chained off restarts, no phases/steps written
yet) and inspecting the `--write`'d manifest:

```yaml
- id: 04e19344
  name: ntp_prod_0002
  phase: cd4dddd1
  order: 1
  topology: top_CH3L1_HUMAN_6NAG
  input_coords:
    source: step
    ref: 42251d53
    path: ntp_prod_0001.rst
  mdin: ntp_prod_0002.mdin
  mdout: ntp_prod_0002.mdout
  mdcrd: null
  notes: []
```

---

## 7. Canonical role tokens

Both the GUI and CLI classify roles through the **one** shared function, `ambermeta.roles.classify_role`:

```
"minimization" | "heating" | "equilibration" | "production" | ""
```

Precedence: (1) authoritative content — `imin=1` in the mdin/mdout ⇒ `minimization`; (2) filename/path
cues, matched on word boundaries (`_`, `.`, `-`, or start/end of a path component), so `minor.in` does
**not** match `minimization` the way a naive substring search would; (3) other content heuristics
(position restraints/`ibelly` ⇒ `equilibration`; a low→high temperature ramp ⇒ `heating`; a very long
`nstlim` ⇒ `production`). An unrecognized name/content classifies as `""` (unknown), never a guess.

A Phase's `role` is normally set once (from its Steps' classified roles, on discovery) rather than
re-derived per Step; a Step itself has no `role` field — role lives on the Phase.

---

## 8. `export --to legacy`: flattening back to v1

`ambermeta export <manifest> --to legacy` (any v1 or v2 input, auto-migrated on read) flattens a
`Simulation` back to the v1 flat shape for downstream tools that still expect `stages:`:

- The pool's first `normal` topology → top-level `global_prmtop`; the first `hmr` topology (if any) →
  `hmr_prmtop`. If the pool holds more than one of a kind, only the first survives at the top level — but
  every Step still gets its *own* `prmtop` key set to whatever it actually bound to, so per-step topology
  choice is not lost even when it is written to CSV (see below).
- Each Phase's Steps become stage dicts, in order, each carrying `stage_role` from its Phase's `role`.
- `input_coords` collapses to a single `inpcrd` path: the resolved `path` if the Step's `input_coords` has
  one, else the Simulation's `starting_structure` if `source == starting_structure`. A `step`-sourced
  Step with no cached `path` yet (never resolved) writes no `inpcrd` at all — resolve/discover first if you
  need it in the flat output.
- `gaps` carries over as-is (`{expected, tolerance}`), same shape as v1's full form.

Real output, from the discovered sequence above:

```bash
$ ambermeta export sim.yaml --to legacy --format yaml -o legacy.yaml
```
```yaml
global_prmtop: CH3L1_HUMAN_6NAG.top
stages:
- name: ntp_prod_0001
  stage_role: production
  prmtop: CH3L1_HUMAN_6NAG.top
  mdin: ntp_prod_0001.mdin
  mdout: ntp_prod_0001.mdout
  inpcrd: CH3L1_HUMAN_6NAG.crd
- name: ntp_prod_0002
  stage_role: production
  prmtop: CH3L1_HUMAN_6NAG.top
  mdin: ntp_prod_0002.mdin
  mdout: ntp_prod_0002.mdout
  inpcrd: ntp_prod_0001.rst
```

Written to CSV (`-o legacy.csv`), the same document:

```csv
name,stage_role,prmtop,mdin,mdout,mdcrd,inpcrd,expected_gap_ps,gap_tolerance_ps,notes
ntp_prod_0001,production,CH3L1_HUMAN_6NAG.top,ntp_prod_0001.mdin,ntp_prod_0001.mdout,,CH3L1_HUMAN_6NAG.crd,,,
ntp_prod_0002,production,CH3L1_HUMAN_6NAG.top,ntp_prod_0002.mdin,ntp_prod_0002.mdout,,ntp_prod_0001.rst,,,
```

---

## 9. Legacy v1 format (still read, auto-migrated)

A v1 manifest is either a **list** of stage dictionaries or a **mapping** of stage-name → stage dictionary
— no `version`/`phases`/`simulation` keys. It still opens everywhere: `ambermeta plan` and `ambermeta info`
read it through the retained top-level `load_manifest`/`load_protocol_from_manifest`/`auto_discover` API
unchanged, and `ambermeta export`, `ambermeta validate --manifest`, and the GUI's **Open** all accept a v1
file transparently, silently auto-migrating it to a `Simulation` via `load_simulation` and working with the
v2 model from then on. (`ambermeta discover` never reads an existing manifest at all — it only ever scans a
directory from scratch — so v1 auto-migration does not apply to it.)

```yaml
# list form (recommended)
global_prmtop: systems/complex.prmtop
hmr_prmtop: systems/complex_hmr.prmtop
initial_coordinates: systems/complex.inpcrd
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
| `initial_coordinates` | The starting coordinate file — recognized by the **v1→v2 migrator** (`migrate_v1_manifest`) as the source for `starting_structure`; the retained flat engine does not otherwise consume this key (it relies on per-stage `inpcrd` / restart auto-detection instead) |
| `stages` | The stage list (list form) |
| `settings` | Validation behavior for the retained flat engine only — `strict_validation`, `allow_gaps` (§9.4) |
| `stage_role_rules` | Name-based role inference for the retained flat engine only (§9.4) — **not** consulted by v1→v2 migration, which always uses the shared `classify_role` classifier instead |

### 9.1 Stage keys

A stage recognizes exactly five file slots — `STAGE_FILE_KINDS = (prmtop, mdin, mdout, mdcrd, inpcrd)` —
given either under a `files` mapping or as top-level keys on the stage. Unrecognized keys are ignored.

| Key | Required | Meaning |
|---|---|---|
| `name` | **yes** | Unique identifier; used for ordering and restart lookup. |
| `stage_role` | no | `minimization` / `heating` / `equilibration` / `production`; inferred from content/path if omitted (always with an `INFO` note). |
| `prmtop`, `mdin`, `mdout`, `mdcrd`, `inpcrd` | no | File paths (provide at least one parseable file). |
| `notes` | no | String or list of strings → validation notes. |
| `gaps` / `gap` | no | Expected discontinuity before this stage (§9.3). |
| `expected_gap_ps` | no | Flat alternative to nested `gaps`. |
| `gap_tolerance_ps` | no | Flat tolerance for gap validation. |

Providing `inpcrd` marks the restart used for the stage. Programmatic callers may also inject restarts via
the `restart_files` argument to `auto_discover` (keyed by stage `name` or `stage_role`).

### 9.2 Legacy key aliases

`normalize_stage_keys` accepts a few variant spellings on read and canonicalizes them: `stage` → `name`,
`role` → `stage_role`, and the flat `expected_gap_ps`/`gap_tolerance_ps` (and the TOML canonical writer's
`gaps_expected`/`gaps_tolerance`) fold into a nested `gaps` dict. CSV additionally accepts `stage`/`role`
as column headers.

### 9.3 Gap configuration (v1 only — v2 has one shape, §5)

`gaps` (or `gap`) describes an expected time discontinuity before a stage. It accepts several shapes in v1:

```yaml
# full form
gaps:
  expected: 100.0       # or expected_ps
  tolerance: 0.5         # or tolerance_ps
  notes:
    - "Restart from backup checkpoint"

# shorthand: just the expected gap in ps
gaps: 100.0

# notes only
gaps: "Manual restart from backup"
```

Validation behavior (retained flat engine): within tolerance → an `INFO` note confirming the gap; outside
tolerance → a `WARNING`. With no expectation set, sub-tolerance gaps are normalized to 0 and a larger gap
produces a note to verify continuity.

> ⚠️ **Migration gotcha:** the v1→v2 migrator (`migrate_v1_manifest`, used by `export`/`validate --manifest`/
> GUI **Open** on a v1 file) only understands the full `{expected, tolerance}` mapping (or the flat
> `expected_gap_ps`/`gap_tolerance_ps` keys, which normalize into that mapping before migration runs). The
> two shorthand forms above — a bare number or a bare string — are valid for the *retained flat engine*
> (`ambermeta plan`, `ambermeta info`, non-manifest `auto_discover`) but **crash the v2 migration path** if
> present. Use the full mapping form (or the flat `expected_gap_ps`/`gap_tolerance_ps` keys) for any v1
> manifest you might later `export` or open in the GUI.

### 9.4 `settings` and `stage_role_rules`

**`settings`** — consulted only by the retained flat engine:

| Key | Default | Effect |
|---|---|---|
| `strict_validation` | `true` | `true` runs cross-stage continuity checks; `false` skips them (≡ `skip_cross_stage_validation`). |
| `allow_gaps` | `false` | When `true` (and validation is on), unconfigured positive gaps are recorded as info, not warnings. |

The CLI flag `--skip-cross-stage-validation` (on `ambermeta plan`) overrides `settings.strict_validation`
unconditionally.

**`stage_role_rules`** — name-based inference applied when a stage omits `stage_role`, also flat-engine
only. Two accepted forms:

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

### 9.5 v1 format examples

**TOML**

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

**CSV** — the canonical header is `CSV_COLUMNS`:

```csv
name,stage_role,prmtop,mdin,mdout,mdcrd,inpcrd,expected_gap_ps,gap_tolerance_ps,notes
minimize,minimization,system.prmtop,min.in,min.out,,,,,"Initial minimization"
equilibrate,equilibration,system.prmtop,equil.in,equil.out,equil.nc,heat.rst7,0,0.1,"NVT equilibration"
production,production,system.prmtop,prod.in,prod.out,prod.nc,equil.rst7,0,0.1,"Main production run"
```

Column order is flexible (driven by the header); empty cells are missing values; the notes field accepts
semicolon-separated entries; the reader also accepts legacy column names `stage` (→ `name`) and `role`
(→ `stage_role`).

> ⚠️ CSV cannot represent a separate `hmr_prmtop` alongside `global_prmtop` at the document level (there is
> nowhere in a flat row to put a second global topology). Saving a v1 protocol with distinct global/HMR
> topologies to CSV loses that top-level pairing — use YAML/JSON/TOML when it matters. This does not affect
> v2 exported *through* `export --to legacy`, since each row's own `prmtop` column already carries whichever
> topology that particular Step actually bound to.

### 9.6 v1 → v2 auto-migration table

Triggered whenever `load_simulation` (used by `export`, `validate --manifest`, GUI **Open**) is pointed at
a file that is not v2-shaped (no `version: 2`, no `phases`/`simulation` key):

| v1 | v2 |
|---|---|
| `global_prmtop` | A pool `Topology` with `kind: normal`. |
| `hmr_prmtop` | A pool `Topology` with `kind: hmr`. |
| A stage's own `prmtop` | A pool `Topology` with `kind: normal` (deduplicated by path; a stage without its own `prmtop` falls back to referencing the `global_prmtop` entry). |
| `initial_coordinates` | `simulation.starting_structure`. |
| Each stage | One `Step` (`id: st_<index>`). |
| Contiguous stages sharing the same (explicit or inferred) `stage_role` | Coalesce into one `Phase` (`id: ph_<n>`, `name` = the role title-cased, or `"Stage"` if the role is empty). A role change starts a new phase even if a later stage reverts to an earlier role. |
| First stage's coordinates | `input_coords: {source: starting_structure}` when the manifest sets `initial_coordinates`; otherwise `{source: path, path: <its own inpcrd>}` if the stage has an `inpcrd`; otherwise `{source: starting_structure}` regardless (pointing at an unset/`null` starting structure — a validation gap to fill in). |
| Every later stage | `input_coords: {source: step, ref: <previous step's id>}` — chained, regardless of whether the v1 file bothered to set `inpcrd` on it explicitly. |
| `stage_role` (explicit or name/content-inferred via `classify_role`) | `Phase.role`. (`stage_role_rules`-based inference is **not** consulted during migration — see §9 above.) |
| `gaps: {expected, tolerance}` (or the flat alias keys) | `Step.expected_gap_ps` / `Step.gap_tolerance_ps` → written back out as `gaps: {expected, tolerance}`. |
| `gaps` shorthand (bare number/string) | **Not supported** — raises `AttributeError` during migration (§9.3). |
| `notes` | `Step.notes` (list, as-is). |
| `settings`, `stage_role_rules` | Not migrated — these only ever configured the retained flat engine. |

Real example — migrating a small v1 manifest with `export --to v2`:

```bash
$ ambermeta export v1demo.yaml --to v2
```
```jsonc
// v1demo.yaml:
// global_prmtop: CH3L1_HUMAN_6NAG.top
// initial_coordinates: CH3L1_HUMAN_6NAG.crd
// stages:
//   - name: ntp_prod_0001
//     mdin: ntp_prod_0001.mdin
//     mdout: ntp_prod_0001.mdout
//   - name: ntp_prod_0002
//     mdin: ntp_prod_0002.mdin
//     mdout: ntp_prod_0002.mdout
{
  "version": 2,
  "simulation": {
    "topologies": [
      { "id": "top_0", "path": "CH3L1_HUMAN_6NAG.top", "kind": "normal" }
    ],
    "starting_structure": "CH3L1_HUMAN_6NAG.crd"
  },
  "phases": [
    { "id": "ph_0", "name": "Production", "role": "production", "order": 0 }
  ],
  "steps": [
    {
      "id": "st_0", "name": "ntp_prod_0001", "phase": "ph_0", "order": 0,
      "topology": "top_0",
      "input_coords": { "source": "starting_structure" },
      "mdin": "ntp_prod_0001.mdin", "mdout": "ntp_prod_0001.mdout", "mdcrd": null,
      "notes": []
    },
    {
      "id": "st_1", "name": "ntp_prod_0002", "phase": "ph_0", "order": 1,
      "topology": "top_0",
      "input_coords": { "source": "step", "ref": "st_0" },
      "mdin": "ntp_prod_0002.mdin", "mdout": "ntp_prod_0002.mdout", "mdcrd": null,
      "notes": []
    }
  ]
}
```

(`stage_role` was omitted on both stages here; both were classified `production` by `classify_role` from
the `ntp_prod_...` filenames, so they coalesced into a single Phase.)

---

## 10. Environment-variable expansion

File paths (and any other string value, recursively — topology paths, `starting_structure`,
`mdin`/`mdout`/`mdcrd`, an explicit `input_coords.path`, etc.) support `${VAR}` and `$VAR`, expanded at
load time; undefined variables are left unchanged. This applies uniformly whether the manifest turns out to
be v1 or v2 — `load_simulation` expands before it even checks the shape.

```yaml
- name: production
  prmtop: ${PROJECT_ROOT}/systems/complex.prmtop
  mdin:   $HOME/templates/prod.in
  mdout:  ${OUTPUT_DIR}/prod.out
```

Disable it with `expand_env=False` on `load_manifest`/`load_protocol_from_manifest`/`auto_discover`, or
`--no-expand-env` on `ambermeta plan`. `load_simulation` (and therefore `export`, `validate --manifest`,
and the GUI) has no such switch — expansion is always on for v2 loads.

---

## 11. Authoring a manifest without writing one

```bash
ambermeta discover runs/ --write sim.yaml           # scan a directory into a v2 draft
ambermeta init runs/ --v2 -o sim.yaml               # a blank, commented v2 template to fill in by hand
ambermeta init runs/ --auto --output manifest.yaml  # v1 template, still supported (--format yaml/json/toml/csv)
ambermeta gui runs/                                 # build it in the browser, drag files onto slots
```

`discover` and the GUI's **Discover** button run the same engine (`discover_draft` in
`ambermeta/gui/api/core_bridge.py`): they classify every prmtop into the topology pool, find a starting
structure, group runs into role-named phases, and chain each step's `input_coords` off the previous step —
surfacing each inference as an explainable suggestion rather than silently guessing. `init --v2` is simpler:
it always writes the same fixed, commented YAML template text shown in §2 (it does not scan `directory`, and
ignores `--format`) — a starting point you fill in by hand rather than a draft of what's on disk. See the
[GUI guide](gui.md) and [CLI reference](cli.md).

---

## 12. Consumers

| Entry point | Behavior |
|---|---|
| `load_simulation(path)` | Read any manifest (v1 auto-migrated) into a `Simulation`. |
| `write_simulation(sim, path, fmt)` | Write a `Simulation` as v2; `fmt` ∈ `{"json", "yaml"}`. |
| `simulation_to_payload(sim)` / `payload_to_simulation(payload)` | v2 dict round-trip (what the GUI's HTTP API sends/receives). |
| `discover_draft(base_directory, recursive=True, pattern=None)` | Scan a directory into a draft `Simulation` + suggestions + warnings — powers `ambermeta discover` and the GUI's **Discover**. |
| `validate_simulation(sim, settings, base_directory)` | Continuity + sequence-hole validation over a `Simulation` — powers `ambermeta validate --manifest` and the GUI's **Validate** panel. |
| `load_manifest(path, expand_env=True)` | (Retained flat engine) parse + normalize stage entries; returns raw data, no protocol. |
| `load_protocol_from_manifest(path, directory=…)` | (Retained flat engine) parse, build, validate → `SimulationProtocol`. |
| `auto_discover(directory, manifest=…)` | (Retained flat engine) with a manifest, parse the listed stages; with `manifest=None`, discover on disk. |
| `ambermeta plan --manifest …` | The CLI front end — v2/migratable manifests print the Simulation → Phase → Step structure; a genuinely flat v1 manifest keeps the classic per-stage summary. |

### Programmatic restart injection (retained flat engine)

```python
from ambermeta import auto_discover

protocol = auto_discover(
    "runs/",
    manifest=manifest_data,
    restart_files={"prod1": "runs/equil.rst7"},   # by stage name or role
)
```

### Builder with per-stage tolerances (retained flat engine)

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

Full signatures for all of the above are in [api.md](api.md).

---

## 13. Errors

| Error | Cause | Fix |
|---|---|---|
| `FileNotFoundError` | Manifest (or a referenced file) missing | Check the path / the referenced file paths. |
| `ImportError` (YAML) | `pyyaml` not installed | `pip install -e ".[yaml]"` |
| `ImportError` (TOML) | `tomli` missing on Python < 3.11 | `pip install -e ".[toml]"` |
| `TypeError` | Manifest is neither list nor mapping (v1) / not a dict (v2) | Use one of the shapes in §2 or §9. |
| `ValueError` (v1) | A stage has no `name` | Add `name` to each stage. |
| `ValueError` | `write_simulation` called with `fmt` other than `json`/`yaml` | Use `export --to legacy` for TOML/CSV output (§1, §8). |
| `AttributeError` during migration | A v1 stage uses the `gaps` shorthand (bare number/string) | Rewrite as `gaps: {expected: ..., tolerance: ...}` before exporting/opening in the GUI (§9.3). |
| `RuntimeError` | YAML output requested without `pyyaml` installed | `pip install -e ".[yaml]"` |

Validation (`ambermeta validate`, `plan`, `validate_simulation`) produces **warnings/findings**, not hard
errors, for: missing files that block a check, atom-count mismatches, timing/box inconsistencies,
unexpected inter-step gaps, and sequence holes in a numbered run sequence. See
[architecture §3](architecture.md#3-continuity-and-sequence-hole-detection) and [cli.md](cli.md#validate).
