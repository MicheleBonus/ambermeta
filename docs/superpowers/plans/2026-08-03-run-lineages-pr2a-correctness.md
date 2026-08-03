# Run Lineages PR 2a (Correctness) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop AmberMeta asserting continuations that did not happen. A replica tree currently arrives from `discover` as one serial chain — `rep1/prod_0002 -> rep2/prod_0001` — with no warning, and every downstream number, finding and artifact inherits that false edge. This PR makes the lineage tag exist, infers it, and makes every chaining and continuity path honour it. **No new capability is claimed here; false claims stop.**

**Architecture:** Bottom-up. The tag lands on the model first, then reaches the analysis engine, then each of the three engines that create or consume chain edges is fixed against it. The tag is *read-only* at the surface in this PR — it is written by `discover` inference and by direct manifest editing. Editing it in the GUI, breaking totals out per lineage, and coherence findings are all PR 2b.

**Tech Stack:** Python 3.9+ (dataclasses, argparse CLI, pydantic v2 + FastAPI for the GUI API), pytest, Vitest/React + TypeScript for the frontend, GitHub Actions.

**Design doc:** `docs/superpowers/specs/2026-07-31-run-lineages-design.md`. **Read section 13 first.** It records four rulings and thirteen corrections made after PR 1 landed; where section 13 disagrees with sections 1-12, section 13 wins. Sections 1-12 quote line numbers that predate PR 1 and are wrong.

---

## Global Constraints

- **Every line number in the design doc's sections 1-12 is stale.** This plan's line references were verified against `bfbe681` on 2026-08-03. If a reference does not match what you find, **trust the file, not this plan, and report the conflict** — do not silently adapt, because the discrepancy may mean an earlier task moved something and a later task is about to undo it. This is not hypothetical: PR 1's plan went stale four times during execution.
- **This plan deliberately contains no verbatim copies of current code.** Read the cited file:line before editing. A pasted "before" block in a plan is a snapshot that rots the moment an earlier task edits the file.
- **Untagged documents must produce unchanged output.** Task 1 builds the harness that proves it; run it after every subsequent task. This is the guarantee decision 2 buys and the reason `lineage` is emitted only when set. Note "unchanged" is byte-identity for the manifest payload and the stats CSV, and exact-structure-plus-approx-floats for the two JSON summaries — see Task 1 step 1 for why the distinction is forced rather than chosen.
- **`ambermeta/protocol.py` is the analysis layer, not back-compat.** It stays. All grouping and partition logic goes in core (`protocol.py`, `simulation.py`, or a new `ambermeta/lineages.py`); the CLI and GUI consume it and reimplement none of it.
- **Any change under `ambermeta/gui/frontend/src/**` requires `npm ci && npm run build` in `ambermeta/gui/frontend` and a commit of the regenerated `ambermeta/gui/static/`**, or the `gui-static-check` CI job fails on a byte diff.
- **`tsc` is a CI gate** (`npm run build` is `tsc && vite build`). A required TS field with stale test literals fails the build even though `vitest` alone would pass.
- **No `build_parser` changes in this PR**, therefore no `docs/cli.md` regeneration. That matters because `scripts/export_cli_help.py` hard-refuses anything but Python 3.11 and the dev machine runs 3.13. If a task finds itself adding a flag, stop and escalate.
- **Do not touch `C:\Users\Miche\Documents\GitHub\ambermeta`** (a stale checkout) or `C:\Users\Miche\Desktop\ambermeta` (the user's app clone). Work only in this worktree.
- **Import trap:** the conda env's editable install resolves `import ambermeta` to the Desktop clone. Run everything with the repo root as CWD *and* assert `ambermeta.protocol.__file__` points here, or you will verify against a pre-PR-1 tree. Two verification agents hit this.
- **`httpx` is required** or `tests/test_gui_api_sim.py` fails to import and pytest aborts the entire collection — 0 tests run while appearing merely "interrupted". Use an env with `pip install -e ".[all,tests]"`.
- **Baselines on `bfbe681`:** pytest 268 passed; vitest 28 files / 267 tests; `npx tsc --noEmit` exit 0.
- **Test against both CI interpreters before claiming a task is done.** CI runs 3.9 and 3.12 and they are not interchangeable — see Task 1 step 1. A green 3.13 dev machine is not evidence.

---

## File Structure

| File | Responsibility after this PR |
|---|---|
| `ambermeta/simulation.py` | `Step.lineage`; emit-when-set in `_step_payload`; read-back + `""`->`None` normalisation; lineage-guarded `relink_restarts` and `repair_dangling_refs` |
| `ambermeta/lineages.py` | **NEW.** `lineages()`, `is_multi_lineage()`, `members()`, the untagged sentinel, and the directory-layout inference with its membership predicate. No FastAPI import. |
| `ambermeta/protocol.py` | `SimulationStage` gains `lineage`, `step_id`, `parent_id`; `_check_continuity` partitions and checks heads against producers; `detect_sequence_gaps`/`detect_numeric_sequences` key on `(lineage, base)`; `auto_detect_restart_chain` guarded; `stage_sequence` entries tagged |
| `ambermeta/gui/api/core_bridge.py` | `discover_draft` chains per lineage and groups phases across lineages; `_flatten_simulation` and `document_to_payload` carry the tag and the producer link; `build_suggestions` keys per lineage |
| `ambermeta/gui/api/document.py` | `add_step` takes `lineage`/`index` and does not auto-chain across tags; `update_step` validates `ref`; `_sim_to_model` projects `lineage` |
| `ambermeta/gui/api/schemas.py` | `lineage` on `StepModel`/`StepCreate`/`StepUpdate`; `lineage` on `Suggestion` |
| `ambermeta/gui/frontend/src/types/index.ts` | `StepModel.lineage: string \| null` (required); `Suggestion.lineage?: string` |
| `ambermeta/gui/frontend/src/test/factories.ts` | `lineage: null` default, so the field is added in one place rather than eleven |

---

### Task 1: Pin the back-compat guarantee before anything can break it

Decision 2's whole justification is that a tag costs untagged users nothing. Nothing currently pins that. Land the proof first so every later task is checked against it.

**Files:**
- Create: `tests/test_lineage_backcompat.py`

**Interfaces:**
- Consumes: `tests/data/amber/md_test_files` via the existing `sample_md_data_dir` fixture (`tests/conftest.py:9-11`).
- Produces: a regression gate every later task must keep green.

- [ ] **Step 1: Understand why a plain hash cannot work**

Section 10 of the design doc says "byte-identical" for four artifacts. Two of them cannot be byte-compared, for two *different* reasons. Both were established by execution on 2026-08-03; do not re-litigate them, but do re-run the harness if you change it.

**(a) Absolute paths.** `summary.json` embeds the run's own working directory (`"path": "C:\\...\\ntp_prod_0001.rst"`, 3 files x 5 stages). Two runs of identical input into different directories differ. Once the directory string is replaced with a sentinel they are equal — verified.

**(b) `sum()` changed in CPython 3.12.** `builtins.sum` became compensated (Neumaier) summation, and three prmtop floats are computed with it: `total_charge`, `total_mass`, `density`/`initial_density` (`legacy_extractors/prmtop.py:401`, `:412`, `:465`). CI's matrix is **3.9 and 3.12**, so the two jobs legitimately produce different bytes for identical input. Measured, with both interpreters holding the full `[all,tests]` dependency set:

| Artifact | Result | Differing leaves |
|---|---|---|
| `stats.csv` | **identical** | 0 |
| `summary.json` | differs | 15 of 967 — only `density`, `total_charge`, `total_mass` |
| `methods_summary.json` | differs | 10 of 507 — only `initial_density`, `total_charge` |

e.g. `8.020996348273828e-05` (3.9) vs `8.020996347271433e-05` (3.12).

A hardcoded hash for either JSON therefore passes on the machine that generated it and fails the other CI job — on the one test every later task is told to keep green.

**(c) The v2 manifest cannot be compared at all**: step and phase ids are `uuid4().hex[:8]`, fresh every run. Pin the round-trip of a *hand-written* fixture manifest instead; never a regenerated one.

- [ ] **Step 2: Write the test with the mechanism that follows**

Copy the sample data into `tmp_path`, run `discover --write` then `plan -m` with all three artifact flags, then:

- **`stats.csv`** — normalise the working directory to a sentinel, hash, compare against a committed constant. Provably stable across both interpreters.
- **`summary.json` and `methods_summary.json`** — normalise, `json.loads`, and compare against a committed golden **structurally**: every key path and every non-float leaf exactly, float leaves with `pytest.approx`. Commit the goldens as JSON files, not as hashes.

Structural comparison is not a weakening. A lineage regression changes key sets, names, refs, roles or counts — all compared exactly. The only thing tolerated is the last few bits of a float, which is precisely the thing that is not evidence of anything.

Normalise **all** path spellings: the JSON contains `\\`-escaped Windows separators, and the CSV and YAML may contain forward slashes. Replace longest-first. (A first attempt at this comparison produced a false "artifacts differ" result purely because only the forward-slash form was replaced.)

Also assert the negative that makes the whole design work: for an untagged `Simulation`, `"lineage" not in simulation_to_payload(sim)["steps"][0]`. Mirror the existing precedent at `tests/test_simulation.py:215-218`, which does exactly this for `rst`.

- [ ] **Step 3: Verify it can fail**

Temporarily make `_step_payload` emit `lineage` unconditionally and confirm the test goes red. Revert. A back-compat test that cannot fail is decoration.

---

### Task 2: `Step.lineage` and the payload round-trip

**Files:**
- Modify: `ambermeta/simulation.py`
- Modify: `tests/test_simulation.py`

**Interfaces:**
- Produces: `Step.lineage`, readable and writable through the v2 payload.
- Consumed by: every later task.

- [ ] **Step 1: Add the field**

`Step` is at `ambermeta/simulation.py:31-47`; `rst` at `:44` is the precedent — added by PR 1 and plumbed end to end. Put `lineage` next to it.

- [ ] **Step 2: Emit only when set**

`_step_payload` (`simulation.py:66-84`) already does exactly this for `rst` (`:80-81`) and `gaps` (`:82-83`), with a comment at `:78-79` explaining why. Follow it. This is what keeps Task 1 green.

- [ ] **Step 3: Read it back, and normalise the empty string**

`payload_to_simulation` builds the `Step` at `simulation.py:121-129`. **Coerce `""` to `None` on ingest.** Verified: an empty-string tag currently survives a round-trip, and under the members rule it would become a phantom member. The rest of the codebase already treats `""` as "clear" for step slots (`document.py:362`), so leaving the two conventions in disagreement is a bug waiting to be filed.

- [ ] **Step 4: Confirm the tag survives the load-time rewrite**

`_adopt_legacy_restart_paths` (`simulation.py:137-158`) runs unconditionally from `payload_to_simulation` (`:133`) and rebuilds `InputCoords` wholesale. It does not touch `Step` fields, so `lineage` should survive — but assert it in a test rather than assuming. This is also the reason the tag belongs on `Step` and **not** on `InputCoords`: anything stored there is silently dropped by this rewrite and by both `relink_restarts` branches.

- [ ] **Step 5: Tests**

Mirror `tests/test_simulation.py:208-212` (tagged round-trip) and `:215-218` (untagged emits no key). Run the full suite.

---

### Task 3: The read-only `lineage` surface (API + TypeScript)

Landed here, immediately after the model, so that the eleven TS fixture breakages happen once and early rather than colliding with later behavioural work.

**Files:**
- Modify: `ambermeta/gui/api/schemas.py`, `ambermeta/gui/api/document.py`
- Modify: `ambermeta/gui/frontend/src/types/index.ts`, `ambermeta/gui/frontend/src/test/factories.ts`, and the eleven literal sites below
- Modify: `ambermeta/gui/static/**` (rebuilt bundle)

- [ ] **Step 1: Pydantic models**

Add `lineage` to `StepModel` (`schemas.py:61-75`, beside `rst` at `:69`) and `StepCreate` (`:166-176`, `rst` at `:173`).

For `StepUpdate` (`:179-189`) use a **top-level** field with `model_fields_set` presence semantics, mirroring `topology` (consumed at `routes.py:349`) — *not* the `StageFiles` `""`-clears mechanism `rst` uses (`schemas.py:131`, `document.py:362`). The design doc says both; they are mutually exclusive, and a tag is not a file path. Do **not** add `lineage` to `_STEP_SLOTS` (`document.py:20`).

- [ ] **Step 2: Project it, or it is always null**

`DocumentStore._sim_to_model` (`document.py:133-142`) constructs `StepModel` field by field. A model field that is not wired here serialises as `null` forever, silently. `rst` at `:138` is the pattern.

- [ ] **Step 3: TypeScript**

`StepModel` is at `types/index.ts:7-15`. Add `lineage: string | null` as **required** — no route sets `exclude_none` (verified across all 29 routes), so the key is always present on the wire and an optional type would understate the contract.

- [ ] **Step 4: Fix the fixtures in one place first**

`src/test/factories.ts` already exists with a `makeStep` helper whose docstring says precisely why: hand-written literals used to break all at once and tempt people into making fields optional. Add the default there first — it clears eight files for free.

Then fix the eleven remaining raw literals. `npx tsc --noEmit` names them; expect these:
`App.dnd.test.tsx:30`, `App.workflows.test.tsx:33`, `Canvas.test.tsx:45` and `:59`, `Canvas.continuity.test.tsx:45`, `:59`, `:73`, `Canvas.dropTargets.test.tsx:58`, `PhaseSection.test.tsx:20`, `StepNode.test.tsx:19`, `NodeInspector.test.tsx:13`.

**Prefer migrating them to `makeStep` over adding the key eleven times** — that is what the factory exists for. Note `NodeInspector.test.tsx:13` defines its *own* shadowing `makeStep`; delete it rather than patching it, or the shared default keeps being bypassed.

- [ ] **Step 5: Rebuild and verify**

`npm ci && npm run build`, commit `ambermeta/gui/static/`, then `npx tsc --noEmit` (exit 0), `npm test`, and pytest.

---

### Task 4: `ambermeta/lineages.py` — membership, and inference from layout

The core module. Deliberately not under `gui/api/`, and it must not import FastAPI.

**Files:**
- Create: `ambermeta/lineages.py`
- Create: `tests/test_lineages.py`
- Modify: `ambermeta/__init__.py` (export)

- [ ] **Step 1: Membership, per ruling 13.1.1**

Implement `members()`, `lineages()` (insertion-ordered), and `is_multi_lineage()`.

**The sentinel rule, exactly:** untagged steps form one shared bucket (not one bucket per step). That bucket **counts toward `is_multi_lineage`** but is **excluded from `lineage_count` and from the `lineages` map**. Section 5's literal reading reported 4 members for the canonical three-replica campaign; this ruling is what prevents that.

Pick a sentinel that cannot collide with a user-supplied tag — a module-private object or a name no `str` tag can equal. Note the public `lineages()` mapping is keyed by `str`, so `None` cannot be a key; keep the sentinel out of that mapping entirely rather than inventing a string for it.

- [ ] **Step 2: Directory-layout inference with the membership predicate**

Per design section 6: among run groups, find the differing path segment and tag by it — **but only for groups whose run-name sets match**. `rep1/prod_0001` and `rep2/prod_0001` match; `common/equil` matches nothing and stays untagged. Without the predicate the canonical layout yields four tags and reports the prep runs as a member.

The directory information is already present: step names carry the posix path-prefixed stem (built at `protocol.py:1374`), e.g. `rep1/prod_0001`. Derive from that; do not re-derive from basenames.

**Ambiguity resolves to untagged, never to a guess.** Implement the failure-mode table in design section 6 as tests — nested sweeps (`300K/rep1/`) stay untagged, root files mixed with subdirectories stay untagged, a single lineage in a subdirectory stays untagged.

- [ ] **Step 3: Tests**

One test per row of that table, plus the four in-scope topologies from design section 1.1. Assert the sentinel is excluded from the count but still makes a half-tagged document multi-lineage.

---

### Task 5: Plumb the tag *and the producer link* to `SimulationStage`

Design section 7.1 warns this is a silent no-op if done in one place. It understates it: the tag must cross **six** boundaries, and ruling 13.1.2 adds a producer link the design doc never specified.

**Files:**
- Modify: `ambermeta/protocol.py`, `ambermeta/gui/api/core_bridge.py`
- Modify: `tests/test_cli_plan_v2.py` or a new `tests/test_lineage_plumbing.py`

- [ ] **Step 1: The dataclass**

`SimulationStage` is at `protocol.py:119-134`. Add `lineage`, and — per ruling 13.1.2 — `step_id` and `parent_id`, all keyword-defaulted so none of the existing construction sites break.

- [ ] **Step 2: The gate**

`document_to_payload` (`core_bridge.py:53-85`) rebuilds every entry from a closed whitelist; the file-kinds loop is at `:70`. **This is the single edit without which every other edit in this task is invisible.** Add the tag and the producer link here.

Its output is an in-memory argument to `auto_discover` and is never serialised, so this reintroduces nothing to an on-disk format.

- [ ] **Step 3: The flatten**

`_flatten_simulation` (`core_bridge.py:307-326`) builds a dict literal at `:319-325`. It already carries `step_id`. Add `lineage`, and the producer id — available as `s.input_coords.ref`. Note this function resolves `ref` down to a bare `inpcrd` path, which is why the producer link has to be carried explicitly rather than recovered later.

- [ ] **Step 4: The manifest path**

`_manifest_to_stages` (`protocol.py:899`, construction at `:968`) reads `files`, the five file kinds, `gaps`/`gap` and `notes` *after* construction (`:1013-1037`). Either extend the constructor call or set the fields post-construction in that same style; the latter matches how every other optional key is handled here. The design doc's "reads no other key" is wrong, and this is the harmless direction of that error.

- [ ] **Step 5: The anti-no-op test — required by design section 7.1**

Assert `[s.lineage for s in build_protocol(_flatten_simulation(load_simulation(p)), settings, dir).stages]` is populated from a tagged v2 manifest fixture, and likewise for the producer link. `build_protocol` here is `core_bridge.build_protocol` (`core_bridge.py:136`), not `ProtocolBuilder.build`; call-shape precedent at `tests/test_cli_plan_v2.py:154`.

**Without this test the no-op is undetectable** — a byte-identity regression on a tagged fixture passes either way, because `validate_manifest` does not reject unknown keys.

- [ ] **Step 6: Leave `ProtocolBuilder.add_stage` alone unless it is free**

`protocol.py:1731`. The design doc calls it a "discover construction site"; it is not, and it has **zero in-repo callers**. Adding an optional parameter is API-completeness only. Do not let it expand scope.

---

### Task 6: `discover_draft` — chain per lineage, group phases across lineages

**The most important task in this PR.** This is the primary producer of false edges and design section 7.5 does not list it.

**Files:**
- Modify: `ambermeta/gui/api/core_bridge.py`
- Create: a multi-replica fixture tree (see step 1)
- Modify: `tests/test_gui_core_bridge_sim.py`, `tests/test_cli_discover.py`

- [ ] **Step 1: Build the fixture, and write the failing test first**

There is **no replica fixture in the repo** — every existing fixture is a single flat production chain. Create a synthetic tree: **three replicas x at least three distinct roles**, with at least one role carrying two runs so a genuine within-lineage chain exists. Roughly `rep{1,2,3}/{min_0001, heat_0001, prod_0001, prod_0002}`.

Three roles is not arbitrary — the phase-count assertion in step 5 depends on it. `discover_draft` opens a new phase per *role change*, so a two-role tree yields six phases, not nine. Verified: a `rep{1,2,3}/{min_0001,prod_0001,prod_0002}` tree produces exactly 6.

Real mdouts are large; check whether the existing fixtures are trimmed and match that convention, and keep the tree as small as the parsers tolerate.

**Record the actual pre-fix behaviour; do not take it from this plan.** Run `discover_draft` on your fixture and write the observed edges and phase count into the test as the "before" assertion. The cross-lineage edge is `rep1/<last run in order> -> rep2/<first run in order>`, and which runs those are depends on the natural sort of your path-prefixed stems — with a `min/heat/prod` naming it is *not* `prod_0002 -> prod_0001`, because `heat` sorts before `min`. The design doc's `rep1/prod_0002 -> rep2/prod_0001` is only correct for a production-only tree.

- [ ] **Step 2: Chain per lineage**

`core_bridge.py:444-451` emits the chained `InputCoords`, guarded only by `prev_step_id is None` at `:444` — i.e. only the *globally* first step gets `starting_structure`. `prev_step_id` is one flat variable, threaded at `:429` and updated after each step.

Make that state per-lineage: the first step of **each** lineage reads `starting_structure`, and each lineage's chain continues only within itself. Tagging alone does not fix this — the chain is built unconditionally — so this needs a real edit, either by computing tags up front from the ordered stems or by chaining in a second pass after tagging.

- [ ] **Step 3: Phase grouping**

The contiguous-role check at `core_bridge.py:461-463` opens a new phase whenever the inferred role changes. Combined with replica-major ordering from `_ordered_stems` (`protocol.py:1044-1049`), a 3-replica x {min,heat,prod} tree yields **nine** phases, three of them named "Minimization".

When multi-lineage, same-role steps from all lineages join one phase. **Gate on multi-lineage** so single-lineage output is unchanged.

- [ ] **Step 4: Report the inference**

Per decision 7, surface the tagging as an `[applied]` suggestion. `build_suggestions` is at `core_bridge.py:270-306`.

- [ ] **Step 5: Tests**

Three chains not one; the phase count drops from *(roles x replicas)* to *(roles)* — with the step 1 fixture, 9 to 3, but assert the number you actually measured in step 1; a single-lineage tree's `discover` output is unchanged (diff it against the Task 1 golden); an ambiguous tree stays untagged.

---

### Task 7: The chain-maintenance invariant — six sites, not three

**No automatic operation may create an `input_coords.ref` crossing a non-null tag boundary.**

**Files:**
- Modify: `ambermeta/simulation.py`, `ambermeta/gui/api/document.py`, `ambermeta/gui/api/schemas.py`, `ambermeta/gui/api/routes.py`
- Modify: `tests/test_simulation.py`, `tests/test_gui_document.py`

- [ ] **Step 1: `relink_restarts` — guard BOTH branches**

`simulation.py:242-277`. The design doc fixes only the `elif` (`:272-276`). Verified on an interleaved reorder `[rep1_1, rep2_1, rep1_2, rep2_2]`: the `elif` produced **zero** cross-lineage edges and the **first** branch (`:265-271`) produced **two**. Guard both; when the predecessor's tag differs and both are non-null, fall back to `starting_structure`.

The function currently tracks only `prev_id` (`:260`, `:277`); it needs a step lookup by id to compare tags.

**`tests/test_simulation.py:137-152` pins the drag-to-front behaviour the `elif` exists for. It must stay green** — the guard is a no-op for untagged documents.

- [ ] **Step 2: `repair_dangling_refs` — same-tag re-chain**

`simulation.py:280-296`. Deleting a shared parent referenced by three members currently produces one 6-step serial chain — the exact false edge this feature exists to remove, manufactured by the tool.

Re-chain only to the nearest preceding step with the *same* tag, else `starting_structure`. When the deleted step was referenced by **two or more distinct tags**, emit a warning finding rather than re-linking silently.

**It has no findings channel today** — it returns `None`, and `DocumentStore.to_response()` (`document.py:164-176`) has no field for one. Adding that channel is part of this step. If it proves larger than it looks, escalate rather than dropping the warning.

**It is also not gated on `auto_link_restarts`:** `delete_phase` (`:311`) and `delete_step` (`:379`) call it directly, bypassing the gated `_relink` wrapper (`:105-112`). A user who turned auto-linking off still gets manufactured edges. Deleting the shared *phase* is the realistic way a user removes a shared equilibration, and the design doc names only step deletion.

`tests/test_simulation.py:196` pins the current single-lineage re-chain and must stay green.

- [ ] **Step 3: `add_step` — accept `lineage` and `index`**

`document.py:315-343`. It appends (`:332`) with no index on either the store method or the route, and auto-chains to `_step_before(sid)` (`:336-339`) when `auto_link_restarts` is on (default `True`, `:25`).

Insert after that lineage's last step and chain to it. **When no lineage is given and the phase is multi-lineage, do not auto-chain at all** — silence is recoverable, a false edge is not.

Mirror `move_step`'s existing index convention (`schemas.py:192-194`) rather than inventing a second one. Note `_step_before` (`:96-103`) crosses phase boundaries, so "the last band" is really "the last step in the document".

Three frontend entry points hit this auto-chain, not one: `PhaseSection.tsx:269`, `AssignActions.tsx:125`, and `App.tsx:36-40` (used at `:113` and `:133`). Only `App.tsx:115-118` supplies explicit coords and escapes it.

- [ ] **Step 4: `update_step` — validate the ref at all**

`document.py:347-368` (coords assigned at `:355-358`), exposed as `PUT /steps/{id}` (`routes.py:335-367`, where `_guard_path` checks only `input_coords.path`). It currently accepts a **nonexistent step id** and a **self-reference**, both verbatim — the latter creating a 1-cycle.

Reject a ref not present in the document, and reject self-reference. A *cross-lineage* ref set by hand is the only way a user can express a genuine branch: **allow it, but surface it as a finding.** Without this, every guard added above is trivially bypassable through this route.

- [ ] **Step 5: `move_step` and the remaining relink callers**

`_relink` is called from `reorder_phases` (`:296`), `add_step` (`:343`), `move_step` (`:393`) and `reorder_steps` (`:405`); `repair_dangling_refs` from `:311` and `:379`. Steps 1-2 fix the shared helpers, which covers all six — but verify each, because `move_step` produces cross-**phase** cross-lineage edges that no single-phase reorder demonstrates.

- [ ] **Step 6: Tests, per design section 10**

(a) the interleave reorder creates zero cross-tag refs; (b) shared-parent deletion produces no `A2->B1`; (c) `add_step` into a multi-lineage phase does not auto-chain; (d) `delete_phase` with `auto_link_restarts=False` does not re-chain across tags; (e) `update_step` rejects a bogus id and a self-ref. All existing chain tests stay green.

---

### Task 8: Continuity — partition by lineage, check heads against their producer

**Files:**
- Modify: `ambermeta/protocol.py`
- Modify: `tests/test_continuity_p1.py`, `tests/test_protocol.py`

- [ ] **Step 1: Extract the pair check without restructuring it**

`_check_continuity` is at `protocol.py:349-443`; the neighbour zip is `:350`. The body contains **three** `continue`/early-exit paths — the missing-times path (`:365-374`), the implausible-gap path (`:399-404`), and the normal path — that change meaning under any inlined nesting.

Extract `:351-442` into a pair function with `continue` becoming `return`, and leave the body otherwise untouched. Do not "tidy" it in the same commit.

- [ ] **Step 2: Partition**

Bucket by tag, one shared bucket for all untagged stages, insertion-ordered so the untagged chain keeps document order. Guard the whole thing so a fully-untagged document takes the original flat path and is byte-identical — `observed_gap_ps` is serialised into `summary.json`, so Task 1's harness will catch any drift.

- [ ] **Step 3: The head check — ruling 13.1.2**

After the partition, check each lineage head against **its actual producer** via the `parent_id` plumbed in Task 5, using the same pair function.

This is why Task 5 carries the producer link. A plain partition leaves every head with `observed_gap_ps = None` and no notes at all — verified: a genuine `equil -> rep1` continuation regresses from `0.0` to `None`, and a document of single-step lineages produces *zero* continuity output, which reads as "checked and fine" rather than "not checked".

Where a head has no resolvable producer, emit an INFO note saying continuity was not measured. Silence is the one outcome ruled out.

- [ ] **Step 4: Tests**

A fan-out fixture produces zero non-INFO continuity notes; a chained-lineage fixture still detects within-lineage gaps; the head's `observed_gap_ps` is asserted explicitly so the chosen behaviour is pinned rather than incidental; the `equil -> rep1` head check still reports `0.0`.

Note `allow_gaps` is **not** a workaround for the old behaviour and must not be conflated with it: it suppresses the "Gap detected without stated expectation" half (`:439-440`) but not the "Stage appears to overlap" half (`:410-412`).

---

### Task 9: Sequence gaps keyed on `(lineage, base)`

**Files:**
- Modify: `ambermeta/protocol.py`, `ambermeta/gui/api/core_bridge.py`, `ambermeta/gui/api/schemas.py`
- Modify: `ambermeta/gui/frontend/src/types/index.ts`, `.../Canvas/PhaseSection.tsx`
- Modify: `tests/test_continuity_p1.py`, `tests/test_gui_core_bridge_sim.py`, `.../Canvas.continuity.test.tsx`

- [ ] **Step 1: Key the detectors**

`detect_numeric_sequences` (`protocol.py:1052-1117`) and `detect_sequence_gaps` (`protocol.py:1124-1149`) both call `Path(name).stem`, discarding the directory, while being fed path-prefixed stems. Key on `(lineage, base)`.

Verified consequences today: a crashed replica (3/1/3 chunks) yields `{}` — **no missing-run finding at all**, for the failure mode replicas exist to expose. Offset numbering (`rep1: 0001-0002`, `rep2: 0011-0012`) yields `{'prod': [3..10]}`.

`detect_numeric_sequences` is public (`ambermeta/__init__.py`, documented at `docs/api.md:520`); `detect_sequence_gaps` is not in `__all__`. Keep the public signature working or update all four existing call sites deliberately.

- [ ] **Step 2: Correct the expected outcome**

The design doc says offset numbering produces "eight spurious `needs_you` cards". It produces **one** card naming eight indices (`build_suggestions` emits one `Suggestion` carrying all indices) plus up to eight canvas ghosts.

For the offset case the correct result is **zero** findings — each member is internally contiguous. For the crashed-replica case it is **one** finding scoped to the short member. Assert both.

- [ ] **Step 3: Carry the tag to the card — both edits or neither**

Add `lineage` to `build_suggestions`' output (`core_bridge.py:270-306`) **and** to the `Suggestion` model (`schemas.py`, beside `base`/`missing`). Pydantic defaults to `extra='ignore'`, so `routes.py:111` (`Suggestion(**s)`) drops an undeclared key **silently, with no error and no effect**. Half of this change is indistinguishable from none.

- [ ] **Step 4: Reconcile the two `base` derivations, or the fix stays invisible**

The ghosts are **already dead** for any multi-directory tree, independently of lineages: the server emits `base: "prod"` while the client's `numericBase` (`PhaseSection.tsx:17-19`) keeps the directory and yields `"rep1/prod"`, and `ghostsForBase` (`:56-65`) rejects on mismatch. Reconcile them, add `lineage` to the reject condition, and pass it from the call site at `:101`.

- [ ] **Step 5: Explicitly out of scope — the dot-index bug**

`Path().stem` eats a dot-numbered index, so `prod.0001/prod.0002/prod.0004` returns `{}`. Design section 7.4 flags it as independent. **Leave it.** Fixing it makes previously-silent untagged manifests start reporting findings, which changes `--strict` exit codes for existing users and breaks Task 1's guarantee. File it; do not fix it here.

- [ ] **Step 6: Rebuild the bundle and run everything**

---

### Task 10: The second chainer — `auto_detect_restart_chain`

**Files:**
- Modify: `ambermeta/protocol.py`
- Modify: `tests/test_core_hardening.py`

- [ ] **Step 1: Guard it**

`protocol.py:1170-1291`, reached by `plan --auto-detect-restarts`. It scores `stages[i-1]` by name (`:1261-1262`, +5.0) and trajectory end-time (`:1277-1281`, +20.0) and will assign rep1's terminal restart as rep2's input. Its atom-count guard (`:1252-1254`) is a no-op across replicas of one system.

Either gate the `i > 0` branches on matching tags, or refuse on multi-lineage documents. Note it only fires for stages lacking a same-stem restart (`:1233`), which is exactly the first step of each replica.

- [ ] **Step 2: The `rep10` regex bug**

`:1266-1267` leftmost-matches `\d{2,}` on a name with `/` folded to `_` (`:1258`), so `rep10_prod_0002` scores against `10`, not `0002`. Split the name into directory and base and score only the base.

- [ ] **Step 3: Do not raise the threshold**

The `>= 5.0` threshold (`:1291`) is met by the name term alone (exactly 5.0). Raising it would silently disable auto-detect for every trajectory-less tree. Fix the candidate scope, not the threshold.

---

### Task 11: `stage_sequence` stops asserting one chain — ruling 13.1.3

**Files:**
- Modify: `ambermeta/protocol.py`
- Modify: `tests/test_protocol.py`

- [ ] **Step 1: Tag each entry**

`to_methods_dict` builds `stage_sequence` at `protocol.py:804-819` as a flat ordered `[{name, role}]` list, published into `methods_summary.json` — the artifact `docs/cli.md` calls publication-ready. For a fan-out it asserts `rep1 -> rep2 -> rep3` ran in sequence.

Add a per-entry `lineage` key. **Additive only**, so an untagged document's artifact is unchanged — Task 1 pins this via its structural comparison (see Task 1 step 1: `methods_summary.json` cannot be byte-hashed across the CI matrix, but every key path and every non-float leaf is compared exactly, which is what "additive only" needs to mean here).

- [ ] **Step 2: Emit no statistical claim**

Per decision 4, the entry states a graph fact (which member this run belongs to) and nothing about independence or sampling. No field named `ensemble_size`, `independent`, or `N`.

---

### Task 12: Documentation

**Files:**
- Modify: `docs/manifest.md`, `docs/api.md`, `docs/architecture.md`, `docs/gui.md`

- [ ] **Step 1: Schema**

Add a `lineage` row to the Step field table in `docs/manifest.md` (the `rst` row is the model, worded "Omitted entirely when unset...") and to the dataclass listing at `docs/api.md:71`.

- [ ] **Step 2: Behaviour**

Document: the tag is declared, never inferred except by `discover`, which reports it as `[applied]`; untagged means one implicit member; the chain invariant; that a lineage head's continuity is measured from its producer.

- [ ] **Step 3: Verify rather than assert**

**Run every command and every snippet you write.** The docs sweep immediately before this PR shipped 31 defects — 5 critical — from text written by reading the code instead of executing it. Re-run the repo's link/anchor check.

---

## Self-Review

Written after drafting, against the design doc and the verification report.

- **Task 3 lands the TS surface before the behaviour that motivates it.** Deliberate: making `lineage` required breaks eleven fixture sites, and doing that early keeps later behavioural commits readable. The cost is one commit where the field exists and renders nowhere.
- **Task 7 step 2 hides a scope risk.** `repair_dangling_refs` has no findings channel, and adding one touches `DocumentStore.to_response()`, `DocumentResponse`, and the frontend. If it grows, the fallback is to land the same-tag re-chain (which needs no channel) and defer only the multi-tag warning — but say so rather than dropping it silently.
- **Task 8 depends on Task 5 carrying `parent_id`.** If Task 5 ships without it, Task 8 cannot implement ruling 13.1.2 and will silently degrade to the behaviour that ruling rejected. Task 5 step 5 must assert the producer link, not just the tag.
- **The fixture in Task 6 is on the critical path for Tasks 6-10** and does not exist yet. If it proves awkward to trim real mdouts, that is worth escalating early rather than working around per-task.
- **`plan --recursive` reaches `SimulationStage` construction at `protocol.py:1478`, which this plan does not tag.** So a recursive scan of a replica tree gets the continuity partition only if the tag arrives — which it does not on that path. Either accept that `--recursive` is untagged (defensible: it is the flat analysis view, not a document) or extend Task 5. **Flagged, not resolved.**
- **No task changes `build_parser`,** so `docs/cli.md` needs no regeneration and the Python 3.11 constraint is not hit. Verified against the task list.
