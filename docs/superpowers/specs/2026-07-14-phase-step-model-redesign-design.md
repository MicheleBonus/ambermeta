# AmberMeta — Phase/Step Model Redesign (GUI + Core + CLI)

- **Date:** 2026-07-14
- **Status:** Design — awaiting user review
- **Author:** Michele Bonus (michele.bonus@gmail.com), with Claude
- **Supersedes / builds on:** `docs/superpowers/specs/2026-06-23-gui-redesign-design.md` (the shipped v1 3-pane GUI)
- **Kind:** Ground-up rebuild of how AmberMeta *models*, *detects*, and *presents* a simulation. Full core change (data model + manifest + CLI), not a GUI patch.

---

## 1. Motivation

The shipped v1 GUI is functional but unintuitive, and the root cause is structural, not cosmetic:

**The data model is two levels deep; users think in three.** Today a `SimulationProtocol` holds an ordered list of `SimulationStage`, where a "stage" is **one run** (one `mdin` + its `mdout`/trajectory/restart + one `prmtop`). There is no entity that groups runs into a *phase* (minimization, heating, equilibration, production). A numbered production series `prod_001…prod_050` is stored as 50 sibling stages, and the GUI's "group by stem" is an after-the-fact attempt to visually re-collapse them. Users experience this as: selecting a file offers no action, the centre panel's clustering is opaque, there is no visual sequence, and topology/coordinate assignment is exposed only as free-text override fields.

**A correctness audit (2026-07-14) of the file-handling substrate** surfaced 38 verified defects (1 high, 16 medium, 21 low after adversarial verification). Five clusters directly undermine the features this redesign introduces (see §7). Because we are changing the model anyway, we fix the substrate at the same time.

This spec defines the **target state** (model + manifest + API + GUI + CLI) and decomposes it into sequenced implementation plans P1–P4. The design was validated interactively with the maintainer (decisions logged in §10).

## 2. Scope & non-goals

**In scope**
- A three-level domain model: **Simulation → Phase → Step**, with a Simulation-owned **topology pool** and **starting structure**.
- A **manifest format v2** that persists the model, plus a tolerant reader that auto-migrates v1 flat manifests.
- API contract changes for phases, steps, the topology pool, discover-as-draft, and a suggestions surface.
- A rebuilt GUI: continuous-timeline canvas, file-panel actions, a full-detail file inspector, and a draft-first suggestions tray.
- CLI parity with the new structure.
- The audit's five correctness clusters (P1 requirements) + a tracked robustness fix-list.

**Non-goals**
- No new science: we surface metadata the parsers already extract; we do not add force-field/energy computation.
- No tablet/mobile or multi-user/cloud: single-user localhost desktop, offline bundle (unchanged from v1).
- We do not preserve the v1 GUI component structure; the frontend is rebuilt against the new API.
- No change to the CLI's headless/scriptable contract beyond what the new model requires.

## 3. Target domain model

Three levels. Terminology matches the user's mental model.

### 3.1 Simulation (the document / top level)
Owns everything that describes the *starting system* and is shared across the run:
- **Topology pool** — an ordered list of 1..N topologies. Each entry: an id, a path, and a **kind** (`normal` | `hmr`), detected from the file but user-overridable. The pool replaces v1's two settings fields (`global_prmtop`, `hmr_prmtop`) and must support **more than two** topologies and **distinct chemical systems** (audit cluster 4).
- **Starting structure** — one coordinate file (the initial coordinates from tleap, e.g. `.inpcrd`/`.rst7`/content-sniffed `.crd`). Feeds the first step's input. Replaces the runtime-only, UI-less `initial_coordinates`.

### 3.2 Phase (the new middle container)
An ordered, named container grouping contiguous steps (Minimization, Heating, Equilibration, Production…). Fields: id, name, **role** (canonical token: `minimization` | `heating` | `equilibration` | `production` | `""`), and order. A phase is **first-class and persisted** (so a manual arrangement survives save/reopen), but it is **not** a topology *storage* level — see 3.4.

### 3.3 Step (one run — today's `SimulationStage`)
The atomic run inside a phase. Fields: id, phase reference, order-within-phase, a **topology binding** (a reference into the pool), an **input-coordinates source**, the run's `mdin`/`mdout`/`mdcrd`, expected/observed gap, notes, load errors. A step is what today's `SimulationStage` already is; the change is that it *references* a pooled topology instead of storing an arbitrary prmtop path, and it *belongs to* a phase.

### 3.4 Topology & coordinate assignment (inheritance with override)
- Topologies are **owned by the Simulation** (the pool).
- The **binding** — which pooled topology a run uses — is **per-step**, because that is the granularity Amber runs at and the only way some runs use `normal` and others `hmr`.
- **Phase is a convenience, not storage:** the UI can "set topology for every step in this phase" in one action and displays the effective value (or "mixed"). This writes to the member steps; the phase stores no topology of its own.
- **Input coordinates resolve by source:** the **first step** ← the Simulation starting structure; **every later step** ← the previous step's output restart (the continuity chain); any step may override to an explicit path. This makes the continuity anchor explicit and fixes audit cluster 3.

### 3.5 Continuity
Continuity is the chain `previous step's output restart → current step's input coordinates`. Because the input-coordinates *source* is now explicit (previous step vs. starting structure vs. override), continuity no longer has to guess from a same-stem restart's timestamp (audit cluster 3, finding #10). Gap = current-input-time − previous-output-end-time, with a **frame-interval-based tolerance** (not one scaled to absolute elapsed time). Sequence-hole detection (a missing `prod_002`) is a first-class continuity check.

## 4. Manifest format v2

The manifest is the shared CLI↔GUI contract; v2 persists the model. **Concrete shape (field names finalised in the P1 plan):**

```yaml
version: 2
simulation:
  topologies:
    - id: top_wt
      path: wt.prmtop
      kind: normal          # detected (mass-based), overridable
    - id: top_wt_hmr
      path: wt_hmr.prmtop
      kind: hmr
  starting_structure: wt.inpcrd
phases:
  - { id: ph_min,  name: Minimization,  role: minimization, order: 0 }
  - { id: ph_prod, name: Production,     role: production,   order: 3 }
steps:
  - id: st_min
    phase: ph_min
    order: 0
    topology: top_wt                        # reference into the pool
    input_coords: { source: starting_structure }
    mdin: min.in
    mdout: min.out
    gaps: { expected: null, tolerance: null }
  - id: st_prod_001
    phase: ph_prod
    order: 0
    topology: top_wt_hmr
    input_coords: { source: step, ref: st_equil_2 }   # or { path: "..." }
    mdin: prod_001.in
    mdout: prod_001.out
    mdcrd: prod_001.nc
```

**Backward compatibility (tolerant reader, auto-migration).** Opening a v1 manifest (a bare `stages:` list or `{stages:[...]}` with `global_prmtop`/`hmr_prmtop`) auto-migrates in memory: each stage → a step; steps are grouped into phases by their (re-inferred, canonical) role; `global_prmtop`/`hmr_prmtop` → pool entries; `initial_coordinates` → starting structure. Saving writes v2. Old manifests keep opening; the CLI reads v2 natively and can still emit a flat/legacy view where a downstream tool needs it.

Formats remain YAML/JSON/TOML/CSV (CSV is a lossy flat export, documented as such).

## 5. API contract changes

Server-authoritative `Document` + single react-query cache + mutation funnel + server-side undo/redo are retained from v1. New/changed operations:

- **Topology pool:** `POST/DELETE` pool entries; `PATCH` an entry's kind/label; `GET` the pool. `set starting_structure`.
- **Phases:** create, rename, set role, reorder, delete (with a policy for its steps: reassign or delete).
- **Steps:** create, delete, **move between phases**, reorder within a phase, set topology binding (pool ref), set input-coords source, set files/gaps/notes.
- **Assignment is unified:** a single "assign file to (target, role/slot)" concept so the file panel can route a path to the pool, the starting structure, a phase default (cascade), or a specific step slot — replacing v1's split between `PUT /stages/{id}` and `PUT /settings`.
- **Discover-as-draft:** discovery returns a complete proposed Simulation (pool + starting structure + phases + steps + suggested defaults + suggestions list) as an editable draft that is applied immediately (draft-first) rather than silently replacing state.
- **Suggestions:** an endpoint (or an enrichment of the document/validation payload) returning the structured suggestion cards (grouping, missing sequence member, continuity gap, topology confirmation, restart-link results, role guesses), each carrying the **signal/evidence** string that produced it.
- **File detail:** `GET /files/metadata` returns the *full* parsed `details` (already computed; stop truncating). Add a small path-guarded **raw-head read** endpoint for the "Raw file" tab.

## 6. GUI / UX design

Validated via interactive mockups. Four pillars.

### 6.1 Canvas — continuous timeline, phases as sections (chosen: Option A)
The centre is one vertical spine = the whole simulation in run order. Phase headers divide it into labelled sections. **The arrow between two steps is the restart→input handoff**; a gap is a broken amber arrow with its magnitude; a missing sequence member shows as a dashed ghost node. Long numbered runs collapse to one expandable band. Everything is drag-to-rearrange at both levels (reorder steps within/across phases; reorder phases). The Simulation header carries the topology pool and starting-structure slot; each step shows its bound topology (▸) and its input-coords source (◂); phase headers show the cascade default (or "mixed").

### 6.2 File panel — select a file and act on it
Left pane. Each row is read on sight and shows what the file *is* plus a data-driven suggestion hint ("looks like your HMR topology", "looks like the starting structure"). Selecting a file drives a contextual **Inspector** offering only role-appropriate **Assign** actions with the detected one marked as the one-click default: a prmtop → *add to pool as HMR / normal*, *set as phase default*, *assign to a step*; a coordinate file → *set as starting structure*, *assign as a step's input*, *treat as trajectory*; an mdin → *create a step* (role from content). Drag-and-drop remains as an alternative.

### 6.3 Inspector — Peek + full detail on click
The Inspector shows a curated **Peek** and a tabbed **Full details** view (*Overview · Full details · Raw file · Warnings*) that surfaces the *entire* parsed payload grouped by category (Identity, System, Box & environment, Composition, HMR; per-kind: the full `&cntrl` table for mdin, run stats for mdout, frames/time/Δt for trajectories) plus a real raw-file head view. This is surfacing already-parsed data, not new parsing.

### 6.4 Suggestions — draft-first, all marked, explainable
Confident guesses are applied immediately to the canvas (marked, dismissable, global undo). A **Suggestions surface** (right pane) splits into **"Needs you"** (missing runs, topology confirmation, continuity gaps — with Accept/Adjust/Ignore) and **"Applied — review"** (grouping, restart linking, starting structure, roles — dismissable). **Every card shows the signal it came from** (`dt=0.004 ⇒ HMR`; `inpcrd.time 120 − prev end 100 = +20 ps`; `sequence 001, 003…050 → 002 absent`).

## 7. Correctness requirements from the audit

These are **P1 requirements**, not follow-ups. Full findings: workflow run `wf_84efb726-65e` (2026-07-14). Five redesign-critical clusters:

1. **Unified role classifier.** Today three guessers diverge (GUI `infer_stage_role_from_path`, CLI `_suggest_stage_role`, content `infer_stage_role_from_content`), the content heuristics are unreachable dead code, and `stage_role` is stored as verbose prose that breaks `--include-roles`. → One shared, content-aware classifier emitting the canonical tokens, used by GUI *and* CLI, with word-boundary matching (kills `minor`→minimization and `prod/run`→"").
2. **`.crd` + shared-coordinate handling.** `.crd` is hard-mapped to trajectory (a tleap starting structure can never become the initial coords); stem grouping turns a shared `system.inpcrd` into a phantom "system" stage and leaves `min` with no inpcrd. → Content-sniff `.crd`; treat a shared/lone inpcrd as the sim starting structure; fix grouping.
3. **Continuity anchoring.** Gaps computed from `inpcrd.time` mis-fire when a same-stem *output* restart is grouped as a step's input (fabricates a stage-duration gap); the tolerance scales with absolute elapsed time (hides real gaps in long runs); sequence holes are never detected. → Explicit input-coords source (§3.4); frame-interval tolerance; sequence-hole detection.
4. **Topology pool.** `classify_topologies` collapses multiple distinct systems into one global prmtop. → A real labeled pool of N topologies (§3.1).
5. **HMR auto-default threshold.** Auto-assign HMR at `dt > 0.002` (manual: non-HMR maxes at 0.002), not `dt ≥ 0.003`.

**Robustness fix-list (medium/low — fold into P1 as substrate hardening):**
- *prmtop labels:* vacuum mislabeled "Implicit Solvent" (RADIUS_SET ubiquitous) → report Periodic/Explicit vs Non-periodic; protein+ligand never labeled "Ligand" (dead `elif`); ions without a charge sign misread as ligands; neutrality computed from incomplete CHARGE data; LEaP-time box reported as if current (add caveat); deuterium (2.014) false HMR / atom-name fallback misclassifies He.
- *inpcrd/restart:* NetCDF autodetect matches a bare 3-byte `CDF` prefix → use full classic magic (`CDF\x01/\x02`) + HDF5 (`\x89HDF`); a stray trailing blank line can fabricate a periodic box from a coordinate line → count non-blank lines and guard box detection with `_looks_like_box`.
- *mdout/mdcrd:* barostat named from `ntp` (scaling geometry) instead of the `barostat` keyword; minimization mdout mislabeled MD (legacy summarizer); a NetCDF `AMBERRESTART` file misrouted to the trajectory parser throws an uncaught `TypeError`; trajectory autodetect CDF-only; ASCII trajectories report `n_frames=0`; REMD detection only T-REMD.
- *kinds:* extensionless canonical Amber defaults (`prmtop`,`inpcrd`,`mdin`,`mdout`,`mdcrd`,`restrt`) classify as OTHER and become invisible → basename fallback; `.trj` unclassified; two same-stem same-kind files silently overwrite; generic `.in`/`.out` greedily claimed.

(3 findings — OPC3-pol water HMR false-positive, a `tempi`/`ntx` heating claim, a coverage fencepost — were refuted on verification and are not carried.)

## 8. Decomposition into implementation plans

One shared design, four sequenced plans (each its own spec-detail → plan → implement cycle, mirroring the v1 A→B rhythm):

- **P1 — Core + manifest.** The Sim→Phase→Step model and topology pool in `protocol.py`/`manifest.py`; manifest v2 + tolerant auto-migration; the unified role classifier; continuity rework (explicit input source, frame-interval tolerance, sequence holes); topology-pool classification; and the parser robustness fix-list. **Includes regression fixtures for every audit failure case.**
- **P2 — API contract.** Schemas + endpoints for the pool, phases, steps (incl. move-between-phases), unified assignment, discover-as-draft, and the suggestions surface; server-authoritative undo for all new mutations.
- **P3 — GUI.** Canvas A (timeline + arrows + drag-drop at both levels), file-panel actions, the Peek/Full-details/Raw inspector, and the draft-first suggestions tray. Rebuilt against P2.
- **P4 — CLI.** Teach `init/discover/plan/validate/export` + completion + docs the new structure (the unified classifier from P1 is already shared). Can trail or interleave with P1.

Sequencing: **P1 → P2 → P3**, with **P4** following P1 (CLI depends only on core). Each plan is reviewed before the next begins.

## 9. Testing strategy

- **Model & migration:** unit tests for the three-level model; round-trip v2 read/write; **v1→v2 auto-migration** fixtures (flat list, `{stages:[...]}`, global+hmr prmtop, initial_coordinates).
- **Parser robustness:** a fixture per audit failure case (e.g. HDF5-magic restart, trailing-blank-line inpcrd, NetCDF `AMBERRESTART`, `.crd` single-frame vs multi-frame, extensionless defaults, `ntp=2`/`barostat=2`).
- **Classifier parity:** a property/table test asserting GUI and CLI produce **identical** roles for the same inputs (the cluster-1 regression), including recursive `min/heat/equil/prod` trees.
- **Continuity:** contiguous same-stem-restart chain produces **no** false gap; long-run small gap is **not** snapped to zero; a missing sequence member is flagged.
- **API:** endpoint tests for pool/phase/step CRUD, move-between-phases, discover-as-draft, undo/redo.
- **Frontend:** component + interaction tests (drag reorder within/across phases, assign-from-inspector, suggestion accept/dismiss), reusing v1's Vitest setup.
- Full suite green (Python + Vitest) is the bar for each plan, as in v1.

## 10. Design decisions (logged)

1. **Level model = Sim → Phase → Step.** Step = one run (today's stage); Phase = new middle container; Sim = document. *(user-confirmed)*
2. **Topology = sim-owned pool (1..N, normal/HMR labeled); step binds one; phase is a cascade convenience, not storage; starting structure is sim-level and feeds step 1; later steps ← previous restart.** *(user-confirmed, incl. multi-prmtop rationale)*
3. **Change depth = full core rebuild** (model + manifest + CLI), with a tolerant auto-migrating reader. *(user-chose over GUI-only / hybrid)*
4. **Suggestions = draft-first, all marked, one-click accept/dismiss, global undo, every guess explainable via its signal.** *(user-chose over propose-first / hybrid)*
5. **Canvas = Option A** (continuous timeline, phases as sections, arrows = continuity, gaps = broken arrows, long runs collapse). *(user-chose over kanban / railway)*
6. **File panel:** data-driven per-file Assign actions + suggestion hints; Inspector with Peek + Full-details/Raw tabs surfacing the full parsed payload. *(user-confirmed; requested the full-detail-on-click view)*
7. **Audit folded into P1** as correctness requirements + robustness fix-list. *(user-chose "fold into P1, keep designing")*

## 11. Open questions (resolve during P1/P2 planning)

- Exact v2 field names and id scheme; whether phase membership lives on the step (`step.phase`) or as an ordered `phase.steps` id list (leaning: `step.phase` + `order`, with a derived ordered view).
- Validation policy when a step's bound topology atom count ≠ its coordinates' atom count (pool contains distinct systems) — warn vs block.
- Phase-delete policy (reassign member steps to a neighbour vs delete them) — default and undo behaviour.
- CSV export fidelity under the three-level model (documented lossy flat view).
- Whether the suggestions payload is a distinct endpoint or an enrichment of the validation report (leaning: enrichment, to reuse the single document funnel).
