# Run lineages, PR 2b — the breakdown and the editing surface

Written against `main` at `78c69cc` (PR 2a = #75, PR 1 = #74) after a second verification sweep,
by execution, of every claim in design §13.4 and the sections it points at. Baseline:
**394 pytest passing on Python 3.9.12 and 3.12.13, 271 vitest passing**, committed static bundle
byte-identical to a fresh build.

Design doc: `docs/superpowers/specs/2026-07-31-run-lineages-design.md`. **§13 supersedes §§1-12.**
Where this plan and §13 disagree, this plan wins — §13 was itself written before PR 2a landed and
PR 2a implemented more of 2b than §13.4 anticipated.

## What the sweep changed

Seven corrections that a plan written from §13.4 alone would have got wrong:

1. **`plan --manifest` already prints findings.** `_plan_v2` (`cli.py:1112-1113`) calls
   `validate_simulation` and `_print_simulation`, reaching the same `_sim_findings`
   (`cli.py:263-276`) that `validate` uses. Adding a findings block there produces *duplicate*
   output. The real gaps are `plan --recursive`/`--interactive`, the written artifacts, and the
   exit code.
2. **Python 3.11 is installed** — `C:/Users/Miche/miniforge3/envs/marker/python.exe` (3.11.14).
   `scripts/export_cli_help.py` runs on it and reports `docs/cli.md is up to date`. §8.2's
   "no docs/cli.md regeneration is possible" is false, and the no-new-flags rule it justifies is
   no longer forced. A parser change is now legal *provided* the generator is run.
3. **Most of §8.3's canvas paragraph shipped in 2a.** `groupSteps` already keys on
   `(lineage, numericBase)` (`PhaseSection.tsx:55-67`); `ghostsForGroup` (`:75-89`) already matches
   on `(serverBase(base), lineage)`; the `prod` vs `rep1/prod` mismatch is fixed by `serverBase`
   (`:28-30`). What is *not* done is everything visible: no band affordance, no member name
   anywhere in the UI, no arrow suppression.
4. **`coherence(sim, params)` as signed in §5.1 is unimplementable.** `Step` carries no parsed
   parameters; `temp0`/`cut`/`ntt`/`ntp`/`dt`/`ig` exist only on
   `SimulationStage.mdin.details.cntrl_parameters` after `build_protocol` has parsed the files.
   Coherence takes stages, not a document.
5. **The begin time sits *below* the proposed stop condition.** §11 item 3 offers
   `3. ATOMIC COORDINATES` (fixture line 233) as the stop; §11 item 4 wants line 237. Stopping at
   the banner returns `begin_time=None` on every file and the feature no-ops.
6. **`PUT /steps/{id}` accepts `lineage` and silently ignores it** — 200, document unchanged
   (`schemas.py:203` declares it; `document.py:467-497` has no branch). A bulk-tagging UI wired to
   the existing hook would appear to work and change nothing.
7. **Retagging manufactures cross-lineage edges and nothing catches it.** Retag a chained
   `s1->s2->s3->s4` as `rep1,rep1,rep2,rep2` and the pre-existing `s3->s2` ref now crosses a
   boundary. `_check_continues_from` only fires when a ref is *set*, not when a tag changes
   underneath one. Via `Step.rst`/`resolve_input_coords` that becomes a wrong *file* in the
   manifest, in `resolved_input_coords`, and in the methods summary — the exact defect 2a existed
   to remove, reintroduced by 2b's own feature.

## Rulings taken for this PR

- **`plan --strict` is unified with `validate --strict`** (user ruling, 2026-08-05): it keeps
  aborting on an unreadable file *and* exits 1 on a `continuity_gap`/`missing_run` finding. One
  word, one meaning. This changes the exit code of an existing invocation and must be called out
  in the PR body and in `docs/cli.md`.
- **Bulk tagging is an explicit step-id list** (user ruling, 2026-08-05), not a phase fan-out:
  `discover` emits phase-major documents, so one Production phase spans every replica and a
  phase-scoped write would stamp them all with one tag. Ship the bulk route, a band-header
  control, and an apply-inferred-tags action.
- **New keys are emitted only when the document is multi-lineage.** Not a style choice: the
  back-compat gate asserts the exact leaf-path set *and order* of `summary.json` and
  `methods_summary.json`, so `totals.lineage_count = 1` or a top-level `lineages: null` fails it.
  This is the `to_methods_dict` emit-when-set convention (`protocol.py:892`) applied consistently,
  and it keeps every untagged user's artifacts byte-identical.
- **The 2a deferral of the dot-index bug is overridden**, in writing. The 2a plan
  (`2026-08-03-run-lineages-pr2a-correctness.md:394`) said "**Leave it.**" on the grounds that
  fixing it makes previously-silent manifests start reporting findings and so changes `--strict`
  exit codes. That reasoning stands; the counterweight is that a dot-numbered tree today loses the
  crashed-replica finding entirely, which is the failure mode the whole feature exists to expose.
  A new finding on a tree that genuinely has a hole is the correct outcome.

## Environment

| Purpose | Interpreter |
|---|---|
| CI leg 1 | `scratchpad/venv39/Scripts/python.exe` (3.9.12) |
| CI leg 2 | `scratchpad/venv2/Scripts/python.exe` (3.12.13) |
| `docs/cli.md` regeneration | `C:/Users/Miche/miniforge3/envs/marker/python.exe` (3.11.14) |

`scratchpad/venv` is **not** usable — its numpy is built for cp313. Do not read its ImportError as
a code defect.

Frontend: `cd ambermeta/gui/frontend && npm run build`, and **commit `ambermeta/gui/static/`** —
`gui-static-check.yml` fails the PR otherwise.

---

## Task 1 — Extend the back-compat gate before anything else

`tests/test_lineage_backcompat.py` is the gate and it already exists; this task only widens it so
the new surfaces are pinned before they move.

1. Add an assertion on `SimulationProtocol.totals()`'s exact key set for an untagged protocol.
   Nothing pins it directly today, so a later refactor can move it silently once someone
   regenerates a golden.
2. Add the negative case the gate is missing: build a *tagged* protocol and assert `to_dict()`
   gains exactly `totals.lineage_count` and a top-level `lineages`, and that an untagged one gains
   neither.
3. Do **not** regenerate any golden in this PR. If a task appears to require it, that task is
   wrong — go back and make the key conditional.

**Verify:** the two existing golden tests still pass on 3.9 and 3.12; the new key-set test fails
if `totals()` gains an unconditional key (check by temporarily adding one).

## Task 2 — Fold-in 1: dot-separated chunk indices

`Path().stem` is applied to a run *name* in exactly two places repo-wide —
`protocol.py:1219` (`detect_numeric_sequences`) and `protocol.py:1330` (`detect_sequence_gaps`).
Every other `.stem`/`splitext` in the tree operates on a real file path, where stripping is
correct; leave all of them alone.

The stem call is doing two jobs: dropping the directory **and** dropping the suffix. Split them.

- Directory: an explicit `rpartition("/")`. This must stay, and stay separate — the emitted `base`
  is bare (`prod`, not `rep1/prod`) and the client depends on it at `PhaseSection.tsx:78` via
  `serverBase`. Remove it and every ghost dies again.
- Suffix: **strip the final suffix unless it is purely digits.** Measured: naive removal is
  `1 failed, 393 passed` and silently turns two more tests vacuous; the numeric-aware rule is
  `394 passed` and fixes the bug.

Three cases the rule has to get right, all verified:

| Input | Today | Required |
|---|---|---|
| `prod.0001` / `.0002` / `.0004` | `{}` | gap at 3 |
| `prod.0001.out` / … | gap at 3 (works today) | unchanged |
| `system.rst5`, `system.rst7` | `{}` | `{}` — **not** a gap at 6 |

`.rst7`/`.parm7` are why "suffix ends in a digit" is not a usable discriminator and "suffix is all
digits" is: no AMBER extension in the `ext_map` (`protocol.py:1632-1651`) is purely numeric.

Also in this task:

- `PhaseSection.tsx:83` builds the ghost label with a hardcoded `_`. For a dot-numbered family it
  renders `rep1/prod_0003` beside real runs called `rep1/prod.0003`. Derive the separator from the
  group's own steps.
- Four comments become load-bearing lies the moment this lands and must be rewritten:
  `lineages.py:20-24` ("kept identical on purpose" — false today for dot names),
  `protocol.py:1199` (claims `name.001` is detected — false), `protocol.py:1216-1218` and
  `:1326-1329` (justify `.stem` on directory grounds only).
- New fixture: every committed and conftest fixture is underscore-numbered. Write the dot-numbered
  one **by string concatenation**, not `Path.with_suffix` — `Path('prod.0001').with_suffix('.mdin')`
  is `prod.mdin`, and a test built through `test_continuity_p1.py:602-605`'s `_write_run` helper
  would silently write the wrong files.

**Verify:** the table above, by execution; `394 passed` unchanged on both interpreters; the
untagged goldens do not move (they are underscore-numbered, so they must not).

## Task 3 — Fold-in 2: a findings channel on every `plan` path

Four separate gaps. Do not touch `_plan_v2`'s printing — it already works.

1. **`plan --recursive` / `--interactive` compute nothing.** Neither branch builds a `Simulation`,
   and `build_suggestions(sim, …)` raises `AttributeError: 'SimulationProtocol' object has no
   attribute 'phases'` when handed a protocol. The tractable subset is
   `detect_sequence_gaps([s.name …], [s.lineage …])`, whose inputs both exist on
   `SimulationProtocol.stages` on every path — verified to return `{('rep2','prod'): [2,3]}` on the
   scan path. Add a protocol-level findings producer for the `missing_run` kind and print it
   through the same "Continuity / sequence findings" heading `_sim_findings` uses, so the two plan
   modes say the same thing about the same tree. The other four suggestion kinds need
   Simulation-only state that `auto_discover` never produces; do not fake them.
2. **No artifact carries findings.** `summary.json` is exactly `{totals, stages}`. Add a
   `findings` key **only when non-empty** (Task 1's rule).
3. **`PlanResult` has no `suggestions` field.** Add it. The GUI currently gets suggestions anyway
   via an auto-revalidate effect (`App.tsx:70-77`), so this is about the artifact and the API
   contract being honest, not about fixing a visible GUI bug.
4. **`--strict` does not escalate.** Per the ruling above, `plan --strict` now exits 1 on a
   `continuity_gap`/`missing_run` finding, on both plan paths. Update the flag's help text and
   **regenerate `docs/cli.md` on the 3.11 interpreter** — a parser change with no regeneration
   fails `cli-docs-sync` and produces no local signal at all (there is no parser/completion parity
   test; the whole 394 still pass).

Also fix, while in `_sim_findings`: it prints `Validation: OK` from `report['ok']` and the caller
then returns 1 under `--strict`. Saying OK and failing is worse than either alone.

**Verify:** on the crashed-replica fixture, `plan --manifest`, `plan --recursive` and
`validate --manifest` all name `rep2/prod`; all three exit 1 under `--strict` and 0 without;
`plan --manifest` prints the findings block exactly once.

## Task 4 — `totals` + `lineages` and `LineageTotals`

Per §3.1 as amended. `buckets` is structurally typed on `.lineage` and already accepts
`SimulationStage`, so the grouping needs no new code — `buckets(protocol.stages)` returns
`['rep1','rep2','rep3']` today.

- `totals()` gains `lineage_count` **only when multi-lineage**. It counts declared tags only; the
  untagged sentinel is excluded (ruling 13.1.1) but still counts toward `is_multi_lineage`, so the
  canonical `common/{min,heat,equil}` + `rep1..3/prod_*` campaign reports 3, not 4.
- `to_dict()` gains a sibling `lineages` map, same condition. Not inside `totals` — both
  `PlanResult.totals` and `ValidationReport.totals` are `Dict[str, float]` and a nested dict raises
  (`totals.lineages: Input should be a valid number`). `/api/plan` builds its response *after*
  writing the files, so getting this wrong is an HTTP 500 over artifacts that already landed —
  reproduced.
- `LineageTotals` is its own pydantic model (`steps`, `time_ps`, `step_count`): `step_count` is an
  int and cannot live in a float map. Declare `lineages: Optional[Dict[str, LineageTotals]]` on
  **both** `PlanResult` and `ValidationReport` — pydantic's default `extra='ignore'` silently drops
  an undeclared key, which is exactly how `StageIssue.continuity` is already lost on the wire
  (`core_bridge.py:225` emits it, `schemas.py:286` does not declare it). Mirror both on the
  hand-written TS types.
- Accumulate with `+=` in a loop, as `totals()` already does. `sum()` would put the 3.9 and 3.12
  outputs at risk of last-bit divergence via CPython 3.12's Neumaier summation.
- Two known cosmetics, to be documented rather than fixed: `lineage_count` coerces to `3.0` inside
  the float map on the wire (precedent: `stage_count: 5.0` at `docs/gui.md:263`), and a member that
  is all minimisation reports `steps: 0.0` because minimisation stages carry no `nstlim`/`dt`.

Fix `StageIssue.continuity` while here — it is one declared field and the same class of defect.

**Verify:** untagged `to_dict()` byte-identical to the golden; tagged campaign reports
`lineage_count: 3` with four members; `POST /api/plan` returns 200 with a populated `lineages` on a
tagged document and no `lineages` key on an untagged one.

## Task 5 — The header-only mdout read

There is exactly one mdout parser: `legacy_extractors/mdout.py::parse_mdout`, which `readlines()`
the whole 2553-line file. Header-only is 0.12 ms against 10.6 ms, so this is worth doing — but only
if it genuinely stops early.

**Return a side-car dataclass from a new entry point. Do not add fields to `MdoutMetadata`.**
`_serialize_value` calls `asdict()` on it, so every new field lands verbatim in `summary.json` and
breaks the golden with real non-null values.

Read three things, from the five fixtures' verified line map:

- **Resolved `ig`** from the key=value at fixture line 190, under
  `Langevin dynamics temperature regulation:`. **Never from line 59** — the repo's own
  `_extract_key_values` returns `{'ig': -1.0}` there, because the resolved seed is free prose that
  wraps onto line 60. Recording -1 for every run means "all runs share a seed", the precise false
  claim decision 4 forbids. The line-190 block is thermostat-specific and every fixture is `ntt=3`;
  absence must mean *unknown*, never *shared*.
- **Begin time** from ` begin time read from input coords = <N> ps` (line 237). Do **not** reach for
  `stats.time_start` — it is the first *printed* frame, 100 ps later (1020.0 vs a true 920.0), and
  using it manufactures a 100 ps gap on every chunked run while looking like agreement with the
  committed golden.
- **File Assignments** (lines 17-28). The value field starts at column 11; **87 is not a field
  width** — long-path lines are 87 and short-path lines are 80. Slice from column 11 and rstrip;
  treat "field has no trailing whitespace" as the truncation flag. In these fixtures only PARM is
  clipped, so a topology check built on it degrades to silence rather than comparing prefixes.

Stop condition: `4. RESULTS` (line 256) or the first ` NSTEP =` (260). **Not**
`3. ATOMIC COORDINATES` (233) — the begin time is four lines past it. A fixed line budget is ruled
out: the header embeds a verbatim mdin echo whose length varies with the input.

Consumer: `_check_stage_pair`'s `start_time` (`protocol.py:436-438`), as a **fallback** when the
inpcrd time is unavailable. That keeps CI (which installs the netcdf extra) on the existing golden
values and improves the bare-install case, where `parse_inpcrd` on a NetCDF restart returns
`time=None` and the mdout header is the only readable start time.

Store it on `SimulationStage` — safe, because `SimulationStage.to_dict()` emits a fixed key list
rather than `asdict()`.

**Verify:** all five fixtures yield the right seed (70038 / 761443 / 410249 / 613120 / 570364) and
begin time (920 / 20920 / 40920 / 60920 / 80920); the goldens do not move; a synthetic header
missing the Langevin block yields `ig=None` rather than -1.

## Task 6 — Coherence findings

`ambermeta/lineages.py` gains `varying_axis` and `coherence`. Neither exists; no `Finding` type
exists anywhere.

**Signature takes stages, not a `Simulation`.** Duck-type them the way `buckets` already duck-types
`_Tagged`, so `lineages.py` keeps importing no protocol and no FastAPI.

- Read `mdin.details.cntrl_parameters.get('temp0')`, **not** `MdinMetadata.target_temp` — the
  latter defaults to 300.0 when the mdin omits `temp0` (`legacy_extractors/mdin.py:487-488`), so
  comparing it silently manufactures agreement between two runs that never declared a temperature.
  Absent must stay absent.
- `ntt`/`ntp` come only from the mdin's raw parameters. A document with mdouts but no mdins is a
  legitimate `discover` result; skip those parameters rather than inferring them from the
  thermostat/barostat strings, which is not the same information.
- `ig` comes from Task 5. Without it there is no seed check on a discovered document at all.

Severity per decision 5: **different `natom` between members, or minimisation mixed with dynamics,
is a category error and exits 1.** Everything else — `temp0`, `cut`, `ntt`, `ntp`, `dt`, a shared
resolved seed — is a finding escalated by `--strict`.

Scope note: this is about members *differing*. Leave `_validate_atoms`' intra-stage comparison
alone — it compares four sources with no notion of which disagreement is meaningful, and promoting
it would fail benign cases like a stripped-water trajectory. Record that as a known limitation.

Output states graph facts and never a statistical property (decision 4): "3 steps read the restart
written by st_7 and carry 3 distinct resolved seeds", never `ensemble_size` or `independent`.

**Verify:** a two-member tree differing only in `temp0` yields one finding and exit 0, exit 1 under
`--strict`; differing in `natom` yields an error and exit 1 unconditionally; an mdin-only tree
yields no seed finding rather than a false one.

## Task 7 — The GUI error channel

§8.3's claims still hold, with one drifted citation (`protocol_issues` is now declared at
`core_bridge.py:196`, filled at `:214`, emitted at `:234`).

Today a coherence error would land in `protocol_issues: List[str]`, which `ValidationPanel.tsx:49`
renders uniformly as `text-warning`; `errorCount` (`:25`) reads only `stage_issues.filter(s => !s.ok)`;
and `report.ok` is **never read anywhere in the frontend**. A category error would show a yellow
"Valid, with 1 protocol note(s)" while the CLI exits 1.

Three changes, and all three are required — a key added to the report dict alone is a silent no-op
on the wire, as `StageIssue.continuity` already proves:

1. An error-severity channel in the payload: the dict key, the pydantic field, **and** the TS
   interface.
2. `ok` computed from it. Note this also changes `validate --manifest`'s exit code (`cli.py:730`)
   and `_sim_findings`' "Validation: OK" line — intended, but a scripting back-compat point for the
   PR body.
3. The badge ladder (`ValidationPanel.tsx:29-33`). `Badge` already accepts `error`; no new tone.

`validate --manifest`'s escalation is keyed on suggestion **kind**
(`kind in ("continuity_gap","missing_run")`, `cli.py:732`), not severity. A coherence finding with a
new kind is exit-code-inert unless that tuple is widened, and no test covers it.

There is **no `ValidationPanel` test file** — the badge ladder, the three-state logic and the
warning list are untested today. This needs a new file, not an edited one.

**Verify:** a `natom` category error shows a red badge and `ok: false` and exits 1; a `temp0`
difference shows a note and exits 0; an untagged document's panel is pixel-unchanged.

## Task 8 — Canvas lineage bands

Only three things are genuinely missing; do not re-derive what 2a shipped.

1. **A band affordance naming the member.** Render it only when the phase holds more than one
   member, or every existing single-lineage manifest grows spurious chrome. The collapsed-band
   label currently shows `g.base`, which *includes* the directory (`rep1/prod × 8 steps`), while the
   suggestion prose shows the tag (`rep2/prod`) — the band header must show the tag and fall back to
   the base. Do not key React children or the `expanded` set by base or by lineage; both collide
   (`PhaseSection.test.tsx:131-143` pins the first-step-id keying).
2. **Arrow suppression between bands.** Key it on the **lineage** changing, not the group changing.
   `above` is threaded across group boundaries on purpose (`:109-117`): `01_min`, `02_nvt`,
   `03_npt` are three groups of one, and an arrow drawn only inside a group vanishes there
   entirely — pinned by `Canvas.continuity.test.tsx:167-203`. Handle the ghost tail: ghosts do not
   advance `previous` (`:139`), so the arrow above the next band's first step still references the
   previous band's last real step. Measured today: a `rep1,rep1,rep2,rep2` phase draws 3 arrows
   including the cross-band one; the real crashed-replica tree draws 8.
3. **A fan-out indicator** above the bands marking the shared branch point.

**Verify:** the crashed-replica tree renders 3 bands, no cross-band arrows, ghosts still inside
rep2's band; an untagged document renders exactly as before (271 vitest green); bundle rebuilt and
committed.

## Task 9 — Bulk tagging

1. **Make `lineage` writable on `PUT /steps/{id}`** — the single-step corrective control, and the
   silent no-op closed. `StepUpdate.lineage` is already declared as a top-level field precisely so
   it inherits `topology`'s `model_fields_set` presence semantics (absent = leave, null = clear)
   rather than `files`' `""`-clears rule.
2. **A bulk route taking an explicit step-id list** plus one patch. Follow the two ordering
   invariants every existing mutator observes and comments: validate all ids **before**
   `_snapshot()`, so a partial failure leaves neither a half-applied tag nor an undo frame that
   reverses nothing; and assign `self._warnings` **after** the snapshot, which clears them
   (`document.py:396`, `:496`). All-or-nothing under the single `RLock`.
3. **A post-tag sweep — this is the load-bearing part.** Retagging strands existing
   `input_coords.ref`s across the new boundary and nothing catches it today. After applying tags,
   re-examine every ref in the affected scope: a ref that now crosses a non-null tag boundary
   reverts to `starting_structure` and the route reports it. Silence is recoverable; a false edge
   that names a real file from the wrong replica is not.
4. **UI**: a band-header retag control and an apply-inferred-layout-tags action. `StepCreatePayload`
   and `StepUpdatePayload` (`types/index.ts:91-100`) both lack `lineage` today — the client cannot
   send a tag on any route. Selection state is strictly single-select
   (`state/selection.tsx:2-3`), so drive the bulk control from the band, not from a multi-select
   gesture.

Two behaviours to know and to state in the PR body: the first successful bulk tag flips
`relink_restarts` off for that document permanently (`simulation.py:340-341` returns early on
`>= 2` members) — intentional, but it changes behaviour far outside itself. And undo eviction is at
the **101st** per-step PUT, not the 100th (`_push` pops only on `> limit`).

**Verify:** tagging 200 steps is one request and one undo unit; asserting on the resulting *value*,
never the 200 status code; the retag-strands-a-ref case produces `starting_structure` plus a
warning, and `_cross_lineage_refs` (`tests/test_gui_document.py:484`) stays empty.

## Task 10 — CLI printing

- `discover` prints only the suggestion `title` (`cli.py:309`), so the per-member breakdown that
  already exists in `lineage_group`'s `evidence` (`rep1: 3 run(s); rep2: 1 run(s); …`) never reaches
  the terminal. Print evidence for `lineage_group` only — appending it for every kind would also
  dump `role_guess`'s `Equilibration->equilibration; Heating->heating; …` into the block.
  `docs/cli.md:387-389` already *claims* the breakdown is printed, so this makes an existing doc
  true rather than needing new prose.
- `_print_simulation` shows no tag on any step line. Add it, emit-when-set.
- `plan` and `validate --manifest` print the per-lineage totals when multi-lineage.
- `docs/cli.md:18` is stale in the other direction — it says discover/export are "not yet wired into
  that checker" when both are in `BLOCK_ORDER` and are checked.

**Verify:** the campaign tree prints three members and their run counts; an untagged tree's output
is unchanged, character for character.

## Task 11 — Docs

`manifest.md`, `api.md`, `gui.md`, `architecture.md`, `cli.md`, `recipes.md`, `tutorials.md`,
`README.md`. Specifically: the `totals` shape is stated at `docs/api.md:365-371`, `:597`,
`docs/gui.md:263`, `:376`, `docs/architecture.md:295`, `README.md:243`, and every one of them
drifts when `lineage_count` lands. The 2a replica sections (`cli.md:369-400`, `:569-585`) sit
outside the generated markers and are hand-edited.

Regenerate `docs/cli.md` on the 3.11 interpreter for the `--strict` help change (Task 3).

## Task 12 — Whole-branch review and ship

Review the full branch diff adversarially before opening the PR, through the real HTTP API and the
real CLI rather than by reading. The 2a sweep found three live fabrication routes and a multi-hop
cycle that per-commit review had missed, all reachable only by driving the actual surfaces.

Then: full suite on **both** 3.9 and 3.12, vitest, `npm run build` with the bundle committed,
`export_cli_help.py --check` on 3.11, and a PR body that names the two behaviour changes a user
can notice — `plan --strict` now failing on findings, and `ok` now false for a category error.

---

## Sequencing

1, 2, 3 are independent of the rest and of each other except that 1 comes first. 4 depends on 1.
5 blocks the seed half of 6. 6 blocks 7. 8 and 9 are the frontend pair and share a bundle rebuild.
10 touches `cli.py:263-276`, which 3 also touches — do 3 first. 11 and 12 last.
