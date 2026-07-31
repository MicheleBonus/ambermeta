# Manifest schema

**A manifest is the durable, hand-editable description of a Simulation** — a topology pool, a starting
structure, an ordered set of Phases, and the Steps inside them, each pointing at its own files and its own
input-coordinate source. This is the **v2** format (`version: 2`), the shared CLI↔GUI contract for the
[Simulation → Phase → Step](architecture.md#2-the-model-simulation--phase--step) model.

There is exactly one manifest format. `ambermeta discover --write`, `ambermeta export`, and the GUI's
**Save** all write through the same `write_simulation` function, so their output is byte-identical for the
same document; `load_simulation` is the only reader.

---

## 1. Formats

A manifest is YAML or JSON. Format is detected from the file extension.

| Format | Extension | Requires |
|---|---|---|
| YAML | `.yaml`, `.yml` | `pyyaml` (the `yaml` extra) |
| JSON | anything else | stdlib — always available |

The two are interchangeable in both directions: `load_simulation` parses either to the same plain
dict *before* it inspects the shape, and `write_simulation` takes `fmt` ∈ `{"json", "yaml"}` (anything
else raises `ValueError: v2 write supports json/yaml only, got: <fmt>`). Only the extension decides how a
file is *read* — a `.yaml`/`.yml` path goes through PyYAML, every other extension is parsed as JSON.

TOML and CSV are **not** manifest formats. Pointing any reader at a `.toml` or `.csv` path fails
immediately rather than half-parsing it:

```
AmberMeta reads and writes manifests as YAML or JSON only; TOML and CSV are not manifest formats.
```

(`ambermeta plan --stats-csv` is unrelated: it writes a per-stage *statistics* CSV — a report, not a
manifest — and is unaffected by any of this.)

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
| `version` | int | `2` for the current format. `load_simulation` keys off the presence of `steps` rather than off this number, but always write `2` explicitly. |
| `simulation` | mapping | The topology pool + the starting structure (§3). |
| `phases` | list | Ordered Phase records (§4). |
| `steps` | list | Ordered Step records, each tagged with the `phase` id it belongs to (§5). A document with no `steps` list is not a manifest — see §11. |

Those four are the whole vocabulary. In particular there is **no `settings` key**: `payload_to_simulation`
never reads one, and adding one to a file changes nothing. Validation behaviour is chosen by the caller —
`ambermeta plan` builds its settings purely from its CLI flags, so `--skip-cross-stage-validation` simply
turns the cross-stage continuity checks off; it is not overriding anything written in the file.

**Relative paths** (topology paths, `starting_structure`, `mdin`/`mdout`/`mdcrd`, an explicit
`input_coords.path`) are resolved against a base directory chosen by whoever loads the file: the manifest's
own directory for `ambermeta validate --manifest`, `plan`'s positional `directory` argument (default `.`)
for `ambermeta plan -m`, and the served directory for the GUI. Keeping the manifest beside the files it
describes makes all three agree.

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
| `topologies` | no (may be empty) | The pool. Every prmtop the Simulation uses lives here **once**; Steps bind to one by `id` instead of each Step carrying its own copy. |
| `starting_structure` | no | The initial coordinate file that feeds the **first** Step whose `input_coords.source` is `starting_structure`. |

Each `topologies[]` entry is a `Topology`:

| Field | Required | Meaning |
|---|---|---|
| `id` | **yes** | Unique identifier; referenced by `steps[].topology`. Hand-written manifests typically use a descriptive slug (`top_wt`); `discover` generates one from the filename (`top_CH3L1_HUMAN_6NAG`). |
| `path` | **yes** | Path to the prmtop file. |
| `kind` | no (default `"normal"`) | `"normal"` or `"hmr"` (hydrogen-mass-repartitioned). Auto-detected from the topology's hydrogen masses when discovered from disk; always overridable by hand. |

A pool may hold any number of topologies — including more than one `normal`/`hmr` pair, for genuinely
distinct chemical systems described by a single Simulation.

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
| `phase` | **yes** | The owning Phase's `id`. A Step whose `phase` matches no Phase record is dropped on load. |
| `order` | no | Sort key among Steps within the same phase. |
| `topology` | no | A `Topology.id` from the pool — the one prmtop this Step runs against. May be `null` if not yet assigned (a discover-draft gap). |
| `input_coords` | no (default `{source: starting_structure}`) | Where this Step's initial coordinates come from — see §6. |
| `mdin`, `mdout`, `mdcrd` | no | File paths for this run. Provide at least one parseable file for `plan`/`validate` to do anything useful with the Step. |
| `rst` | no | The restart this run **writes** (`-r restrt`). It is what the next Step reads — see §6. Omitted entirely when unset, so a Step that records no restart round-trips as no key. |
| `notes` | no (default `[]`) | List of free-text strings. |
| `gaps` | no | `{expected, tolerance}` in ps — see below. Omitted entirely when both are unset (round-trips as no key, not as `null`s, unless you write it explicitly as in the template). |

A Step is one actual run. It is the only level that binds a topology and names files; Phases and the
Simulation exist to give Steps shared context (a role, a topology pool, a starting structure).

### `gaps`

`gaps` has exactly **one** shape — a mapping with two optional numeric keys, no shorthand:

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
`tests/data/amber/md_test_files/` (five `ntp_prod_000N` runs chained off restarts) and inspecting the
first two Steps of the `--write`'d manifest:

```yaml
- id: 5dd38413
  name: ntp_prod_0001
  phase: 6899ce10
  order: 0
  topology: top_CH3L1_HUMAN_6NAG
  input_coords:
    source: starting_structure
  mdin: ntp_prod_0001.mdin
  mdout: ntp_prod_0001.mdout
  mdcrd: null
  notes: []
  rst: ntp_prod_0001.rst
- id: a1ed8c23
  name: ntp_prod_0002
  phase: 6899ce10
  order: 1
  topology: top_CH3L1_HUMAN_6NAG
  input_coords:
    source: step
    ref: 5dd38413
  mdin: ntp_prod_0002.mdin
  mdout: ntp_prod_0002.mdout
  mdcrd: null
  notes: []
  rst: ntp_prod_0002.rst
```

(Ids are generated, so yours will differ.)

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

## 8. Environment-variable expansion

File paths (and any other string value, recursively — topology paths, `starting_structure`,
`mdin`/`mdout`/`mdcrd`, an explicit `input_coords.path`, etc.) support `${VAR}` and `$VAR`, expanded at
load time, before the reader even checks the document's shape; undefined variables are left unchanged.

```yaml
simulation:
  topologies:
    - id: top_wt
      path: ${PROJECT_ROOT}/systems/complex.prmtop
  starting_structure: ${PROJECT_ROOT}/systems/complex.inpcrd
steps:
  - id: st_prod
    name: production
    phase: ph_prod
    mdin:  $HOME/templates/prod.in
    mdout: ${OUTPUT_DIR}/prod.out
```

Disable it with `expand_env=False` on `load_simulation`, or `--no-expand-env` on `ambermeta plan`.
`ambermeta export`, `ambermeta validate --manifest`, and the GUI load with the default, so expansion is
always on for them.

---

## 9. Authoring a manifest without writing one

```bash
ambermeta discover runs/ --write sim.yaml   # scan a directory into a v2 draft
ambermeta init -o sim.yaml                  # a blank, commented v2 template to fill in by hand
ambermeta gui runs/                         # build it in the browser, drag files onto slots
```

`discover` and the GUI's **Discover** button run the same engine (`discover_draft` in
`ambermeta/gui/api/core_bridge.py`): they classify every prmtop into the topology pool, find a starting
structure, group runs into role-named phases, and chain each step's `input_coords` off the previous step —
surfacing each inference as an explainable suggestion rather than silently guessing. Directory scanning is
`discover` and only `discover`.

`init` is simpler: it always writes the same fixed, commented v2 YAML template — a starting point you fill
in by hand rather than a draft of what's on disk. It does not scan anything; its positional `directory`
argument (default `.`) only says where the file lands, and `-o/--output` and `--force` are its only flags.
See the [GUI guide](gui.md) and [CLI reference](cli.md).

---

## 10. Consumers

| Entry point | Behavior |
|---|---|
| `load_simulation(path, expand_env=True)` | Read a v2 manifest into a `Simulation`. Raises if the file has no `steps` list (§11). |
| `write_simulation(sim, path, fmt)` | Write a `Simulation` as v2; `fmt` ∈ `{"json", "yaml"}`. |
| `simulation_to_payload(sim)` / `payload_to_simulation(payload)` | v2 dict round-trip (what the GUI's HTTP API sends/receives, and what `load_simulation`/`write_simulation` sit on top of). |
| `discover_draft(base_directory, recursive=True, pattern=None)` | Scan a directory into a draft `Simulation` + suggestions + warnings — powers `ambermeta discover` and the GUI's **Discover**. |
| `validate_simulation(sim, settings, base_directory)` | Continuity + sequence-hole validation over a `Simulation` — powers `ambermeta validate --manifest` and the GUI's **Validate** panel. `settings` is the caller's dict, never read from the manifest (§2). |
| `ambermeta plan --manifest …` | The CLI front end: loads the manifest, flattens it for the validation engine, and prints the Simulation → Phase → Step structure. |

To build a protocol from a document you already hold in memory, use
`auto_discover(directory, manifest=<list of stage dicts>)` — its `manifest=` argument takes stage dicts,
not a path. Full signatures for all of the above are in [api.md](api.md).

---

## 11. Errors

| Error | Cause | Fix |
|---|---|---|
| `FileNotFoundError`: `Manifest not found: <path>` | Manifest missing | Check the path. |
| `ImportError` (YAML) | `pyyaml` not installed and the path ends in `.yaml`/`.yml` | `pip install -e ".[yaml]"` |
| `<path> is not a v2 manifest (no 'steps' key).` | The file is some other document — most often a manifest from before the v2 format | `ambermeta discover <dir> --write <path>` to rebuild it. |
| `<path> is a v2 manifest but is missing its 'steps' list.` | The document announces itself as v2 (`version: 2`, or a `simulation`/`phases` key) but has no steps | Restore the steps, or rebuild with `discover --write`. |
| `AmberMeta reads and writes manifests as YAML or JSON only; TOML and CSV are not manifest formats.` | A `.toml` or `.csv` path was handed to a reader | Convert the document to YAML or JSON (§1). |
| `TypeError` | The parsed file is neither a mapping nor a list | Use the shape in §2. |
| `ValueError` | `write_simulation` called with `fmt` other than `json`/`yaml` | Ask for `json` or `yaml`. |
| `RuntimeError` | YAML output requested without `pyyaml` installed | `pip install -e ".[yaml]"` |

On the command line these surface as `ERROR: <message>` with exit code 1; `ambermeta export` and
`ambermeta validate --manifest` prefix them with `Failed to load manifest: `.

Validation (`ambermeta validate`, `plan`, `validate_simulation`) produces **warnings/findings**, not hard
errors, for: missing files that block a check, atom-count mismatches, timing/box inconsistencies,
unexpected inter-step gaps, and sequence holes in a numbered run sequence. See
[architecture §3](architecture.md#3-continuity-and-sequence-hole-detection) and [cli.md](cli.md#validate).
