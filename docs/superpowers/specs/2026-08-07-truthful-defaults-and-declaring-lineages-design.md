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

Replace with a three-way rule sourced from the mdout, which the parser already produces —
`legacy_extractors/mdout.py:406` tracks `NSTEP = … TIME(PS)` and `:543` computes
`global_end = last_stats.time_end`:

| State | Contributes | Detection |
| --- | --- | --- |
| Ran to completion | `time_end` from the final `NSTEP` record | mdout present and parseable |
| Ran, truncated | `time_end` from the final `NSTEP` record | same — a run killed at 60% counts 60% |
| Ran, mdout unparseable | nothing, plus a note | mdout present, parse failed |
| Queued | nothing | mdin present, no mdout |

Sourcing from `time_end` rather than `nstlim × dt` is strictly more truthful and fixes a second
latent bug: a crashed or wall-clock-killed run is currently rounded up to its full intent.

**Blast radius, accepted:** this changes reported totals for every existing project, not only
replicated ones. Any project containing a truncated or queued run will report a smaller number
than before.

**Landing:** the new rule is the only rule — no flag, no manifest version bump, no second code
path. When `validate` runs against a manifest whose stored totals disagree with the recomputed
ones, it reports the delta and why:

```
totals changed since this manifest was written:
  time_ps  5,055,000 → 5,030,000
  reason   5 queued runs no longer counted (mdin present, no mdout)
  runs     1006 → 1001 completed, +5 queued
```

Keeping the old number reachable behind a flag would invite citing it. Changing it silently would
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

**New rule:** for each cohort with more than one member, compute that cohort's own varying segment
index and its own tag set. If every cohort yields the same tag set, treat them as one campaign
with those members. Otherwise refuse, as today.

```
equil/* → varying index 1 → {01,02,03,04,05}
prod/*  → varying index 1 → {01,02,03,04,05}     same set → 5 members ✓
```

> **Implementation trap, verified empirically.** Do *not* union the directories and then look for
> the varying segment. The union has two segments varying (`equil|prod` at index 0, `01..05` at
> index 1), so `if len(varying) != 1: return {}` refuses one line later. Reconcile per cohort;
> never union first.

Genuinely ambiguous shapes — nested sweeps where two segments vary within a single cohort —
continue to refuse, and become P4's problem.

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

Accepting issues one `PATCH /api/steps/lineage` per tag — the route already takes an arbitrary
cross-phase id list, applies in one edit and one undo entry, and auto-severs any restart link the
edit turned into a cross-member claim (`document.py:522-544, 574-627`).

`[Change ▾]` lets the user pick a different path segment when the proposal picked the wrong one.

Where inference refuses outright, the strip is replaced by a `needs_you` card rather than the
silence emitted today (`core_bridge.py:340-341` guards the lineage card behind `if declared:`
with no `else`).

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
| `TopBar/TopBar.tsx` | actions | P2.3 `Define replicas…` |
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
- **`ambermeta init`'s v2 template** (`cli.py:1069-1140`) emits no `lineage:` key, teaching the
  wrong shape to anyone hand-authoring.
- **`n_atoms` is computed at discovery and dropped** — `topology_pool.Topology` has it,
  `simulation.Topology` does not — so `coherence()` cannot compare topology bindings across
  members and a lineage bound to the wrong prmtop produces no finding unless atom counts differ.
- **A lineage has no identity**: no roster on `DocumentResponse`, no ordering, no rename primitive
  distinct from re-tagging every step. Deferred to P3/P4.
- **`validate` has no progress or cancel channel** despite taking 27 minutes on a real campaign.
