# Architecture

**AmberMeta is one engine with two faces.** A single core — parsers, a role classifier, a manifest contract, simulation assembly, and a validation model — does all the work. The CLI and the GUI are thin presentation layers over that core; neither contains domain logic the other lacks. This document is the map of that core: the three-level model it builds, how a manifest round-trips through it, and the contracts that hold the CLI and GUI together.

> **Audience:** contributors, and users who want to understand *why* a result looks the way it does. For task-oriented usage, start with the [tutorials](tutorials.md); for exact signatures, the [API reference](api.md); for the full manifest schema, the [manifest reference](manifest.md).

---

## 1. Package layout

```
ambermeta/
  __init__.py            # public re-exports of the retained engine (the classic import surface)
  cli.py                 # argparse front end: plan / discover / validate / export / init / info / gui / completion
  errors.py              # AmberMetaError, FileLoadError, classify_exception
  simulation.py          # the v2 model: Simulation/Phase/Step/Topology/InputCoords + load/write
  roles.py               # classify_role() — the ONE role classifier, shared by CLI and GUI
  topology_pool.py       # TopologyPool + classify_topology_pool() — HMR detection over a set of prmtops
  coords.py              # sniff_coordinate_kind() — inpcrd vs mdcrd by content, not extension
  protocol.py            # SimulationStage, SimulationProtocol, ProtocolBuilder — discovery, assembly,
                          # continuity/sequence-gap detection; still the shared validation machinery
  manifest.py            # tolerant YAML/JSON reader + in-memory stage-dict helpers; STAGE_FILE_KINDS
  utils.py               # MetadataBase, shared helpers
  parsers/               # thin per-file wrappers (PrmtopParser, MdinParser, ...)
  legacy_extractors/     # the actual byte-level parsing → *Metadata dataclasses
  gui/
    server.py            # FastAPI app, run_gui(), CORS + static SPA serving
    api/
      core_bridge.py     # the ONLY GUI module that imports the core (manifest/protocol/parsers/simulation)
      document.py        # server-authoritative Document + DocumentStore (undo/redo)
      files.py           # directory scan + resolve_within_base containment
      routes.py          # HTTP handlers (thin; delegate to the store + bridge)
      schemas.py         # Pydantic request/response models
    static/               # pre-built, committed frontend bundle (offline)
    frontend/             # React + TS + Vite source for static/
```

The dependency arrows still point one way: `cli` and `gui` depend on the core (`simulation`, `roles`, `topology_pool`, `coords`, `protocol`, `manifest`, `parsers`, `errors`); the core depends on nothing above it. `legacy_extractors` is a leaf — it knows file formats and nothing about simulations.

Two engine layers live side by side, deliberately:

- **`ambermeta.simulation`** — the Simulation → Phase → Step model: plain dataclasses plus `load_simulation`/`write_simulation`. This is what `discover`, `export`, `validate --manifest`, `plan -m <manifest>`, and every GUI operation build and hand around.
- **`ambermeta.protocol`** — the flat `SimulationProtocol`/`SimulationStage` engine. It still does the actual file grouping, parsing orchestration, role inference, and continuity math; the v2 layer *flattens into it* rather than reimplementing validation (§6). It also remains the whole path for `plan --recursive` and `plan --interactive`, which build a protocol straight from the directory (or from prompted stage dicts) without ever constructing a `Simulation`.

Neither layer duplicates parsing, role classification, or continuity logic — see §6 for exactly how the new model reuses the old validator.

---

## 2. The model: Simulation → Phase → Step

v1.0 modeled a run as a flat **Protocol → Stage** (two levels; a "stage" was one run). v1.1 rebuilds this as **three levels**, matching how people actually think about a run:

| Level | Dataclass (`ambermeta/simulation.py`) | Owns |
|---|---|---|
| **Simulation** | `Simulation(version, topologies, starting_structure, phases)` | the whole document: a **topology pool** and one **starting structure** |
| **Phase** | `Phase(id, name, role, steps)` | a named, role-bearing grouping (minimization / heating / equilibration / production / `""`) |
| **Step** | `Step(id, name, topology, input_coords, mdin, mdout, mdcrd, rst, lineage, expected_gap_ps, gap_tolerance_ps, notes)` | one actual run — today's old "stage" |

A **Phase** is a convenience/grouping level: it carries a role but no files of its own. A **Step** is where the files live, and it binds exactly one topology **by id** out of the Simulation's pool.

### Topology pool

Topologies live once on the `Simulation`, not per-run. `ambermeta/topology_pool.py` builds the pool during discovery:

```python
# ambermeta/topology_pool.py
HMR_MIN_TIMESTEP_PS = 0.002          # non-HMR SHAKE tops out at dt = 0.002 ps

def implies_hmr(dt) -> bool:
    return isinstance(dt, (int, float)) and dt > HMR_MIN_TIMESTEP_PS
```

`classify_topology_pool(directory, prmtop_rels)` parses every discovered prmtop, labels each `normal` or `hmr` from its own atom masses (`hmr_active`, via `extract_prmtop_metadata`), and keeps **all** of them — distinct chemical systems (different atom counts) are preserved rather than collapsed into a single global topology. A step references a pool entry by `id`; a phase can cascade "use this topology for every step in me" as a UI convenience, but the phase itself stores nothing.

### Input-coordinate sources

Every step's starting coordinates resolve through `InputCoords(source, ref, path)`:

| `source` | Meaning |
|---|---|
| `starting_structure` | read the Simulation's single starting structure — what the **head of each lineage** reads, which in a document that declares none is just the first step |
| `step` (with `ref: <step id>`) | chain from the referenced step's output restart (its `rst`, stored on the step that writes it) — the continuity anchor |
| `path` (with `path: "..."`) | an explicit override, bypassing the chain |

This makes the old implicit "the first stage uses the initial coordinates, later stages use the previous restart" rule an explicit, inspectable field on every step instead of an assumption baked into ordering.

### The one role classifier

`ambermeta/roles.py:classify_role()` is the single source of truth for role inference, imported by `ambermeta.protocol` (`infer_stage_role_from_path`/`infer_stage_role_from_content`), the CLI, and the GUI's `discover_draft`. Precedence:

1. **Authoritative content** — `cntrl.imin == 1` (mdin) or `mdout.imin == 1` → `minimization`, regardless of filename.
2. **Filename/path cues** — word-boundary matching per path component (`min`/`minim`/`em` → minimization; `heat`/`warm`/`therm`/`anneal` → heating; `equil`/`eq`/`nvt`/`npt` → equilibration; `prod` → production). Boundaries are `_`, `.`, `-`, or start/end of the component, so `minor` never matches `min`.
3. **Other content heuristics** — restraints (`ntr`/`ibelly`) → equilibration; a temperature ramp (`tempi < temp0 <= 50`) → heating; a long run (`nstlim > 500000`) → production.

Canonical tokens: `"minimization" | "heating" | "equilibration" | "production" | ""`.

---

## 3. Continuity and sequence-hole detection

Two related but distinct checks run over consecutive steps, both in `ambermeta/protocol.py` and both reused (not reimplemented) by the v2 validator (§6):

**Continuity** compares the previous step's output-restart end-time to the current step's input-coordinate time:

```
gap = start_time(current) - end_time(previous)
```

The tolerance is **frame-interval based, not scaled to absolute elapsed time** — a small absolute floor plus half the previous run's average timestep:

```python
default_tolerance = 0.1
if isinstance(prior_dt, (int, float)) and prior_dt > 0:
    default_tolerance = max(default_tolerance, float(prior_dt) * 0.5)
```

A gap within an explicit `expected_gap_ps ± gap_tolerance_ps` window (or within the default floor, when no expectation is set) is logged as an `INFO` note — a **healthy transition is never flagged**. A gap outside that window, an overlap, or an unconfigured non-zero gap becomes a real (non-`INFO`) continuity note, which is what the GUI turns into a `continuity_gap` suggestion.

"Consecutive" means consecutive **within one lineage**. When any step carries a `lineage` tag, `_check_continuity` partitions the stages by member first and compares pairs inside each member; each member's head is then measured against the step it actually continues from (its `input_coords.ref`, carried into the flat engine as `parent_id`), or gets an `INFO: Continuity for <name> was not measured (no producing stage resolved).` note where no producer resolves. A document that declares no lineage at all takes the original flat neighbour-by-neighbour path, unchanged.

**Sequence holes** are a separate, first-class finding: `detect_sequence_gaps(names, lineages=None)` looks at numbered-run families (`prod_0001`, `prod_0002`, `prod_0004`, …) and reports the missing indices **per member**, keyed on `(member, base)` — here, `{(UNTAGGED, "prod"): [3]}` — independent of whether any continuity gap was ever measured, because the file for index 3 simply doesn't exist to measure a gap against. `lineages` is read positionally alongside `names`, one tag per run and `None` where a run carries none; omitting it puts every run in the one untagged bucket (`ambermeta.lineages.UNTAGGED`), which is the single family the detector always had. Inside a member, an index between its lowest and its highest that no run occupies is missing; across members of one base, only those whose numbering *overlaps* frame each other — so `rep2` stopping at `prod_0001` beside `rep1`'s `0001-0003` is reported, while a member numbered `0011-0012` on a scale of its own is not.

Real output on the sample data (`tests/data/amber/md_test_files/`, a 64,528-atom glycoprotein system with a five-run NPT production sequence) with `ntp_prod_0003.*` removed:

```
$ ambermeta discover /path/to/dir
Simulation summary
==================
Topologies (pool): 1
  - top_CH3L1_HUMAN_6NAG [normal]  CH3L1_HUMAN_6NAG.top
Starting structure: CH3L1_HUMAN_6NAG.crd
Phases: 1

Phase: Production [production]
  - ntp_prod_0001  topology=CH3L1_HUMAN_6NAG.top  input=starting structure  (mdin=ntp_prod_0001.mdin, mdout=ntp_prod_0001.mdout)
  - ntp_prod_0002  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0001 (ntp_prod_0001.rst)  (mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)
  - ntp_prod_0004  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0002 (ntp_prod_0002.rst)  (mdin=ntp_prod_0004.mdin, mdout=ntp_prod_0004.mdout)
  - ntp_prod_0005  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0004 (ntp_prod_0004.rst)  (mdin=ntp_prod_0005.mdin, mdout=ntp_prod_0005.mdout)

Suggestions:
  - [needs_you] ntp_prod sequence is missing member(s) 3
  - [applied] CH3L1_HUMAN_6NAG.crd set as the starting structure
  - [applied] Phase roles inferred from file content/names
```

And the same hole surfacing through `validate --manifest` on the resulting v2 manifest:

```
$ ambermeta validate --manifest sim.yaml
Simulation validation

Continuity / sequence findings:
  - ntp_prod sequence is missing member(s) 3: present members of 'ntp_prod' skip index(es) 3

Validation: OK
```

(A sequence hole is a finding, not a hard failure by default — pass `--strict` to make findings a validation failure.)

---

## 4. The parsing layer

**Responsibility:** turn one file on disk into a typed metadata object, or a structured error — never an unhandled exception. Unchanged by the v1.1 model rebuild; both engine layers share it.

- **`ambermeta/parsers/`** holds thin wrapper classes (`PrmtopParser`, `MdinParser`, `MdoutParser`, `MdcrdParser`, `InpcrdParser`). Each exposes `__init__(filename)` and `parse()`. `parse()` returns a small dataclass (`PrmtopData`, `MdinData`, …) that extends `MetadataBase` and therefore always carries `filename: str` and `warnings: List[str]`.
- **The parsed payload lives on `.details`** — e.g. `PrmtopParser(path).parse().details` is a `legacy_extractors.prmtop.PrmtopMetadata`. This two-level shape (wrapper + `.details`) keeps the stable, uniform interface (`filename`/`warnings`) separate from the rich, file-specific field set.
- **`ambermeta/legacy_extractors/`** does the real work: reading the binary/ASCII formats and populating the `*Metadata` dataclasses (`PrmtopMetadata`, `MdinMetadata`, `MdoutMetadata`, `TrajectoryMetadata`, `InpcrdMetadata`). These are the field names users see in `info` output and in `.details`.

> ⚠️ **The most common documentation/usage error.** The metadata fields are on `.details`, not on the object returned by `parse()`. Write `PrmtopParser(p).parse().details.natom`, not `.parse().natom`. See the [API reference](api.md#7-parser-metadata-fields) for the full per-file list.

**Streaming statistics.** `mdout` thermodynamic data (temperature, pressure, density, energy, volume) is accumulated with Welford's online algorithm (`StreamingStats` inside `ThermoStats`), so a multi-gigabyte log is summarized in one pass with O(1) memory.

`ambermeta/coords.py:sniff_coordinate_kind()` sits next to the parsers as a lightweight content-based classifier used by discovery: it reads the file's own header (an ASCII restart/inpcrd has an `NATOM [TIME]` line as line 2; a trajectory doesn't) rather than trusting the extension, which is how `discover` picks the starting structure out of a directory that mixes `.crd`/`.rst`/`.mdcrd` files.

---

## 5. Manifest format v2 and the tolerant reader

**Responsibility:** be liberal in what you accept *within v2*, strict in what you emit. This is still the most important boundary in the codebase — the manifest is the durable artifact users and the GUI both round-trip. The full v2 schema (every key, all `input_coords` sources, `gaps`) is in the [manifest reference](manifest.md); this section covers the mechanics.

### One reader, one format

`ambermeta/manifest.py:_read_raw_manifest` turns a manifest file into its raw container: **YAML or JSON, chosen by extension**, with `${VAR}`/`$VAR` env expansion (which `plan --no-expand-env` turns off). Those are the only two manifest formats in either direction; a `.toml` or `.csv` path is refused before it is parsed:

```
<path>: AmberMeta reads and writes manifests as YAML or JSON only; TOML and CSV are not manifest formats.
```

The rest of `manifest.py` (`_normalize_manifest`, `validate_manifest`) is no longer a file-format concern at all: it normalizes and existence-checks the **in-memory** list of flat stage dicts that `protocol.auto_discover(directory, manifest=[...])` accepts — the shape `_flatten_simulation()` produces (§6), never something read off disk.

`ambermeta/simulation.py:load_simulation(path)` is the one manifest entry point, and it is what every manifest-aware command (`export`, `validate --manifest`, `plan -m`, and the GUI's open) actually calls:

```python
def load_simulation(path: str, expand_env: bool = True) -> Simulation:
    """Load a Simulation from a v2 manifest file."""
    raw = _read_raw_manifest(path, expand_env=expand_env)
    if not isinstance(raw, dict) or "steps" not in raw:
        ...   # rejected — see below
    return payload_to_simulation(raw)
```

The gate is the `steps` key, not the version number, so a hand-edited v2-shaped file without an explicit `version:` still loads. Anything else is rejected outright — there is no second reader and no migration:

```
$ ambermeta plan -m old.yaml
ERROR: old.yaml is not a v2 manifest (no 'steps' key). Rebuild it with `ambermeta discover <dir> --write <path>`.
```

(`export` and `validate --manifest` print the same message behind `ERROR: Failed to load manifest: `. Exit code is `1` either way.) A file that *does* announce itself as v2 — `version: 2`, or a top-level `simulation`/`phases` key — but has no `steps` gets a different message telling its owner to restore the steps rather than rebuild, because rebuilding from the directory would discard the phases and topology pool the file still has.

**Loading never writes.** The file on disk changes only when something explicitly saves (`export -o`, the GUI's Save, `discover --write`).

### Serialization limits

- `write_simulation(sim, path, fmt)` (`fmt` ∈ `{"json", "yaml"}`) is the only manifest writer — **JSON and YAML only**, both lossless. It is what `ambermeta export`, `discover --write`, and the GUI's Save all call.
- There is no flat/legacy writer beside it. `export` emits canonical v2 and nothing else, and a `Simulation` has no lossy serialization to fall out of.
- The one CSV the tool still writes is `plan --stats-csv` — a per-stage *statistics* table from `protocol.write_stats_csv` (§7), not a manifest and not readable back in.

---

## 6. The validation model — how v2 reuses the old engine

**Responsibility:** report whether the reconstructed Simulation holds together, as *notes/findings* — not exceptions.

The v2 validator does not reimplement continuity or per-stage checks; it **flattens a `Simulation` back into the flat stage-dict shape `ambermeta.protocol` already knows how to validate**, then calls the same discovery/validation pipeline the CLI's `--recursive` path uses:

```
Simulation (phases → steps)
        │  core_bridge._flatten_simulation()
        ▼
flat stage dicts (name, role, prmtop, mdin, mdout, mdcrd, inpcrd, gaps, ...)
        │  core_bridge.build_validation_report()
        ▼
protocol.auto_discover(directory, manifest=flat_stages, ...)   # SimulationProtocol
        │
        ▼
per-stage validation + cross-stage continuity (§3)  →  stage_issues / protocol_issues
        │  core_bridge.build_suggestions() + _continuity_gap_suggestions()
        ▼
{ ok, totals, stage_issues, protocol_issues, suggestions }
```

Concretely, `core_bridge.validate_simulation(sim, settings, base_directory)` (called by `validate --manifest`, `plan -m <v2 manifest>`, and the GUI's Validate) does exactly this: flatten, run `auto_discover`, then layer on the v2-specific suggestion kinds — `missing_run` (from `detect_sequence_gaps`, §3), `continuity_gap` (one per genuine, non-`INFO` continuity note, keyed off the engine's own healthy/problem classification rather than text-matching warning strings), and `lineage_group` (an `[applied]` card naming each lineage the document declares, how many runs it holds, and how many runs carry no lineage at all).

Underneath, validation is still two-tiered exactly as before:

- **Per-stage** (`SimulationStage.validate()`): atom-count agreement across the stage's files, box sanity, basic timing/sampling checks. A stage whose files partly failed to parse is flagged `degraded` (`True` when any `FileLoadError` is attached) but still validated on what *did* parse — a corrupt `mdout` never discards a good `prmtop`.
- **Cross-stage** (`SimulationProtocol.validate(cross_stage=True, allow_unexpected_gaps=False)`): the continuity math from §3, run between every consecutive pair.

| Knob | Effect |
|---|---|
| `--skip-cross-stage-validation` (`plan`) → `settings["strict_validation"]` | Whether cross-stage continuity runs at all |
| `--allow-gaps` (`validate --manifest`) → `settings["allow_gaps"]` → `allow_unexpected_gaps` | Whether unconfigured positive gaps are `INFO` (allowed) or a real finding |
| `--strict` (`validate --manifest`) | Promotes findings to a hard validation failure (exit 1) instead of "OK, with N notes" |

That `settings` dict is a **runtime** object, not part of the document: `plan` and `validate` build theirs from the CLI flags alone, the GUI from its Settings panel. A v2 manifest has no `settings` key — `payload_to_simulation` never looks for one — so nothing in the file can turn a check on or off, and `--skip-cross-stage-validation` overrides nothing; it simply switches the continuity checks off for that run.

The upshot: **one continuity engine, one sequence-hole detector, one role classifier** — whether the caller is `plan --recursive` walking a raw directory, `validate --manifest` opening a hand-written v2 file, or the GUI clicking Validate.

---

## 7. Export

**Responsibility:** emit machine-readable records for downstream use. `ambermeta export` (§5) is the manifest path; the flat engine's exports cover the `plan` reports and methods reporting:

| Export | Producer | Contents |
|---|---|---|
| v2 manifest | `simulation.write_simulation()` / `ambermeta export` / `discover --write` | Canonical Simulation → Phase → Step, JSON or YAML |
| Protocol summary | `SimulationProtocol.to_dict()` | `totals` + every stage's full metadata, validation, and continuity (the classic `plan` report, written by `--summary-path`) |
| Methods summary | `SimulationProtocol.to_methods_dict()` | Reproducibility-critical metadata only — software/version, MD engine settings (ensemble, thermostat, barostat, cutoff, constraints), system composition, restraints — with energies and bulk arrays dropped |
| Statistics CSV | `plan --stats-csv` | One row per stage: time range, duration, and temperature/pressure/density/energy as mean ± σ |

`to_methods_dict()` is where residue-name dictionaries (water / protein / nucleic / lipid / ion sets in `legacy_extractors`) classify system composition for the methods section.

---

## 8. Error-handling philosophy

Unchanged by the model rebuild. AmberMeta distinguishes *expected* failures (a missing file, a permission error, a truncated log) from *bugs*. Expected failures never produce a traceback.

- **`FileLoadError`** (a dataclass: `kind`, `path`, `error_type`, `message`) captures a single file's failure. `classify_exception()` maps the underlying exception to an `error_type` — `FileNotFoundError`→`missing`, `PermissionError`→`permission`, `UnicodeDecodeError`→`decode`, everything else→`malformed`. These accumulate on a stage's `load_errors` and surface as validation notes.
- **`AmberMetaError`** is the base for failures the CLI catches and turns into a clean message + exit `1` (no traceback).
- **Fault tolerance is the default.** `plan` and `discover` skip a bad file, record the error, and finish (`exit 0`, or `1` only if nothing at all was found). `--strict` flips the first bad file to a hard `AmberMetaError`.

The result: a run over a messy directory produces a complete, honest report instead of dying on the first surprise.

---

## 9. The GUI bridge — one engine, enforced

The GUI's defining constraint is that it adds **no** domain logic. Every open, save, discover, validate, metadata, and assign operation routes through `ambermeta/gui/api/core_bridge.py`, which is **the only GUI module that imports the core** (`ambermeta.manifest`, `ambermeta.protocol`, `ambermeta.parsers`, `ambermeta.simulation`, `ambermeta.roles`, `ambermeta.topology_pool`, `ambermeta.coords`). The route handlers in `routes.py` are thin; the engine they call is the same one the CLI calls — `discover_draft()` is what both `ambermeta discover` and the GUI's Discover button run, and `validate_simulation()` is what both `ambermeta validate --manifest` and the GUI's Validate panel run.

The server (`gui/server.py`) is **server-authoritative**:

- A singleton `DocumentStore` (`api/document.py`) holds one in-memory document — the current `Simulation`, `base_directory`, `manifest_path`, and `settings`. The frontend is a view of this; it holds no authoritative state.
- **Undo/redo lives on the server.** Every mutation deep-copies the prior state onto a bounded undo stack under a `threading.RLock`; a read takes a locked snapshot.
- **Manifests are written by the same `write_simulation`** the CLI uses — so a GUI **Save** is byte-identical to `ambermeta export`'s output for the same document.

HTTP surface (base `/api`; full request/response shapes in the [GUI guide](gui.md) and [API reference](api.md)):

```
GET  /document                                 open/save/preview/discover state
POST /document/{open,save,preview,discover}
POST /validate
POST /undo | /redo
GET|PUT /settings
POST /topologies                 PUT|DELETE /topologies/{id}
PUT  /simulation/starting-structure
POST /phases                     POST /phases/reorder
PUT|DELETE /phases/{id}          POST /phases/{id}/steps
POST /phases/{id}/steps/reorder
PUT|DELETE /steps/{id}           POST /steps/{id}/move
POST /assign
GET  /files | /files/metadata | /files/raw | /files/related/{stem}
```

Security is built into the boundary, not bolted on:

| Control | Mechanism |
|---|---|
| **No path escape** | `files.resolve_within_base()` resolves every requested path with `realpath` and rejects anything outside `base_directory` (including sibling-prefix tricks); handlers return `403` |
| **SPA can't swallow the API** | The catch-all route 404s unknown `/api/*` paths and refuses `..`/absolute paths before serving `index.html` |
| **No remote origins** | CORS is pinned to `http://localhost:8765` / `http://127.0.0.1:8765`; the server binds `127.0.0.1` by default; single-user, localhost-only |

The frontend (`gui/frontend/`, built into `gui/static/`) is React 18 + TypeScript + Vite + Tailwind, with `@tanstack/react-query` as the single server-state cache and `@dnd-kit` for drag-and-drop. It ships pre-built and offline — no CDN, fonts bundled. See the [GUI guide](gui.md) for the user-facing tour (canvas, inspector, suggestions tray) and the complete endpoint reference.

---

## 10. Contracts worth remembering

These are the invariants the rest of the system (and its tests) depend on:

1. **Three levels, not two.** A Simulation owns a topology pool and a starting structure; a Phase is a role-bearing grouping with no files of its own; a Step binds one topology and declares an explicit `input_coords` source.
2. **`parse().details`** carries the metadata; the wrapper carries `filename`/`warnings`.
3. **One manifest format, read and written.** `load_simulation()` takes a v2 document — YAML or JSON, with or without an explicit `version:` — and anything else is an error, not a conversion; `write_simulation()`/`export` always emits v2 JSON or YAML.
4. **One role classifier (`roles.classify_role`)**, one continuity algorithm, one sequence-hole detector — shared verbatim by the CLI and the GUI; the v2 validator flattens into the same `SimulationProtocol` machinery rather than reimplementing it.
5. **Inference is always announced** — any role, topology kind, or starting structure inferred from content or path shows up as an `INFO` note or a suggestion, never a silent guess.
6. **Failures are data, not crashes** — `FileLoadError` + fault-tolerant `plan`/`discover`; `--strict` to opt into hard failure.
7. **The GUI imports the core only through `core_bridge.py`** — no duplicated logic, byte-identical manifests, server-authoritative state.
