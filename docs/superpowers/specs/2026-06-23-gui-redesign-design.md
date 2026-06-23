# GUI Redesign — Design Spec

**Date**: 2026-06-23
**Status**: Approved (design); pending implementation plans
**Sub-project**: B of 3 (A: core hardening ✅ → **B: GUI redesign** → C: TUI redesign)
**Builds on**: Sub-project A (canonical `ambermeta.manifest`, hardened `ambermeta.protocol`/parsers). Branch `gui-redesign` off `core-hardening`.

## Context

The web GUI (`ambermeta gui`) is a React 18 + TS + Vite + Tailwind SPA over a
~15-endpoint FastAPI backend — a three-pane editor (Files | Stages | Properties)
with drag-and-drop. A read-only map of the current implementation found the
"incomplete / not nice to use" verdict is driven by **architecture**, not polish:

1. **The GUI backend bypasses the canonical core.** `routes.py` re-implements
   export, validation, restart-linking, role inference, and sequence detection
   instead of calling `ambermeta.manifest` / `ambermeta.protocol`. This is the
   CLI/TUI/GUI triplication that causes drift and violates "CLI is source of
   truth" (e.g. GUI export drops CSV gaps/notes; GUI "valid" ≠ CLI valid).
2. **Three competing sources of truth** (server process-global, Zustand mirror,
   panel-local + a client-only undo stack) with no reconciliation. Undo reverts
   only the client while the server keeps stale state → **silent manifest
   corruption** (the single most dangerous defect).
3. **Dead / broken capability:** `/files/metadata` broken (wrong parser API) and
   uncalled; protocol-level validation dead in the UI; sequence grouping has a
   working backend but zero UI; broken responsive layout; per-keystroke save
   storms; broken expand/collapse; stub folder actions.

The backend bootstrap, SPA serving (with A's path-traversal fix), stage CRUD,
settings, Pydantic schemas, and security guards are solid (~60–70% reusable).

## Goals

1. A web GUI with **100% of the functionality** of the CLI/TUI manifest-builder
   workflow, that is **genuinely convenient** to use.
2. **One source of truth:** server-authoritative document; the canonical core is
   the only engine for export/validation/discovery/sequences/restart/HMR.
3. The GUI is a **true manifest editor**: open an existing manifest (any format),
   edit, **Save** writes the canonical manifest — byte-identical to CLI output.
4. Correct, trustworthy **undo** (server-authoritative, includes settings).
5. First-class handling of **large protocols** (50–500+ stages).
6. **Offline-capable desktop** tool (no external CDN; air-gapped HPC friendly).

## Decisions (from brainstorming)

- **Concurrency:** single user, localhost. Server-authoritative single document
  + a lock; multiple tabs view the same document consistently.
- **Persistence:** the document **is** a manifest file. Open/Save real manifests
  via `ambermeta.manifest`; drop the separate session-JSON concept. Explicit
  **Save** (not autosave), with a dirty indicator and unsaved-changes guard.
- **Scale:** large protocols are common → sequence grouping/collapsing and list
  virtualization are first-class requirements.
- **Platform:** desktop-first, offline-capable (bundle all assets). Responsive
  down to laptop. **Tablet/mobile out of scope.**
- **Validation:** full CLI parity via the core (not a lightweight heuristic).
- **Stack:** keep React 18 + TS + Vite + Tailwind (build/serve/CI are sound).

## Non-goals

Multi-user / per-session isolation; tablet/mobile; live file-watching /
websockets; the TUI (Sub-project C). No change to the CLI or core engine beyond
what the GUI needs to call (the core is already hardened in A).

---

## Architecture

### One source of truth: a server-authoritative Document

The backend owns a single in-memory **Document**:

```
Document = {
  protocol: <ordered stages + per-stage files/role/gaps/notes>,
  settings: <global_prmtop, hmr_prmtop, strict_validation, allow_gaps, ...>,
  manifest_path: <the bound file on disk, or None for unsaved>,
  base_directory: <the dir passed to `ambermeta gui`>,
  dirty: <bool>,
}
```

- Guarded by a **lock** so concurrent requests (tab races) can't interleave a
  read-modify-write. Single-user, but correctness-safe.
- All **blocking filesystem work** (recursive discovery, parsing) runs in a
  threadpool (`run_in_executor` / `fastapi.concurrency.run_in_threadpool`), never
  on the event loop.
- **Undo/redo** is a bounded command history on the Document (snapshots or
  inverse-commands covering stages AND settings), exposed via API. The frontend
  never maintains its own undo stack.

### Frontend data flow

- **react-query** owns all server state (the declared-but-unused dep becomes
  real). Every mutation is a mutation hook that invalidates/refetches the
  Document; no parallel client mirror of server data.
- A thin client store (or react-query + local `useState`) holds **UI-only**
  state: current selection, panel sizes (persisted to localStorage),
  expand/collapse, modal state.
- The PropertiesPanel edits a draft and commits on blur/Enter/explicit apply —
  **not per keystroke** — and re-syncs when the underlying stage changes.

---

## B1 — Backend & API contract (build first)

Deliverable: a correct, core-backed API that the frontend builds against.
Testable on its own via pytest hitting the API + asserting core delegation.

### Core delegation (kills the triplication)

| Concern | Today (routes.py) | B1 |
|---|---|---|
| Export | hand-rolled 4 serializers | `ambermeta.manifest.write_manifest` |
| Open/Load manifest | n/a (session JSON) | `ambermeta.manifest.load_manifest` (tolerant) |
| Validation | shallow GUI-local heuristic | build protocol via `ambermeta.protocol` + `validate_manifest`; return protocol-level + per-stage results (continuity, gaps, restart chain, mdout finished, on-disk existence) |
| Sequence detection | re-implemented | `ambermeta.protocol.detect_numeric_sequences` |
| Restart linking | brittle name-stem heuristic | `ambermeta.protocol.auto_detect_restart_chain` |
| Role inference | re-implemented | `ambermeta.protocol.infer_stage_role_*` |
| File metadata | broken (dataclass-as-dict) | parser `.details` (natom/dt/nstlim/box/finished…) |
| HMR topology | manual only | parser `hmr_active` auto-detect (as CLI/TUI now do) |

### API surface (revised contract)

- `GET /api/document` — the whole Document in one call (protocol + settings +
  manifest_path + dirty). Replaces the 3-call initial load.
- `POST /api/document/open` `{path}` — load a manifest file via `load_manifest`,
  validate it parses, set `manifest_path`, return Document. Schema/format errors
  return a clean 4xx (not a raw 500).
- `POST /api/document/save` (`{path?, format?}`) — write the canonical manifest
  via `write_manifest` to `manifest_path` (or a new path = "Save As"); clear
  dirty. Warn when CSV can't represent HMR (consistent with A's CLI behavior).
- `POST /api/document/discover` `{recursive, pattern?}` — auto-discover stages
  from `base_directory` using the core (`smart_group_files` / `auto_discover`
  semantics), including HMR/normal topology split.
- Stage CRUD: keep `GET/POST /api/stages`, `GET/PUT/DELETE /api/stages/{id}`,
  `POST /api/stages/reorder`, `PUT /api/stages/bulk` (dedupe the merge logic into
  one helper). All mutate the Document under the lock and set dirty.
- `POST /api/validate` — full-parity validation (above); returns
  `{ok, stage_issues[], protocol_issues[], totals}`.
- `GET /api/files` — typed file tree; run scan in threadpool; option to include
  non-simulation files so any path is pickable.
- `GET /api/files/metadata` `{path}` — fixed; returns parsed `.details`.
- `GET /api/files/related/{stem}` — keep (used for drag-grouping).
- `GET/PUT /api/settings` — keep; support partial patch.
- `POST /api/undo`, `POST /api/redo` — server command history; return Document.
- Remove the session-save/load JSON endpoints (superseded by open/save manifest).
  No crash-recovery sidecar in scope: the document is the manifest file, with
  explicit Save + a dirty indicator and unsaved-changes guard.

### State & safety
- Module-global Document replaced by a single `Document` instance behind a lock
  in an app-scoped holder (still single-user; the lock fixes tab races).
- All FS/parse work off the event loop (threadpool).
- `open`/`save` confined to within `base_directory` (reuse A's containment
  pattern) to avoid arbitrary read/write.

---

## B2 — Frontend rebuild (build on B1's contract)

Deliverable: the new GUI; fresh production bundle committed to
`ambermeta/gui/static`; passes `gui-static-check` CI.

### Layout & shell
- Three-pane desktop layout: **Files | Stages | Properties**, resizable, panel
  sizes persisted. Responsive down to laptop widths (single graceful breakpoint);
  no tablet/mobile.
- Top bar: Open / Save (dirty indicator) / Validate / Discover / Undo-Redo /
  Export. Unsaved-changes guard on close/navigation.

### State
- react-query for all server state; mutation hooks per action; optimistic where
  safe, else refetch. No Zustand mirror of server data. UI-only state local.
- Undo/Redo buttons call the server endpoints; the view reflects the returned
  Document. (No client-side undo stack.)

### Key feature surfaces (the "100% + convenient" wins)
1. **File-metadata preview** — selecting/hovering a file shows natom, dt, nstlim,
   box, finished, etc. (from the fixed endpoint), so files are assigned with
   confidence. Inline preview when assigning to a stage slot.
2. **Validation panel** — a Validate action runs full CLI-parity validation and
   shows a protocol-level pass/fail summary + per-stage issues with
   **jump-to-issue**; continuity/gap/restart-chain problems surfaced.
3. **Sequence grouping + virtualization** — numbered runs (`prod_001..050`)
   render as collapsible groups; the stage list is virtualized so large protocols
   stay responsive. Group-level actions (set role for the whole sequence).
4. **File picker everywhere** — global/HMR prmtop, initial coords, per-stage
   files, open/save: all use a tree/browser picker, not raw-text inputs. Drag
   from the file tree still works and is discoverable.
5. **HMR auto-detection** — on discover/assign, classify normal vs HMR topology
   via the core; user can override.
6. **Visible restart-linking** — a manual "Re-link restarts" action plus clear
   indication of what was linked (which inpcrd feeds which stage); driven by the
   core heuristic.
7. **Open / Save real manifests** in any format; Save writes canonical output.

### Design system (addresses "not nice to use")
- Bundled fonts (no Google CDN — air-gapped friendly); a deliberate, documented
  palette and spacing/density suited to a dense scientific data tool; consistent
  components (buttons, inputs, badges, panels). Detailed visual design is done at
  build time with the frontend-design skill, guided by this spec.

---

## Testing strategy

- **B1 (backend):** pytest hitting the FastAPI app via `TestClient`:
  open/save round-trip a real manifest (== `write_manifest` output); validation
  matches the core (`validate_manifest`/protocol) on fixtures incl. a
  continuity/gap failure; `/files/metadata` returns real `.details`; discover
  splits HMR/normal; reorder/CRUD under the lock; threadpool offloading;
  containment of open/save paths. Assert the GUI no longer re-implements engine
  logic (delegation tests).
- **B2 (frontend):** component/integration tests (Vitest + Testing Library) for
  the document model, validation panel, sequence grouping, file picker, undo via
  server; a built bundle that passes `gui-static-check`. Keep CI green.
- Cross-cutting: a GUI-export ↔ CLI-read round-trip test proving parity.

## Backward compatibility / scope

- Public Python API and the CLI are unchanged. The `ambermeta gui` entry point
  and `run_gui` signature stay (it still serves a built bundle on localhost).
- The on-disk artifact is now the canonical manifest (an improvement); the old
  session-JSON format is dropped (the GUI was the only producer).

## Risks

- **Frontend rebuild scope** — mitigated by building on a correct B1 contract and
  porting the worthwhile pieces (dnd-kit interactions, TS types, presentational
  components) rather than starting literally from zero.
- **Large-protocol performance** — mitigated by virtualization + grouping from
  the start.
- **Core integration edge cases** — mitigated by delegation tests that pin GUI
  behavior to the core.

## Decomposition & sequencing

One spec (this document), **two implementation plans**, built in order:
- **B1 — Backend & API contract** (core delegation, document/state model, fixed
  endpoints, full-parity validation). Independently testable.
- **B2 — Frontend rebuild** (on B1's contract; new design system; the feature
  surfaces above; fresh bundle).

Each gets its own writing-plans → subagent-driven execution → review cycle.

## Acceptance criteria

1. GUI export is byte-identical to `ambermeta` CLI for yaml/json/toml/csv
   (no data loss), via `write_manifest`.
2. GUI validation matches the CLI (continuity/gaps/restart/finished/existence),
   surfaced at protocol and per-stage level with jump-to-issue.
3. Open → edit → Save round-trips a real manifest; the document is the file.
4. Undo/redo is server-authoritative and never desyncs (covers settings).
5. `/files/metadata` returns real parsed details; file preview works.
6. Large protocols (≥100 stages) remain responsive (grouping + virtualization).
7. No external CDN dependency; runs offline.
8. One engine: GUI delegates export/validation/discovery/sequences/restart/HMR
   to the core (delegation tests prove it); no re-implementation in `routes.py`.
9. Full test suite + `gui-static-check` green; fresh bundle committed.
