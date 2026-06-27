# Architecture

**AmberMeta is one engine with two faces.** A single core — parsers, a manifest contract, protocol assembly, and a validation model — does all the work. The CLI and the GUI are thin presentation layers over that core; neither contains domain logic the other lacks. This document is the map of that core: what each layer is responsible for, where the boundaries are, and the contracts that hold them together.

> **Audience:** contributors, and users who want to understand *why* a result looks the way it does. For task-oriented usage, start with the [tutorials](tutorials.md); for exact signatures, the [API reference](api.md).

---

## 1. Package layout

```
ambermeta/
  __init__.py            # public re-exports (the supported import surface)
  cli.py                 # argparse front end: plan / init / validate / info / gui / completion
  errors.py              # AmberMetaError, FileLoadError, classify_exception
  protocol.py            # SimulationStage, SimulationProtocol, ProtocolBuilder, discovery + assembly
  manifest.py            # tolerant reader + canonical writer; STAGE_FILE_KINDS, CSV_COLUMNS
  utils.py               # MetadataBase, shared helpers
  parsers/               # thin per-file wrappers (PrmtopParser, MdinParser, ...)
  legacy_extractors/     # the actual byte-level parsing → *Metadata dataclasses
  gui/
    server.py            # FastAPI app, run_gui(), CORS + static SPA serving
    api/
      core_bridge.py     # the ONLY GUI module that imports the core
      document.py        # server-authoritative Document + DocumentStore (undo/redo)
      files.py           # directory scan + resolve_within_base containment
      routes.py          # HTTP handlers (thin; delegate to the store + bridge)
      schemas.py         # Pydantic request/response models
    static/              # pre-built, committed frontend bundle (offline)
    frontend/            # React + TS + Vite source for static/
```

The dependency arrows point one way: `cli` and `gui` depend on the core (`protocol`, `manifest`, `parsers`, `errors`); the core depends on nothing above it. `legacy_extractors` is a leaf — it knows file formats and nothing about protocols.

---

## 2. Data flow

The same pipeline runs whether the entry point is `ambermeta plan`, `load_protocol_from_manifest()`, or a GUI **Validate** click:

```
 directory or manifest
        │
        ▼
 ┌──────────────┐   per file
 │  discovery   │   smart_group_files → detect_numeric_sequences
 │  / manifest  │   (group loose files into stage stems, order them)
 └──────┬───────┘
        ▼
 ┌──────────────┐   PrmtopParser/MdinParser/... → .details (legacy *Metadata)
 │   parsing    │   failures captured as FileLoadError, not exceptions
 └──────┬───────┘
        ▼
 ┌──────────────┐   build SimulationStage per group; infer role; link restarts
 │  assembly    │   → SimulationProtocol (ordered stages)
 └──────┬───────┘
        ▼
 ┌──────────────┐   per-stage checks + cross-stage continuity (gaps, restart chain)
 │  validation  │   notes attached to each stage (INFO / WARNING)
 └──────┬───────┘
        ▼
 ┌──────────────┐   to_dict / to_methods_dict / stats CSV / canonical manifest
 │   export     │
 └──────────────┘
```

Each box is a layer below.

---

## 3. Parsing layer

**Responsibility:** turn one file on disk into a typed metadata object, or a structured error — never an unhandled exception.

The split is deliberate:

- **`ambermeta/parsers/`** holds thin wrapper classes (`PrmtopParser`, `MdinParser`, `MdoutParser`, `MdcrdParser`, `InpcrdParser`). Each exposes `__init__(filename)` and `parse()`. `parse()` returns a small dataclass (`PrmtopData`, `MdinData`, …) that extends `MetadataBase` and therefore always carries `filename: str` and `warnings: List[str]`.
- **The parsed payload lives on `.details`** — e.g. `PrmtopParser(path).parse().details` is a `legacy_extractors.prmtop.PrmtopMetadata`. This two-level shape (wrapper + `.details`) keeps the stable, uniform interface (`filename`/`warnings`) separate from the rich, file-specific field set.
- **`ambermeta/legacy_extractors/`** does the real work: reading the binary/ASCII formats and populating the `*Metadata` dataclasses (`PrmtopMetadata`, `MdinMetadata`, `MdoutMetadata`, `TrajectoryMetadata`, `InpcrdMetadata`). These are the field names users see in `info` output and in `.details`.

> ⚠️ **The most common documentation/usage error.** The metadata fields are on `.details`, not on the object returned by `parse()`. Write `PrmtopParser(p).parse().details.natom`, not `.parse().natom`. The field names are also AMBER-flavored: `natom`/`nres` on prmtop, `natoms` on mdout/inpcrd, `temp_control`/`press_control`/`stage_role` on mdin, `hmr_active` (not `is_hmr`), `residue_composition` (not `residue_counts`). See the [API reference](api.md#6-parser-metadata-fields) for the full per-file list.

**Streaming statistics.** `mdout` thermodynamic data (temperature, pressure, density, energy, volume) is accumulated with Welford's online algorithm (`StreamingStats` inside `ThermoStats`), so a multi-gigabyte log is summarized in one pass with O(1) memory. The result exposes `count`, `time_start`/`time_end`, and mean ± σ per quantity.

---

## 4. The manifest contract

**Responsibility:** be liberal in what you accept, strict in what you emit. This is the most important boundary in the codebase, because the manifest is the durable artifact users and the GUI both round-trip.

`ambermeta/manifest.py` implements a **tolerant reader** and a **canonical writer**:

| Direction | Function | Behavior |
|---|---|---|
| Read | `load_manifest(path, expand_env=True)` | Detects format by extension (YAML / JSON / TOML / CSV), parses, expands `${VAR}`/`$VAR`, and normalizes every stage entry |
| Normalize | `normalize_stage_keys(entry)` | Maps legacy aliases to canonical keys: `stage`→`name`, `role`→`stage_role`, flat `expected_gap_ps`/`gap_tolerance_ps`→ a nested `gaps` dict |
| Write | `write_manifest(payload, path, fmt)` | Emits one deterministic form in `json` / `yaml` / `toml` / `csv` |
| Check | `validate_manifest(manifest, directory, strict)` | Confirms referenced files exist (raise vs. record per the `strict` flag) |

Two constants pin the schema:

- `STAGE_FILE_KINDS = ("prmtop", "mdin", "mdout", "mdcrd", "inpcrd")` — the only file slots a stage recognizes.
- `CSV_COLUMNS` — the canonical CSV header (`name, stage_role, prmtop, mdin, mdout, mdcrd, inpcrd, expected_gap_ps, gap_tolerance_ps, notes`).

**Why "tolerant in, canonical out" matters:** a user can hand-write a terse mapping in YAML, the GUI can load it, and on save it becomes the canonical form — byte-identical to what `ambermeta init --auto` would have written. There is exactly one on-disk representation to diff, review, and regression-test against. The reader's flexibility never leaks into the writer's output.

The full schema (all formats, gap shapes, `settings`, `stage_role_rules`, env expansion) is in the [manifest reference](manifest.md).

---

## 5. Protocol assembly

**Responsibility:** turn a pile of files (or a manifest) into an *ordered* `SimulationProtocol` of `SimulationStage`s. This lives in `ambermeta/protocol.py`.

The discovery path (`auto_discover`, used by `plan --recursive` and the GUI **Discover**) runs:

1. **Group** — `smart_group_files()` buckets files by stem (filename minus extension), assigning each to its `STAGE_FILE_KINDS` slot. **One file group becomes one stage**, uniformly for every role; numbered runs are *not* collapsed.
2. **Sequence-detect** — `detect_numeric_sequences()` recognizes families like `ntp_prod_0000 … ntp_prod_0005` (underscore/dot/hyphen/bare-digit suffixes), so they sort numerically and carry a "item *n* of *m*" note.
3. **Role-infer** — when `stage_role` is absent, `infer_stage_role_from_content()` reads the parsed `mdin`/`mdout` first (ensemble, temperature schedule, `maxcyc` vs `nstlim`); the path name is a fallback. Every inference is recorded as an `INFO` note — AmberMeta never silently guesses.
4. **Link restarts** — with `auto_detect_restarts=True`, `auto_detect_restart_chain()` matches each stage's `inpcrd` to the previous stage by atom count, time continuity, and sequence order.

The manifest path (`load_protocol_from_manifest`) skips discovery and takes the stage list as given, but runs the same parsing, role-inference fallback, restart linking, and validation.

`ProtocolBuilder` is the fluent equivalent for programmatic callers — `from_directory`/`from_manifest`, `with_grouping_rules`, `with_pattern_filter`, `with_stage_tolerance`, `auto_detect_restarts`, `add_stage`, `build` — composing the same primitives.

> **Invariant — HMR.** `HMR_TIMESTEP_THRESHOLD_PS = 0.003`: a timestep ≥ 3 fs is treated as evidence of hydrogen-mass repartitioning. Topology HMR is detected independently from atom masses (`hmr_active`), with a fallback to atom-name patterns when the `ATOMIC_NUMBER` section is absent. The two signals together drive HMR-topology classification.

---

## 6. Validation model

**Responsibility:** report whether the reconstructed protocol holds together, as *notes* — not exceptions.

Validation is two-tiered:

- **Per-stage** (`SimulationStage.validate()`): atom-count agreement across the stage's files, box sanity, basic timing/sampling checks. A stage whose files partly failed to parse is flagged `degraded` (the `degraded` property is `True` when any `FileLoadError` is attached) but still validated on what *did* parse — a corrupt `mdout` never discards a good `prmtop`.
- **Cross-stage** (`SimulationProtocol.validate(cross_stage=True, allow_unexpected_gaps=False)`): continuity between consecutive stages — the timing gap (observed vs. `expected_gap_ps` within `gap_tolerance_ps`) and restart→trajectory linkage.

Outcomes are attached to each stage as human-readable notes tagged `INFO` or `WARNING`; a protocol with continuity notes is reported as *valid, with N notes* rather than as a silent clean pass. Two knobs adjust strictness:

| Knob | Effect |
|---|---|
| `settings.strict_validation` / `--skip-cross-stage-validation` | Whether cross-stage continuity runs at all |
| `settings.allow_gaps` / `allow_unexpected_gaps` | Whether unconfigured positive gaps are `INFO` (allowed) or `WARNING` |

---

## 7. Export

**Responsibility:** emit machine-readable records for downstream use.

| Export | Producer | Contents |
|---|---|---|
| Protocol summary | `SimulationProtocol.to_dict()` | `totals` + every stage's full metadata, validation, and continuity |
| Methods summary | `SimulationProtocol.to_methods_dict()` | Reproducibility-critical metadata only — software/version, MD engine settings (ensemble, thermostat, barostat, cutoff, constraints), system composition, restraints — with energies and bulk arrays dropped |
| Statistics CSV | `plan --stats-csv` | One row per stage: time range, duration, and temperature/pressure/density/energy as mean ± σ |
| Canonical manifest | `manifest.write_manifest()` | The protocol as an editable, round-trippable manifest |

`to_methods_dict()` is where residue-name dictionaries (water / protein / nucleic / lipid / ion sets in `legacy_extractors`) are used to classify system composition for the methods section.

---

## 8. Error-handling philosophy

AmberMeta distinguishes *expected* failures (a missing file, a permission error, a truncated log) from *bugs*. Expected failures never produce a traceback.

- **`FileLoadError`** (a dataclass: `kind`, `path`, `error_type`, `message`) captures a single file's failure. `classify_exception()` maps the underlying exception to an `error_type` — `FileNotFoundError`→`missing`, `PermissionError`→`permission`, `UnicodeDecodeError`→`decode`, everything else→`malformed`. These accumulate on a stage's `load_errors` and surface as validation notes.
- **`AmberMetaError`** is the base for failures the CLI catches and turns into a clean message + exit `1` (no traceback).
- **Fault tolerance is the default.** `plan` skips a bad file, records the error, and finishes (`exit 0`). `--strict` flips the first bad file to a hard `AmberMetaError`.

The result: a run over a messy directory produces a complete, honest report instead of dying on the first surprise.

---

## 9. The GUI bridge — one engine, enforced

The GUI's defining constraint is that it adds **no** domain logic. Every open, save, discover, validate, metadata, and restart-link operation routes through `ambermeta/gui/api/core_bridge.py`, which is **the only GUI module that imports the core** (`manifest`, `protocol`, `parsers`). The route handlers in `routes.py` are thin; the engine they call is the same one the CLI calls.

The server (`gui/server.py`) is **server-authoritative**:

- A singleton `DocumentStore` (`api/document.py`) holds one in-memory `Document` — `base_directory`, `manifest_path`, an ordered list of stage dicts, and `settings`. The frontend is a view of this; it holds no authoritative state.
- **Undo/redo lives on the server.** Every mutation deep-copies the prior state onto a bounded undo stack (limit 100) under a `threading.RLock`; a read takes a locked snapshot. `replace()` (used by open/discover) optionally resets history.
- **Manifests are written by the same `write_manifest`** the CLI uses — so a GUI **Save** is byte-identical to the CLI's output (the `gui-static-check` and round-trip parity are part of the project's guarantees).

Security is built into the boundary, not bolted on:

| Control | Mechanism |
|---|---|
| **No path escape** | `files.resolve_within_base()` resolves every requested path with `realpath` and rejects anything outside `base_directory` (including sibling-prefix tricks); handlers return `403` |
| **SPA can't swallow the API** | The catch-all route 404s unknown `/api/*` paths and refuses `..`/absolute paths before serving `index.html` |
| **No remote origins** | CORS is pinned to `http://localhost:8765` / `http://127.0.0.1:8765`; the server binds `127.0.0.1` by default |

The frontend (`gui/frontend/`, built into `gui/static/`) is React 18 + TypeScript + Vite + Tailwind, with `@tanstack/react-query` as the single server-state cache and `@dnd-kit` for drag-and-drop. It ships pre-built and offline — no CDN, fonts bundled. See the [GUI guide](gui.md) for the user-facing tour and the complete endpoint table.

---

## 10. Contracts worth remembering

These are the invariants the rest of the system (and its tests) depend on:

1. **`parse().details`** carries the metadata; the wrapper carries `filename`/`warnings`.
2. **Tolerant reader, canonical writer** — the manifest writer emits exactly one form; the reader's leniency never reaches it.
3. **One file group → one stage**, identically for every role; numbered sequences are preserved, not collapsed.
4. **Inference is always announced** — any role inferred from content or path adds an `INFO` note.
5. **Failures are data, not crashes** — `FileLoadError` + fault-tolerant `plan`; `--strict` to opt into hard failure.
6. **The GUI imports the core only through `core_bridge.py`** — no duplicated logic, byte-identical manifests, server-authoritative state.
