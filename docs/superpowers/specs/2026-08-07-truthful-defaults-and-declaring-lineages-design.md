# Truthful defaults, and a way to declare lineages

**Date:** 2026-08-07
**Status:** approved, ready for planning
**Supersedes nothing.** Builds on `2026-07-31-run-lineages-design.md` (PR1 #74, PR2a #75, PR2b #77).

## Why

AmberMeta was pointed at a real campaign — `/store7/gentile/data/simulations/sys021`, 1097 runs
across `equil/01..05` and `prod/01..05` — and could not be told the thing the run-lineages work
exists to express: that these are five replicas.

That much was expected to be hard. What the investigation found is that the tool does not merely
decline to make the claim. It makes several false ones, and they validate clean:

- Discover asserts **nine continuations that never happened** (`equil/01 → equil/02` … `equil/05 →
  prod/01`, `prod/01 → prod/02` …), pools all 1006 production chunks into one 1006-long sequence,
  and publishes the campaign as a single serial 5.055 µs run with `ok: true` and zero warnings.
- Five production chunks were queued and never ran (`prod/01/nvt_prod_0202`,
  `prod/{02..05}/nvt_prod_0201`; each `nstlim=2500000, dt=0.002`). Their 25 ns is counted as
  simulated time, because totals are derived from the mdin alone.
- The five genuine handoffs — every `prod/NN` head reads its own `equil/NN/18_ntp_equi.restrt`,
  and AMBER recorded that in the mdout — are ignored entirely.

So the number that would reach a methods section is wrong in two directions at once, and the
structure that would make it right cannot be entered.

The through-line of this spec: **AmberMeta should only claim what the files support.**

## Scope

| | In this spec | Later, own spec |
| --- | --- | --- |
| P1 | Truthful defaults | |
| P2 | Declaring lineages | |
| P3 | | Per-lineage topology (`PATCH /steps/topology`, per-member control) |
| P4 | | Multi-axis campaigns (condition axes vs member axes) |

P3 and P4 are deliberately excluded. P4 in particular is a one-way door on the manifest format —
`coherence()` currently emits `Finding("warning", "parameter", "Members differ in temp0 …")` for
every axis that varies, which is correct for a replica set and wrong for a deliberate temperature
sweep. That decision should not be made as a side effect of fixing `sys021`. Nothing in this spec
forecloses it: `Step.lineage` stays a free string.

Vocabulary is settled by the existing code and needs no change. `simulation.py:45` reads *"Which
run lineage (replica, branch, pose) this step belongs to."* **Lineage** is the general term; a
replica is one kind of lineage; branching is already in-model, since `crosses_lineage()`
(`simulation.py:273-292`) accepts a cross-member ref with a warning because that is the only way
to record a genuine branch.

---

# P1 — Truthful defaults

## P1.1 Totals come from what ran

`SimulationProtocol._sum_stages` (`protocol.py:541-557`) derives both `steps` and `time_ps` from
the mdin, never asking whether the run produced output:

```python
length = getattr(stage.mdin.details, "length_steps", 0) or 0
dt = getattr(stage.mdin.details, "dt", 0) or 0
total_steps += float(length)
total_time  += float(length) * float(dt)
```

Replace with a four-way rule sourced from the mdout:

| State | Contributes | Detection |
| --- | --- | --- |
| Ran (complete or truncated) | `elapsed_ps` (below), and `elapsed_ps / dt` steps | `stage.mdout` and `stage.mdout_header` both present, `stats.count > 0`, `begin_time_ps` not None |
| Minimisation | nothing, no note | `mdout.details.run_type == "Minimization"` — a min mdout prints `NSTEP ENERGY RMS GMAX`, never `TIME(PS)`, so it has no elapsed time and never had one |
| Ran, mdout unusable | nothing, plus a note | `stage.mdout is not None` but `stats.count == 0`, or `mdout_header is None`, or `begin_time_ps is None` |
| Queued | nothing, plus the `queued` status (P1.2) | `stage.mdin` present, `stage.mdout is None` |

**The formula is `elapsed_ps = stats.time_end - mdout_header.begin_time_ps`.** This is
load-bearing and was verified against the repo's own fixtures before being written down:

- `stats.time_end` is an **absolute** AMBER clock reading, not a duration. The back-compat
  fixture's five chunks read 20920 / 40920 / 60920 / 80920 / 100920 ps against a true 100,000 ps
  total. Summing `time_end` directly yields 304,600 ps — a worse bug than the one being fixed.
- `stats.time_end - stats.time_start` is **not** the alternative: `time_start` is the first
  *printed* frame, one `ntpr` interval after the true begin, giving 99,500 ps.
  `protocol.py:451-456` already documents this exact trap.
- The chosen formula reproduces the committed golden exactly:
  `sum(time_end - begin_time_ps) == 100000.0` and `sum(elapsed/dt) == 25000000.0`, which is what
  `tests/data/lineage_backcompat/summary.json` already holds. **No golden regeneration is
  expected**, and any movement in those files is a signal the formula is wrong, not a routine
  rebase.

"The final NSTEP" is **not** retrievable — `ThermoStats.add_frame` parses the NSTEP key and
discards it, and `MdoutMetadata.nstlim` is the control-data *intent*, identical to the mdin's.
Steps-that-ran are therefore derived as `elapsed_ps / dt`.

The `+=`-not-`sum()` accumulation in the current docstring must survive the rewrite: CPython
3.12's `sum` is compensated, CI runs 3.9 *and* 3.12, and the goldens compare floats.

Sourcing from elapsed mdout time rather than `nstlim × dt` is strictly more truthful and fixes a
second latent bug: a crashed or wall-clock-killed run is currently rounded up to its full intent.

**Blast radius, accepted:** this changes reported totals for every existing project, not only
replicated ones. Any project containing a truncated or queued run will report a smaller number
than before.

**Landing:** the new rule is the only rule — no flag, no manifest version bump, no second code
path.

**Where the delta is reported.** The v2 manifest stores no totals — `simulation_to_payload` emits
version/simulation/phases/steps and nothing else — so there is no stored number in the manifest to
compare against, and the spec is not changing the format to add one. The comparison is made
against a previously written **`summary.json`**, which is where totals actually live. When `plan`
is about to overwrite a `summary.json` whose `totals` disagree with the recomputed ones, it says
so before writing:

```
totals changed since the last summary.json in this directory:
  time_ps  5,055,000 → 5,030,000
  reason   5 queued runs no longer counted (mdin present, no mdout)
  runs     1006 → 1001 completed, +5 queued
```

Where no prior `summary.json` exists, nothing is reported — there is no claim to contradict.
Keeping the old number reachable behind a flag would invite citing it; changing it silently would
surface the discrepancy at the worst possible moment.

## P1.2 Queued runs are kept, cost nothing, and are reported

A stem with an mdin and no mdout becomes a step with status `queued`. It stays in the manifest —
the `.in` is real evidence of intent, and dropping it would hide that a campaign was cut short —
contributes 0 ps, and is reported:

```
Production · lineage 01
  nvt_prod_0201   ✓  5000 ps
  nvt_prod_0202   ○  queued, not run

completed  201 runs · 1,005,000 ps
queued       1 run  · not counted
```

This also removes a false positive that exists today. The current `missing_run` finding names
member `202`, which is not missing — it is queued. The phantom comes from the same mdin-only
blindness as P1.1, and the real asymmetry (lineage 01 completed through `0201`, lineages 02–05
through `0200`) becomes legible instead.

## P1.3 Never write an edge that crosses a run directory

`core_bridge.py:495-525`: with no tags, `multi_lineage = False`, every step lands in one
`UNTAGGED` bucket, and one flat chain is written across all 1097 steps regardless of directory.

Those edges then **self-validate**, which is why nothing catches them: `resolve_input_coords`
hands the consumer the producer's *own* restart, so `_check_stage_pair` compares the producer's
end time against its own restart and gets `observed_gap_ps = 0.0`.

New rule, in one sentence: **the tool writes an edge only within a run directory; anything
crossing a directory boundary is proposed, never written.**

| Evidence | Action |
| --- | --- |
| Same run directory, consecutive stems (`nvt_prod_0001 → 0002`) | **write** — existing behaviour, cannot be wrong about membership because it never leaves the directory |
| `MdoutHeader.assignment("INPCRD")` names a file another step wrote | **propose** (see P2.4) |
| Anything else | nothing — the step reads `starting_structure` |

A step with no written producer reports continuity as *not measured*, not as a zero gap.

A `queued` step still receives its within-directory edge — `nvt_prod_0202` continues from
`nvt_prod_0201` as its mdin says it would. The edge records a declared intent; the step simply
contributes no time. Continuity checks skip it, since there is no observed end time to compare.

The asymmetry is deliberate and follows from the evidence hierarchy: if AMBER's own log only
proposes, a naming convention cannot write. Within-directory chaining survives because removing
it would gut the default output of every existing single-replica project, and because a
cross-directory boundary is precisely where both the nine bogus edges and the five real handoffs
live.

On `sys021` this removes all nine false edges.

## P1.4 Fix the documentation and wire contracts that misled

Four sources actively state the opposite of the code:

| Location | Says | Truth |
| --- | --- | --- |
| `schemas.py:70-73` | *"the GUI only displays it"* | `routes.py:357-358` writes it |
| `schemas.py:200-203` | *"The tag is read-only at this surface today: no route writes it."* | `routes.py:380-395` `PATCH /steps/lineage`, covered by `tests/test_gui_bulk_lineage.py:59-65` |
| `docs/gui.md:146,489`; `README.md:267,315` | *"These inline editors are stubs today"* | `StepInspector.tsx:33-225` fully implements name, topology, Source select, "Continues from", `reads:` readback, reverse consumer list — shipped in PR2a (#75) |
| `routes.py:409-412` | *"the run names do not distinguish members by one directory segment"* | On `sys021` they do; the real refusal is the rival-cohort rule (P2.1) |

The stale `schemas.py` contracts are the most consequential: they are the likely reason the
frontend never grew a tagging affordance beyond `LineageBand`.

---

# P2 — Declaring lineages

## P2.1 Widened inference, reconciled per cohort

`infer_lineages_from_layout` (`lineages.py`) refuses `sys021` at:

```python
matched = [dirs for dirs in cohorts.values() if len(dirs) > 1]
if len(matched) != 1:
    return {}
```

Cohorts are keyed by `frozenset(_run_base(r) for r in runs)`. `equil/*` holds 18 run bases;
`prod/*` holds `{nvt_prod}` (and `{cpptraj, nvt_prod}` for `prod/01`). Different frozensets →
rival cohorts → `len(matched) != 1` → `{}`. Verified against the real tree: `equil/` alone yields
`01..05`, `prod/` alone yields `01..05`, together `{}`. The wanted tags are computed and discarded.

**New rule**, in five steps:

1. Group directories into cohorts by run-base frozenset, as today.
2. For each cohort holding **more than one** directory: check depth uniformity *within that
   cohort*, and compute *that cohort's own* varying segment index. A cohort that fails either
   check contributes nothing — it does **not** refuse the whole tree. (Required by
   `test_a_prep_run_at_a_different_depth_does_not_block_the_replicas`.)
3. Require every contributing cohort to agree on the **same** segment index. Otherwise refuse —
   two cohorts naming their member at different depths must not silently merge.
4. Require the contributing tag sets to be **nested**: sort by size, and every set must be a
   subset of the largest. Otherwise refuse. The reconciled tag set is the largest.
5. **Absorb singleton directories.** A directory dropped at step 2 for being alone in its cohort
   is tagged if it is deep enough to have a segment at the agreed index *and* that segment is
   already in the reconciled tag set.

> **This rule was rewritten after the first draft was tested and failed.** The obvious version —
> *"if every cohort yields the same tag set, accept"* — **refuses `sys021`**, the exact tree this
> feature exists to fix. Reconstructed and executed against the real shape: `equil/*` cohorts on
> 18 shared run bases → `{01..05}`; but `prod/01` also holds `cpptraj`, so its base set is
> `{cpptraj, nvt_prod}` while `prod/02..05` hold `{nvt_prod}`. `prod/01` is therefore alone in its
> cohort, is dropped by `len(dirs) > 1`, and the surviving prod cohort yields only `{02,03,04,05}`.
> Two unequal sets → refuse. Steps 4 and 5 exist precisely to survive this: `{02..05}` is a subset
> of `{01..05}`, and `prod/01`'s segment at index 1 is `01`, which is already a reconciled tag.

Worked through on `sys021`:

```
equil/01..05   bases {18 shared}      → index 1 → {01,02,03,04,05}
prod/02..05    bases {nvt_prod}       → index 1 → {02,03,04,05}
prod/01        bases {cpptraj,nvt_prod} → alone in its cohort → dropped at step 2

step 3: both contributing cohorts agree on index 1            ✓
step 4: {02..05} ⊂ {01..05}  → reconciled = {01,02,03,04,05}  ✓
step 5: prod/01 segment[1] == "01" ∈ reconciled → tagged 01   ✓
```

Every existing refusal still refuses, and this is the acceptance criterion for the rule:

| Existing test | Shape | Why it still refuses |
| --- | --- | --- |
| `test_two_rival_families_tag_neither` | `{rep1,rep2}` vs `{ctrl1,ctrl2}` | Disjoint, so neither is a subset of the other — step 4 refuses |
| `test_a_shared_prep_directory_stays_untagged_and_out_of_the_count` | `common/` beside `rep1..3` | `common` is not in the reconciled tag set — step 5 does not absorb it |
| `test_runs_at_the_tree_root_fail_the_predicate…` | runs at depth 0 | The `if d` filter is kept unchanged |
| `test_a_single_lineage_in_a_subdirectory_stays_untagged` | one directory | The `len(candidates) < 2` guard is kept unchanged |
| `test_lineages.py::…nested_sweep…` | `300K/rep1` … | One cohort, two segments vary → contributes nothing → no contributing cohorts → refuse |

> **Implementation trap, verified empirically.** Do *not* union the directories and then look for
> the varying segment. The union has two segments varying (`equil|prod` at index 0, `01..05` at
> index 1), so `if len(varying) != 1: return {}` refuses one line later. Reconcile per cohort;
> never union first.

Nested sweeps continue to refuse, and become P4's problem.

**Blast radius.** `infer_lineages_from_layout` has **four** call sites, not one:
`protocol.py:1883` (inside `smart_group_files`, feeding `detect_numeric_sequences`),
`protocol.py:1961` (`plan --recursive`), `core_bridge.py:491` (`discover_draft`), and
`document.py:557` (`apply_inferred_lineages`). Widening it changes sequence-family pooling on
every existing project, so the sequence-note assertions in `test_continuity_p1.py` and
`test_gui_core_bridge_sim.py` are part of this task's verification, not a later surprise. Note
also that `document.py:557` passes `[s.name for s in steps]` — open-document names, possibly
hand-renamed — not scan-derived stems.

The function is re-exported at `ambermeta/__init__.py:22` and documented in `docs/api.md:107` as
`(run_names) -> Dict[str, str]`. **Its signature does not change.** The proposal object of P2.2 is
built by a new function alongside it, not by changing this one's return type.

## P2.2 Propose, never apply

Inference gains a preview mode. Discover returns a **proposal** alongside the draft and writes
nothing. The canvas renders a review strip:

```
Discovered 1097 runs in sys021.

┌─ 10 run directories look like 5 repeated members ──────┐
│ Segment 2 of the path names the member.  [Change ▾]    │
│                                                        │
│   01  ← equil/01 (18)  + prod/01 (202)                 │
│   02  ← equil/02 (18)  + prod/02 (201)                 │
│   …                                                    │
│        [ Accept ]  [ Not replicas ]                    │
└────────────────────────────────────────────────────────┘
```

Accepting issues one `PATCH /api/steps/lineage` per tag — the route takes an arbitrary cross-phase
id list, applies in one edit and one undo entry, and auto-severs any restart link the edit turned
into a cross-member claim (`document.set_lineages`, `_crossing_refs`, `_sever_crossed_refs`).

`[Change ▾]` lets the user pick a different path segment when the proposal picked the wrong one.

Where inference refuses outright, the strip is replaced by a `needs_you` card rather than the
silence emitted today (`core_bridge.py:340-341` guards the lineage card behind `if declared:`
with no `else`). That card is built in `discover_draft` and appended, **not** added to
`build_suggestions` — the latter is called from three places and has no access to the scan, which
its own comment at `:331-335` already records.

**The proposal still drives phase layout; it just writes no tags.** `multi_lineage`
(`core_bridge.py:495`) currently gates phase-major grouping *and* chaining off written tags. If
Discover stopped tagging, phase-major grouping would vanish for every tree and
`test_discover_draft_groups_same_role_steps_from_every_lineage_into_one_phase` and
`test_discover_draft_opens_a_new_phase_when_a_role_recurs` would both break. So `multi_lineage`
is re-derived from *the proposal* rather than from `Step.lineage`: layout is unchanged,
`Step.lineage` stays `None` until Accept, and bands correctly do not render before then.

**The existing "Infer lineages" button must go.** `SimHeader.tsx:122-130` already ships one,
wired to `useInferLineages()` → `POST /api/steps/infer-lineages`, which writes tags with **no
preview**. Shipping P2.2 beside it would leave two contradictory inference affordances in one
app. It is removed and replaced by the `Define replicas…` entry point of P2.3. It has no test
coverage, so nothing pins it — but `api.inferLineages` / `useInferLineages` and their `import`s
must be removed with it, because `noUnusedLocals` makes a dangling import a hard build failure.
The `POST /steps/infer-lineages` route itself stays, repointed to return a proposal.

## P2.3 "Define replicas…" — declaring members by hand

The confirm strip only appears when inference succeeded. Inference will keep refusing on purpose:
nested sweeps (P4), and any tree where no single path segment names the member. Without a manual
path, those users are exactly where this spec started.

**The bootstrap deadlock, and why the obvious fix is wrong.** `PhaseSection.tsx:274` reads
`const showBands = bands.some((b) => b.lineage !== null)`, so with nothing tagged no band renders,
and `LineageBand` is the only caller of `useSetLineages` in the entire frontend — no lineage
control exists in the Inspector or on the step card, and selection is single-select. The tempting
one-line fix is to make `showBands` unconditional. **It must not be done.** `bandsOf`
(`PhaseSection.tsx:185-193`) merges *adjacent* entries sharing a tag, so in a fully untagged
document every step collapses into one band per phase, and `LineageBand`'s rename applies to
`steps.map((s) => s.id)` — every step in that band. On `sys021` that is a control which tags all
~1007 production steps as a single member in one keystroke. `LineageBand` is a post-tagging
*editing* surface — its own docstring says a phase-major document "produces one band per member",
which presupposes members — and it does that job correctly. It is not a way to create members
from nothing, and ungating it does not make it one. `showBands` stays as it is.

**The fix:** the strip becomes openable on demand, from a top-bar `Define replicas…` action,
regardless of document state:

```
┌─ Define replicas ──────────────────────────┐
│ Which part of the path names the replica?  │
│                                            │
│   [ equil|prod ]  [ 01…05 ]◀  [ run stem ] │
│                                            │
│   01  ← equil/01 (18) + prod/01 (202)      │
│   02  ← equil/02 (18) + prod/02 (201)      │
│   …                                        │
│                     [ Apply ]  [ Cancel ]  │
└────────────────────────────────────────────┘
```

Segments are read off the run paths actually present; picking one regroups the preview live. This
is the same component as the confirm strip, in a mode where the user supplies the segment instead
of inference proposing it — so `[Change ▾]` in the confirm strip and `Define replicas…` from the
top bar land in the same place.

**Preview rows are editable.** Each proposed member's tag can be overridden before Apply. The
segment picker gets a regular tree ~all the way there; hand-editing the rows covers the irregular
remainder without building a second navigation model. A tree where members cannot be expressed as
whole run directories at all remains out of reach, and that limitation is accepted here — the full
per-run assignment table is P3/P4 territory.

Applying issues the same `PATCH /api/steps/lineage` calls as accepting a proposal: one per tag,
one undo entry each, cross-member links auto-severed.

Partially-tagged documents already work today and are unaffected: once any member exists,
`showBands` is true, the untagged remainder renders as a "no lineage" band, and `LineageBand`
retags it correctly.

## P2.4 The handoff proposal, from AMBER's own record

`MdoutHeader.file_assignments` (`mdout_header.py:66`) parses AMBER's File Assignments block,
including the `INPCRD:` line. Its own docstring at `:14` calls it *"the chain AMBER itself
asserts."* It has **zero call sites** outside its own module and tests.

That is the ground truth for "which equil feeds which prod", parsed on every mdout since before
this work began and thrown away. On `sys021`, every `prod/NN` head's mdout names
`equil/NN/18_ntp_equi.restrt`.

Wire it into the proposal — not into the manifest. A second strip line:

```
┌─ 5 production runs name their own equilibration in the mdout ─┐
│    01 ← equil/01/18_ntp_equi.restrt                           │
│    02 ← equil/02/18_ntp_equi.restrt                           │
│    …                                                          │
│   [ Wire these ]  [ Leave unlinked ]                          │
└───────────────────────────────────────────────────────────────┘
```

No content hashing is introduced. The package contains none (`grep -rn "hashlib|md5|sha1|samefile"
ambermeta/` returns nothing), and AMBER's own record is better evidence than a byte comparison
anyway: it says what the run *read*, not what happens to match.

Accepting issues `PUT /api/steps/{id}` per edge. The route already refuses dead refs, self-refs,
null refs and cycles with 400, and returns `resolved_input_coords` so the client never
re-implements resolution.

**Order matters, and the order is: tags first, then handoffs.** The two operations interact.
`set_lineages` runs `_sever_crossed_refs`, which rewrites to `starting_structure` any edge *this
edit* turned into a cross-member link; and `_check_continues_from` accepts a cross-member ref with
a "branch, not a continuation" warning. Writing handoffs first and tagging second would therefore
delete the edges just written. Tagging first is safe because a handoff within one member —
`equil/01 → prod/01`, both tagged `01` — is not a crossing at all, so it draws neither the sever
nor the warning. P1.3's within-directory edges likewise never cross a member boundary when a
member is a whole directory, so tagging severs nothing. This ordering has no existing test and
gets one.

**Accept is N transactions, not one.** `PATCH /steps/lineage` raises 404 on the first unknown id
and applies nothing (pinned by `test_one_bad_id_changes_nothing`), but five tags are five separate
requests and five undo frames; a failure on the third leaves two applied. Step ids are freshly
generated on every Discover, so a proposal held across a re-Discover is stale by construction —
which is the 400-plus-re-proposal case in Error handling below. The strip reports partial
application rather than claiming success.

`MdoutHeader.assignment("INPCRD")` returns `None` when AMBER clipped the value at the field
width, which is common for long paths. That is "no evidence", not "no producer" — such a step
simply gets no proposed edge. Discovery does not read mdout headers today; the new read matches
the existing fault tolerance in `discover_draft`, which catches
`(IOError, OSError, ValueError, LookupError)` around its mdin parse.

## P2.5 Discover stops eating tags

`routes.py:103-113` replaces the document wholesale:

```python
out = core_bridge.discover_draft(...)
store.replace(simulation=out["simulation"], ..., reset_history=False)
```

Re-running Discover — the most prominent button in the top bar, and the natural reflex after
adding files — silently drops every tag. `reset_history=False` means Ctrl+Z recovers it, but
nothing says so.

Re-discovery preserves existing tags by matching step identity (directory + run stem), and reports
any it could not carry over.

## P2.6 The payoff is visible, and cheap

`ValidationReport.lineages`, `PlanResult.lineages` and `totals.lineage_count` are typed in
`types/index.ts:56,66,91` and read nowhere; `ValidationPanel.tsx:94-96` renders only `stage_count`
and `time_ps`. `StageIssue.continuity` likewise reaches the wire and is dropped. The CLI does print
them (`cli.py:426-452`).

Render per-lineage counts and totals in the confirm strip and the validation panel.

This is affordable **because of P1.1**: totals now come from mdout headers, which discovery already
parses, rather than from opening trajectories. Measured on the real tree, `POST /api/validate`
takes **1622 s and reads ~28 GB**; Discover takes 2.4 s. The reward for tagging must not be a
27-minute blocking call with no progress and no cancel.

---

# Architecture and boundaries

Each change lands in the module that already owns the concern; no new modules.

| Unit | Owns | Changes |
| --- | --- | --- |
| `protocol.py` | run/stage totals | P1.1 completed-vs-queued sourcing from mdout |
| `mdout_header.py` | AMBER's File Assignments | P2.4 — first call site for existing dead code |
| `lineages.py` | membership inference | P2.1 per-cohort reconciliation |
| `simulation.py` | model + continuity | P1.2 `queued` status |
| `gui/api/core_bridge.py` | draft construction | P1.3 edge rule, P2.2 proposal, P2.6 totals |
| `gui/api/routes.py` | HTTP surface | P2.2 preview mode, P2.5 tag preservation, P1.4 message |
| `gui/api/schemas.py` | wire contract | P1.4 corrected docs, proposal type |
| `Canvas/PhaseSection.tsx` | phase layout | **unchanged** — see P2.3 on why `showBands` stays |
| new `Canvas/ProposalStrip.tsx` | the review strip, in both proposed and manual modes | P2.2, P2.3, P2.4, P2.6 |
| `TopBar/TopBar.tsx` | actions | P2.3 `Define replicas…` (a 7th prop; `TopBar.test.tsx:14-15` passes all six explicitly and must be updated) |
| `Canvas/SimHeader.tsx` | simulation header | P2.2 — remove the old no-preview "Infer lineages" button |
| `tests/conftest.py` | fixture trees | optional mdout writer + explicit-content arm for `write_run_tree` |
| `TopBar/ValidationPanel.tsx` | findings | P2.6 per-lineage totals |

The proposal is a **response-shaped object, not stored state** — it is derived from the draft on
each Discover and discarded on accept or decline. Nothing in the manifest format changes:
`Step.lineage` remains `Optional[str]`, emitted only when set (`simulation.py:87-88`), so a
document that declares no lineages keeps the exact step block it had before.

## Error handling

- Inference refusal is a *reported* outcome, not silence: a `needs_you` card naming why.
- An mdout that fails to parse costs a note and contributes nothing. It never fails the run —
  this preserves the Spec 1 fault tolerance where a skipped file costs a note and exit 0.
- Accepting a proposal that has gone stale (the document changed underneath) is refused with a
  400 and a re-proposal, rather than applying against shifted ids.
- Tag preservation across re-discovery reports unmatched tags rather than dropping them quietly.

## Testing

**The existing fixture helper cannot express any of this and must be extended first.**
`tests/conftest.py:write_run_tree` writes **mdin only**, deliberately, so under P1.1 every
existing lineage fixture becomes entirely `queued` with `0.0 ps` totals — and
`test_lineage_totals.py:67` (`breakdown["rep2"]["time_ps"] < breakdown["rep1"]["time_ps"]`)
degenerates to `0.0 < 0.0` and fails. The helper gains an optional mdout writer emitting a
`begin time read from input coords` header line, a File Assignments block and a few
`NSTEP = … TIME(PS) =` records. It also picks mdin content by
`next(k for k in _REPLICA_MDIN if k in Path(stem).name)`, which raises `StopIteration` on stems
like `18_ntp_equi` or `cpptraj` — so it needs an explicit-content arm before a `sys021` fixture
can exist at all.

A fixture built from the real `sys021` structure — full directory layout and run stems, with tiny
synthetic mdins/mdouts and no trajectories — asserting:

1. `infer_lineages_from_layout` yields `{01..05}` for the combined tree (P2.1), and still returns
   `{}` for a nested-sweep layout where two segments vary within one cohort.
2. Exactly five cross-directory edges are *proposed* from INPCRD evidence, and **zero**
   cross-directory edges are written (P1.3, P2.4).
3. Within-directory chaining is unchanged for a single-directory chunked run (P1.3 regression).
4. Five steps carry status `queued`; totals are 5,030,000 ps, not 5,055,000 (P1.1, P1.2).
5. A truncated mdout counts its actual `time_end`, not `nstlim × dt` (P1.1).
6. `validate` on a manifest with stored older totals reports the delta and the reason (P1.1).
7. Re-running Discover preserves tags (P2.5).
8. `Define replicas…` is available on a fully untagged document, its segment picker offers every
   segment present in the run paths, picking one regroups the preview, an edited preview row
   overrides the tag it applies, and Apply issues one `PATCH /steps/lineage` per distinct tag
   (P2.3).
9. `LineageBand.test.tsx:84-95` is **kept as-is**: an untagged phase must continue to render no
   band. It now pins a deliberate decision rather than an accident, and its comment should say so.
10. `test_lineage_backcompat` continues to prove manifests without `lineage:` round-trip
    byte-identically.

## Out of scope, recorded so it is not lost

- **`cpptraj.in` is classified as an AMBER mdin** (`files.py:26-29`, whose own NOTE calls the
  content sniff "a follow-up"; `protocol.py:1843`),
  fabricating a phantom Production step, splitting `prod/01` into its own cohort, and inserting
  itself as the producer of `prod/01/nvt_prod_0001` (which therefore resolves to `null`). P2.1's
  per-cohort reconciliation makes this harmless for inference, but the phantom step remains.
  Fixing it means sniffing `.in` files for an `&cntrl` namelist, which reclassifies files in every
  existing project.
- **P1.3's directory rule is enforced at discovery only.** Two other code paths also create
  `input_coords.ref`s and are keyed on lineage rather than on directory: `relink_restarts`
  (`simulation.py:306-361`), whose multi-member guard does not trip on an untagged document, and
  `repair_dangling_refs` (`simulation.py:364-407`), whose `same_lineage` filter matches every step
  when nothing is tagged. `document.py:394` auto-chains a newly created step to its phase
  neighbour for the same reason. So a reorder, a delete or a step-add can still re-create a
  cross-directory edge that discovery would no longer write. Closing this means giving those three
  the same directory predicate, and is deliberately not in this spec.
- **`ambermeta init`'s v2 template** (`cli.py:1069-1140`) emits no `lineage:` key, teaching the
  wrong shape to anyone hand-authoring.
- **`n_atoms` is computed at discovery and dropped** — `topology_pool.Topology` has it,
  `simulation.Topology` does not — so `coherence()` cannot compare topology bindings across
  members and a lineage bound to the wrong prmtop produces no finding unless atom counts differ.
- **A lineage has no identity**: no roster on `DocumentResponse`, no ordering, no rename primitive
  distinct from re-tagging every step. Deferred to P3/P4.
- **`validate` has no progress or cancel channel** despite taking 27 minutes on a real campaign.
