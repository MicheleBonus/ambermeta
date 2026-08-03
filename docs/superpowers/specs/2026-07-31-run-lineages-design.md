# Run lineages: declaring sets of related simulations

Design doc — 2026-07-31

## 1. The problem

A real MD experiment is rarely one run. It is N replicas differing in random seed, or N
productions branching off one equilibrated restart, or N poses of the same system. That
structure is scientifically meaningful metadata: it determines what a reported sampling
time means.

AmberMeta's v2 model represents *sequential continuation* well and *parallelism* not at
all. Worse, it currently asserts continuation that did not happen. Reproduced against a
two-replica tree built from the repo's own fixtures:

```
Phase: Production [production]
  - rep1/prod_0001  input=starting structure
  - rep1/prod_0002  input=restart of rep1/prod_0001 (rep1/prod_0001.rst)
  - rep2/prod_0001  input=restart of rep1/prod_0002 (rep1/prod_0002.rst)   <-- false
  - rep2/prod_0002  input=restart of rep2/prod_0001 (rep2/prod_0001.rst)
```

`discover` claims replica 2 continued from a restart file in replica 1's directory. No
warning, one flat phase. `totals` then reports the sum as one lineage's sampling time.
The failure mode is a confident false claim, not an error.

### 1.1 Topologies in scope

1. N equilibrations differing in `ig` (or T ramp), one production from each.
2. One equilibration, N productions from the same final restart, differing in `ig`.
3. One lineage segmented into chained chunks (`irest=1`). **Already supported.**
4. Shared topology, different starting coordinates (poses, cluster representatives).

Deferred but not to be precluded: multi-topology campaigns (apo/holo, mutants), and
AMBER's own multi-copy modes (`-ng`/`-groupfile`, REMD, GaMD, TI lambda windows).

**Non-preclusion caveat, stated honestly.** Three of the four deferred cases are not
provenance-DAG-shaped. REMD is N coupled walkers exchanging coordinates periodically —
bidirectional and time-indexed, not a directed acyclic provenance edge. TI lambda windows
usually have no provenance edge between them at all; their relationship is a parameter
axis. A groupfile run is one job with N internal replicas that may share one mdout stream.
This design does not claim to generalise to them. It claims only not to *block* them: a
per-step tag plus per-step provenance edges adds no structure that a future parameter-axis
or coupled-walker model would have to undo.

## 2. What already exists (the baseline)

Verified by construction and execution, not by reading alone.

**Fan-out already round-trips with no schema change.** A hand-built three-way branch:

```
ntp_prod_0001  source=starting_structure    -> CH3L1_HUMAN_6NAG.crd
ntp_prod_0002  source=step  ref=st_1        -> ntp_prod_0001.rst
ntp_prod_0003  source=step  ref=st_1        -> ntp_prod_0001.rst
ntp_prod_0004  source=step  ref=st_1        -> ntp_prod_0001.rst
round-trip equality: True
```

Nothing constrains a producer to one consumer: `resolve_input_coords` (`simulation.py:281`)
scans by `ref`, `schemas.py:57` declares `ref: Optional[str]` with no uniqueness rule, and
`relink_restarts` (`simulation.py:312`) deliberately leaves non-neighbour refs alone.

**The analysis layer linearises it, and is already wrong.** The same fan-out through
`validate_simulation`:

```
totals: {'steps': 20000000.0, 'time_ps': 80000.0, 'stage_count': 4}
ntp_prod_0003  ['Stage appears to overlap previous stage by 20000 ps.', ...]
ntp_prod_0004  ['Stage appears to overlap previous stage by 40000 ps.', ...]
ok: True
```

`totals()` (`protocol.py:448`) sums `nstlim*dt` over every stage unconditionally.
`_check_continuity` (`protocol.py:353`) zips document-order neighbours, so it compares each
branch to its *sibling* and reports an overlap that never happened — and still returns
`ok: True`.

So the model is ready and the analysis is not. This work is mostly about the analysis.

## 3. Decisions

1. **Declaration, not inference.** The user says which runs form which member. The program
   may auto-apply a grouping *guess* and report it, but never asserts membership it was not
   told, and never asserts statistical independence.
2. **`Step.lineage: Optional[str]`** — a tag on each step. Steps sharing a tag are one
   member (itself possibly a chain of chunks). No set container, no new top-level key.
3. **One manifest = one experiment.** All lineages in a `Simulation` are members of that one
   set. apo/holo is two manifests. `lineage: "wt/rep1"` remains a valid string if a
   hierarchy is ever wanted, so this does not preclude the deferred multi-topology case.
4. **Number plus inseparable structure.** `time_ps` keeps its current meaning (sum of
   `nstlim*dt` over all steps). Add `lineage_count`, and a per-lineage breakdown in the same
   document. No emitted field, value or message uses `ensemble_size`, `independent`, or `N` —
   the output states graph facts (`3 steps read the restart written by st_7 and carry 3
   distinct resolved seeds`) and never a statistical property. (Existing prose in
   `docs/architecture.md` and `docs/tutorials.md` uses the English word "independent"
   descriptively; this rule governs emitted output and new field names, not prior docs.)
5. **Fatal only for category errors.** Different `natom`, or minimization mixed with
   dynamics, is an error and exits 1. Every other difference — `temp0`, `cut`, `ntt`, `ntp`,
   `dt`, a shared resolved seed — is a finding, escalated by the existing `--strict`.
6. **Canvas: collapsible lineage bands** inside each phase.
7. **`discover` auto-tags lineages** from directory layout, reported as `[applied]`, and
   chaining stops at lineage boundaries.
8. **New header-only mdout read** used by `discover`: resolved `ig`, `File Assignments`
   chain evidence, POINTERS block.
9. **No prmtop content hash.** POINTERS comparison only.
10. **Prerequisites land first, in their own PR.**

### 3.1 Amendment to decision 4, forced by the type system

`per_lineage` cannot live inside `totals`. `PlanResult.totals` and `ValidationReport.totals`
are both `Dict[str, float]` (`schemas.py:240`, `:274`); a nested dict raises in pydantic.
`/api/plan` builds its response *after* `_attempt()` has written the files
(`core_bridge.py:422-431`), so the GUI would return HTTP 500 on a fully successful run and
name none of the files that landed.

Final shape — same document, breakdown beside the count rather than inside a float map:

```json
{
  "totals":  {"steps": 75000000.0, "time_ps": 300000.0, "lineage_count": 3},
  "lineages": {
    "rep1": {"steps": 25000000.0, "time_ps": 100000.0, "step_count": 5},
    "rep2": {"steps": 25000000.0, "time_ps": 100000.0, "step_count": 5},
    "rep3": {"steps": 25000000.0, "time_ps": 100000.0, "step_count": 5}
  },
  "stages": [...]
}
```

`lineages` is absent entirely when the document is single-lineage. `PlanResult` and
`ValidationReport` each gain a typed `lineages: Optional[Dict[str, LineageTotals]]`.

## 4. Rejected alternatives

| Rejected | Why |
|---|---|
| **Infer membership from files** | No file-level bit separates case 1 (seed replicas) from case 4 (pose variants): identical POINTERS, identical topology, and under `ig=-1` identical mdins. The only discriminator is directory naming — the same evidence class that produced the false-chain bug. |
| **A first-class set object** (`replicate_sets:` with member lists) | Member lists dangle when steps are renamed or deleted; needs a new top-level key and a migration story; buys nothing over a tag given one-manifest-one-experiment. |
| **A phase-level `kind: sequence\|ensemble`** | Does not nest. Case 1 crossed with case 3 — a replica that is itself a chain of five chunks — has nowhere to live. |
| **Derived-only ("set is a view over the DAG")** | Covers cases 2 and 3 free, and cannot express 1 or 4: their members share no ancestor. Case 4 members are N disconnected roots. |
| **Emitting `ensemble_size` and a cumulative "sampling time"** | Independence is a property of the sampled distribution, not the file graph. Children reading one parent restart inherit identical velocities; divergence flows only through thermostat noise, and that correlation channel is invisible to any file inspection. `to_methods_dict` (`protocol.py:466-828`) has no `notes`, no `continuity`, no caveat field, so a qualifier provably cannot reach the artifact `docs/cli.md` calls publication-ready. |
| **A prmtop content fingerprint** | The mdout's PARM path is clipped at 87 chars so the filename is unrecoverable; version stamps disagreed by 2m06s for the same system; and POINTERS equality is necessary but not sufficient (ff14SB vs ff19SB of one system have identical POINTERS). Members reference the topology *pool by id*, so equality is already trivial. |
| **Suggest-and-accept for lineages** | `SuggestionsTray.tsx` has Accept/Adjust/Ignore buttons that all call the same `onDismiss`, adding an id to a local `Set`. No apply mechanism exists anywhere. This is the *most* expensive option, not the cheapest. |

## 5. Schema

```python
@dataclass
class Step:
    ...
    rst: Optional[str] = None
    lineage: Optional[str] = None      # NEW
```

- `_step_payload` emits `lineage` **only when set**, matching `rst` and `gaps`.
- `payload_to_simulation` reads it back.
- Untagged = the implicit single member.
- **Switch.** Define `members(sim)` as the distinct non-null tags, plus one sentinel member
  if any step is untagged. `is_multi_lineage(sim)` is `len(members(sim)) >= 2`.

  Stated this way so the partially-tagged case is unambiguous: one tag plus untagged steps is
  **two** members and is multi-lineage. (An earlier phrasing — ">= 2 distinct non-null tags" —
  contradicted the sentinel rule and would have made a half-tagged document silently
  single-lineage, which is the worst of both behaviours: the user has declared structure and
  the tool ignores it.) A fully untagged document has exactly one member and every path below
  is a no-op.

Mirrored on `StepModel`, `StepCreate`, `StepUpdate` (presence semantics via
`model_fields_set`), and on TypeScript `StepModel` as **required** `lineage: string | null` —
the response is not serialised with `exclude_none`, so the key is always present.

### 5.1 New core module

`ambermeta/lineages.py` — deliberately **not** under `gui/api/`. Today `discover_draft`
lives in `gui/api/core_bridge.py`, which is why `ambermeta discover` fails without FastAPI
installed.

```python
def lineages(sim) -> "OrderedDict[str, List[Step]]"
def is_multi_lineage(sim) -> bool
def varying_axis(members, params) -> Dict[str, List[Any]]
def coherence(sim, params) -> List[Finding]     # severity: error | warning | info
```

## 6. Inference algorithm, and where it fails

`discover` tags lineages from directory layout, reported as `[applied]`.

**Rule.** Among run groups (a group with an mdin or mdout), find the path segment that
differs. Tag by that segment — **but only for groups that pass a membership predicate**:
candidate lineages must have matching run-name sets. `rep1/prod_0001` and `rep2/prod_0001`
match; `common/equil` matches nothing and stays untagged.

Without the predicate, the common layout `common/{min,heat,equil}` + `rep1..rep3/prod_*`
yields four tags, `lineage_count: 4` for a three-member campaign, and a `lineages` entry for
`common` whose `time_ps` is the prep runs — reported as `[applied]` rather than as a
question, falsifying decision 4's contract by feeding it wrong structure.

**Phase grouping must change with it.** `_ordered_stems` (`protocol.py:1048`) natural-sorts
the *path-prefixed* stem, so a rep1/rep2/rep3 tree is replica-major, and
`discover_draft`'s contiguous-role check (`core_bridge.py:510`) opens a new phase per role
*per replica*: 3 replicas x {min, heat, prod} = **9 phases**, three named "Minimization",
each holding one lineage. Section 8.3's bands would have nothing to render. When lineages are
tagged, same-role steps from all lineages join one phase. Gated on multi-lineage so
single-lineage discover output is unchanged.

**Known failure modes, recorded rather than solved:**

| Layout | Result |
|---|---|
| `rep1/`, `rep2/` directories | works |
| `rep1_prod_0001.mdout` flat, replica-prefix | works (replica-major sort) |
| `01_min_rep1`, flat replica-*suffix* | already step-major; phases correct, tags still derivable |
| Nested sweeps (`300K/rep1/`, `310K/rep1/`) | ambiguous — which segment is the member? Leave untagged. |
| Single lineage in a subdirectory | no differing segment; untagged; correct |
| Files at tree root mixed with subdirectories | root files fail the predicate; untagged |

Ambiguity resolves to **untagged**, never to a guess.

### 6.1 Chain evidence

`File Assignments` states `INPCRD` and `RESTRT` per run — the chain asserted by AMBER
itself. Prefer it over filename adjacency, with two cautions:

- `INPCRD` is an absolute path from another machine; `RESTRT` is a bare basename. Normalise
  to basename.
- **Basename matching is ambiguous by construction for replicas**: `rep1/prod_0001.rst` and
  `rep2/prod_0001.rst` share a basename. Match on the relative path where available, and
  when N candidates tie, record no edge rather than picking one.

`auto_detect_restart_chain` (`protocol.py:1174-1294`) is a **second, independent** chaining
implementation reached by `plan --auto-detect-restarts`. It scores `stages[i-1]` by name and
time and will happily assign rep1's terminal restart as rep2's input (verified: score 25 vs
a 5.0 threshold). It must get the same lineage guard, or refuse on multi-lineage documents.
Its `re.search(r'(\d{2,})')` also takes the first 2+ digit run, so `rep10_prod_0002` scores
against `10`, not `0002` — an independent bug worth fixing while there.

## 7. The linearity assumptions being removed

### 7.1 Plumbing: four sites, not one

A `lineage` key set only in `_flatten_simulation` never reaches `SimulationStage`.
`document_to_payload` (`core_bridge.py:64-86`) rebuilds each entry from a closed whitelist —
`name`, `stage_role`, `STAGE_FILE_KINDS`, `gaps`, `notes` — which is why `step_id` is already
dropped there. `_manifest_to_stages` then constructs `SimulationStage(name, stage_role)`
(`protocol.py:972`) and reads no other key. Implemented as one edit, the entire feature is a
**silent no-op** and `validate_manifest` raises nothing because it does not reject unknown
keys.

Required edits: `SimulationStage` (`protocol.py:124`), `_manifest_to_stages`
(`protocol.py:972`, plus the discover construction sites at `:1482` and `:1887`),
`document_to_payload` (`core_bridge.py:64`), `_flatten_simulation` (`core_bridge.py:317`).

`document_to_payload`'s output is an in-memory argument to `auto_discover` and is never
serialised, so this does not reintroduce anything into an on-disk format.

**Required test:** assert `[s.lineage for s in build_protocol(...).stages]` is populated
from a tagged v2 manifest. Without it the no-op is undetectable — a byte-identity regression
on a tagged fixture passes either way.

### 7.2 `totals()` — per section 3.1.

### 7.3 `_check_continuity()` — partition by lineage, then zip within each partition. A
lineage boundary yields no gap finding; the branch point is not an overlap.

### 7.4 `detect_sequence_gaps` / `detect_numeric_sequences` — currently key on
`Path(name).stem`, discarding the directory, and `build_suggestions` (`core_bridge.py:276`)
feeds them a flat concatenation across every phase and member. Verified consequences:

- rep1 x3, rep2 x1, rep3 x3 (a crashed replica) -> `{}`. **No missing-run finding at all**
  for the failure mode replicas exist to expose.
- rep1 `prod_0001..0002`, rep2 `prod_0011..0012` (offset numbering) -> `{'prod': [3..10]}`.
  **Eight spurious `needs_you` cards.**

Key both on `(lineage, base)`. Add `lineage` to the `Suggestion` schema so the card can say
which member is short. Independently: `Path().stem` eats a dot-numbered index, so
`prod.0001/prod.0002/prod.0004` returns `{}` entirely.

### 7.5 Chain-maintenance invariant

**No automatic operation may create an `input_coords.ref` crossing a non-null tag boundary.**

Three operations violate this today, all verified by execution:

- **`relink_restarts` (`simulation.py:342`).** Reorder three members so rep2 leads, and
  rep1's head is re-pointed at rep2's tail. The `elif ic.source == "starting_structure" and
  was is None` branch fires on the document-first step. Only that one step is exposed —
  mid-document heads are protected by the `was is None` guard — and the branch exists so
  drag-to-front is not lossy (`tests/test_simulation.py:135`). Fix: refuse to emit a `ref`
  when `prev.lineage != step.lineage` and both are non-null; revert to `starting_structure`.
- **`repair_dangling_refs` (`simulation.py:359`).** Delete a shared parent E referenced by
  three members and the result is a single 6-step serial chain: `A1 -> A2 -> B1 -> B2 -> C1
  -> C2`. This is the exact false edge the feature exists to remove, manufactured by the
  tool, in a topology this doc names. Fix: re-chain only to the nearest preceding step with
  the *same* tag, else `starting_structure`. When the deleted step was referenced by >= 2
  distinct tags, emit a warning finding rather than re-linking silently.
- **`add_step` (`document.py:315`, `:332`).** Appends to the end of the phase — there is no
  index on the store method or the route — and, when no explicit `input_coords` are supplied
  and `auto_link_restarts` is on (its default; the GUI add button sends only a name), chains
  to `_step_before(sid)`, the tail of the last band. Fix: accept `lineage` and `index`;
  insert after that lineage's last step and chain to it. When no lineage is given and the
  phase is multi-lineage, do not auto-chain at all — silence is recoverable, a false edge is
  not.

## 8. Surface parity

### 8.1 Core
As sections 5-7. All grouping, divergence and coherence logic in `ambermeta/lineages.py`
and `ambermeta/protocol.py`. CLI and GUI compute none of it.

### 8.2 CLI — no new flags
`discover` prints lineages and the `[applied]` note; `validate --manifest` prints the
coherence table and varying axis, exiting 1 on a category error or on any finding under the
existing `--strict`; `plan` emits the new keys.

Consequence: zero edits to the three hand-written completion scripts, and no
`docs/cli.md` regeneration — which matters because the generator hard-refuses anything but
Python 3.11 (`scripts/export_cli_help.py:25`) and the dev machine runs 3.13.

The originally requested `--explain-grouping` is answered by the `[applied]` suggestion plus
the tag written into the manifest: the inference is visible as data, not as a debug mode.

### 8.3 GUI

**Bands are the outer level; `groupSteps` stays as the inner one.** Deleting
`numericBase`/`stepNumber`/`groupSteps` would remove two working features from *untagged*
documents: the `COLLAPSE_THRESHOLD` behaviour that keeps a 100-chunk phase from rendering
100 cards (`PhaseSection.tsx:15`, `:300`), and `MissingRunGhost` placement, which
`ghostsForBase` (`:56`) keys on `group.base` from `missing_run` suggestions derived from step
*names*, not tags. Grouping becomes `(lineage, numericBase)` — a no-op when nothing is
tagged.

**Coherence needs a real error channel.** A `Finding` is not stage-attached, so it would land
in `protocol_issues: List[str]` (`core_bridge.py:181-199`), which `ValidationPanel` renders
uniformly as `text-warning` (`:49`). `errorCount` comes only from
`stage_issues.filter(s => !s.ok)`, and `report.ok` is never read. A category error would show
a yellow badge reading **"Valid, with 1 protocol note(s)"** while the CLI exits 1. Three
changes: an error-severity channel in the payload, `ok` computed from it, and the badge
logic. (The same defect already ships for intra-stage atom-count mismatches.)

**Bulk tagging is required, not optional.** 20 replicas x 10 chunks is 200 steps; each
per-step PUT calls `_snapshot()` (a deep copy) and `history_limit` is 100, so the hundredth
edit evicts the Discover result being annotated. The pattern to copy already exists and is
tested: the phase header's topology select writes every step in one PUT and one undo unit
(`PhaseSection.tsx:232-263`, asserted at `PhaseSection.test.tsx:212-223`). Per-step
`CommitField` remains for corrections.

**Arrows.** Within a band, unchanged. Between bands, none. A fan-out indicator above the
bands marks the shared branch point.

## 9. Removing the v1 file format

There is a `v1.0.0` tag and `version = "1.1.0"`, but no package index — every install
instruction is `pip install -e .` from a clone, and the maintainer confirms no v1 manifests
exist that anyone wants to open. The v1 *file format* is therefore removed, in PR 1.

**Removed:** `migrate_v1_manifest`, `_adopt_legacy_restart_paths`, `normalize_stage_keys`,
CSV/TOML manifest *parsing*, `export --to legacy`, `_sim_to_legacy_payload`, the non-`--v2`
`init` templates, and the `_is_v2` shape heuristic with its bare `except Exception`
(`cli.py:1581-1584`).

**Kept:** the flat engine in `protocol.py` in full — `SimulationProtocol`,
`SimulationStage`, `auto_discover`, continuity, `to_dict`, `to_methods_dict`,
`write_stats_csv`. This is the analysis layer, not back-compat; every number in the summaries
comes from it, and the v2 model has no analysis capability of its own. Also kept: CSV/TOML as
**export-only views** (`export --format csv` is a useful flat spreadsheet, a feature rather
than compatibility).

This removal deletes a hazard rather than only code. `migrate_v1_manifest` chains every stage
to its predecessor unconditionally (`simulation.py:246`) and writes the consumer's `inpcrd`
onto the predecessor's `rst` (`:250-251`) — so a flat replica manifest migrates into one
fabricated edge *and* one falsified restart attribution per replica boundary. Since
`docs/tutorials.md:363` tells replica users to pass `--allow-gaps` rather than annotate, that
population was precisely the one at risk.

`--allow-gaps` itself stays and keeps working; a declared lineage boundary is simply not a
gap, so it is no longer needed for replicas. Using both is not an error.

## 10. Tests

- **Back-compat:** an untagged manifest's v2 payload, `summary.json`,
  `methods_summary.json` and stats CSV are byte-identical before and after. This is the
  guarantee decision 2 buys and nothing currently pins it.
- **Anti-no-op:** a tagged v2 manifest round-trips to populated `protocol.stages[i].lineage`
  (section 7.1).
- **Chain invariant:** the reorder permutation of 7.5, the shared-parent deletion of 7.5, and
  `add_step` into a multi-lineage phase — each asserting no cross-tag `ref` is created.
- **Sequence gaps:** a fixture with *deliberately unequal* chunk counts (rep2 short by one)
  must produce exactly one `missing_run` scoped to rep2; an offset-numbering fixture must
  produce none.
- **Coverage** for each of the four in-scope topologies.
- **GUI, which the first draft priced at zero:** `lineage` is required in TS, so it goes into
  `test/factories.ts` first and then into **eight hand-written step literals** across
  `App.dnd`, `App.workflows`, `Canvas`, `Canvas.continuity`, `Canvas.dropTargets`,
  `PhaseSection`, `StepNode`, `NodeInspector` tests. `tsc` is a CI gate today, so these are
  compile-time failures. The ghost and grouping tests get rewritten, not deleted.

## 11. Unverified AMBER assumptions

Everything below is asserted by the design and **not** established by the repo's data, which
is a single 5-link NPT chain from Amber 22 pmemd.cuda with `ntt=3`.

1. **Where `ig` is echoed for other configurations.** Verified: with `ig=-1`, pmemd.cuda
   echoes the resolved seed twice — free text at line 59, and `ig = 70038` at line 190 under
   `Langevin dynamics temperature regulation:`. Unverified: sander, `ntt != 3`, minimization
   runs. The line-190 echo sits under a thermostat-specific header, so a Berendsen or NVE run
   may place or omit it.
2. **Whether the 87-character clip on `File Assignments` lines is a fixed field width.** All
   five fixtures show 87 for MDIN/INPCRD/PARM, but every path is the same length, so short
   paths may or may not be padded. If it is *not* fixed, the PARM filename may be recoverable
   for shorter paths — which would revive a cheaper topology check.
3. **That the `3. ATOMIC COORDINATES` banner is a reliable stop condition.** Verified in all
   five fixtures (CONTROL DATA runs 161-231). The header contains a verbatim echo of the
   user's mdin, so its length varies with the input file; a fixed line count would be
   arbitrary. Unverified across AMBER versions.
4. **That `begin time read from input coords` (line 237) is always present.** It is in all
   five fixtures and is the authoritative start time — mdin `t` is a lie under `irest=1`
   (mdin says 1000.0, the run began at 920.000 ps). Unverified for minimization or `irest=0`.
5. **That POINTERS equality implies the same system.** It is necessary, not sufficient: the
   same system under ff14SB and ff19SB has identical POINTERS. Used only as a category-error
   *refutation* (different POINTERS => not the same system), never as confirmation.
6. **Nothing about REMD/GaMD/TI/groupfile output.** No such file exists in the repo.

## 12. Sequencing

**PR 1 — prerequisites, small, landed and merged alone.**
1. Remove the v1 file format (section 9). This deletes the v1/v2 dispatch at
   `cli.py:1578-1586`, so `_plan_v2` stops being a separate early-return branch and there is
   one plan path to fix rather than two to keep in step.
2. `plan -m <manifest> --summary-path/--methods-summary-path/--stats-csv` writes its
   artifacts. Today `_plan_v2` (`cli.py:1525-1538`) prints and returns 0, writing nothing —
   verified by execution. This feature outputs through that path, so it must work first.
   Ordered after (1) because (1) removes the branch that causes it.
3. CI runs pytest and vitest. Neither has ever run in CI; both were green locally as of
   2026-07-31.

**PR 2 — the feature**, in reviewable commits: model field and payload round-trip; the chain
invariant; plumbing to `SimulationStage`; totals and `lineages`; continuity partition;
sequence-gap keying; header-only mdout read; discover tagging and phase grouping; coherence
findings; canvas bands and bulk tagging.

> **AMENDED after PR 1 landed — see section 13.** PR 2 is split into **2a (correctness)** and
> **2b (breakdown and editing surface)**. Every line number quoted anywhere above this point
> predates PR 1 and is wrong; section 13.2 maps the ones that matter.

---

## 13. Amendments after verification (2026-08-03)

PR 1 merged as `bfbe681` (#74), deleting ~719 lines across 17 files. Every factual claim in
sections 1-12 was then re-verified against the resulting tree, by execution rather than by
reading. 66 claims had drifted; 11 were substantively wrong. This section records what changed.
**Where section 13 and sections 1-12 disagree, section 13 wins.**

### 13.1 New rulings

1. **The untagged sentinel is excluded from `lineage_count` and from the `lineages` map.** It
   still forms its own continuity partition, and it still counts toward `is_multi_lineage`.
   Section 5's literal rule would have reported `lineage_count: 4` for the canonical
   `common/{min,heat,equil}` + `rep1..3/prod_*` campaign — the exact miscount section 6's
   membership predicate exists to prevent, reintroduced through the back door.
2. **A lineage head is checked against its real producer**, not left unchecked. Naive
   partitioning silently drops a check that is correct today (verified: a genuine `equil -> rep1`
   continuation goes from `observed_gap_ps=0.0` to `None`), and a document of single-step
   lineages produces *zero* continuity output, which reads as "checked and fine" rather than
   "not checked". This requires a producer link on `SimulationStage` that section 7.1 does not
   specify — see 13.3.
3. **`to_methods_dict`'s `stage_sequence` gains a per-entry `lineage` key.** Purely additive, so
   an untagged document's `methods_summary.json` stays byte-identical.
4. **PR 2 splits.** See 13.4.

### 13.2 Substantively wrong claims in sections 1-12

| Section | Claim | Reality |
|---|---|---|
| 7.5 | Three operations create false cross-tag edges | **Six** mutation call sites, and the primary producer is not among them — see 13.3 |
| 7.5 | `relink_restarts`' fix belongs on the `elif` branch | On an interleaved reorder the `elif` produces **zero** cross-tag edges and the *first* branch produces **two**. Both need the guard |
| 7.5 | `auto_link_restarts` is the opt-out | `repair_dangling_refs` is called directly by `delete_phase` and `delete_step`, bypassing the gated `_relink` wrapper. Turning auto-linking off does not protect the user |
| 7.3 | Partitioning is a pure improvement | It removes a correct check from every lineage head — hence ruling 2 |
| 7.3 | Implementable inside `_check_continuity` alone | `SimulationStage` carries no tag; 7.1's plumbing is a hard prerequisite |
| 7.4 | Offset numbering yields "eight spurious `needs_you` cards" | **One** card naming eight indices, plus up to eight spurious canvas ghosts. And the ghosts are already dead for any multi-directory tree, because the server's `base` is `prod` while the client's `numericBase` is `rep1/prod` |
| 7.1 | `_manifest_to_stages` "reads no other key" | It reads `files`, the five file kinds, `gaps`/`gap` and `notes` *after* construction. A tag can be plumbed post-construction in that same style |
| 7.1 | Two "discover construction sites" | Neither is reached by `ambermeta discover`, which goes through `discover_draft`. One is `ProtocolBuilder.add_stage`, which has zero in-repo callers |
| 3.1 | `lineages` is "absent entirely" when single-lineage | Unachievable in the API responses: no route sets `exclude_none`, so an `Optional` field serialises as `"lineages": null`. Only `to_dict()`/`summary.json` can literally omit it. Section 5 chose the opposite convention for `StepModel.lineage`, so the doc contradicted itself |
| 8 | POINTERS is read from the mdout | There is no POINTERS block in any mdout — it is a prmtop `%FLAG`. The mdout analogue is `1. RESOURCE USE:`, and `natoms`/`nres` are **already parsed** |
| 5.1 | `discover` fails without FastAPI because `discover_draft` lives under `gui/api/` | PR 1 emptied `gui/api/__init__.py` precisely to fix this. The relocation is now optional tidying, not a bug fix |
| 9 | `_adopt_legacy_restart_paths` was removed | Deliberately **kept** — it is v2 schema-evolution compat, not v1 back-compat |
| 9 | CSV/TOML survive as export-only views | Dropped entirely by user ruling during PR 1. `write_stats_csv` is the only CSV left |

### 13.3 The omission that matters most

**`discover_draft` is the primary producer of false cross-lineage edges, and section 7.5 does
not list it.** `ambermeta/gui/api/core_bridge.py:451` emits `InputCoords(source="step",
ref=prev_step_id)` unconditionally, guarded only by whether this is the *globally* first step
(`:444`). `prev_step_id` is one flat variable over `_ordered_stems` order, so a `rep1/rep2/rep3`
tree yields a single serial chain with `rep1/prod_0002 -> rep2/prod_0001` and
`rep2/prod_0002 -> rep3/prod_0001` baked in. It is reached by both `ambermeta discover` and
`POST /discover`, so every replica document arrives at the CLI and the GUI already wrong.
This is the mechanism behind the failure section 1 opens with; fixing only 7.5's three named
operations leaves it in place.

Two further unlisted hazards, both verified:

- **`update_step` accepts any `ref` with no validation** (`document.py:355-358`, exposed as
  `PUT /steps/{id}`): a nonexistent id and a self-referencing id are both accepted verbatim.
  Any guard added to the automatic paths is bypassable here.
- **A false `ref` is now a false *file*, not merely a false edge.** Because `Step.rst` landed in
  PR 1, `resolve_input_coords` returns the producer's `rst`, so a cross-lineage ref makes the
  manifest, the GUI's `resolved_input_coords`, and the methods summary all name a file from the
  wrong replica.

### 13.4 Revised sequencing

**PR 2a — correctness. Nothing new is claimed; false claims stop.**
Model field and payload round-trip; plumbing to `SimulationStage` (tag **and** producer link);
`discover_draft` per-lineage chaining and phase grouping; guards on all six mutation sites plus
`update_step` validation; continuity partition with the producer-checked head; sequence-gap
keying on `(lineage, base)`; `stage_sequence` tagging; read-only `lineage` on the API and TS
models. Every item is a defect with a failing test available before the fix.

**PR 2b — the breakdown and the editing surface.**
`totals` + `lineages` and `LineageTotals`; coherence findings and the GUI error channel;
header-only mdout read (resolved `ig`, File Assignments, authoritative begin-time); canvas
lineage bands; bulk tagging; CLI printing of the per-lineage breakdown.

`auto_detect_restart_chain` (`plan --auto-detect-restarts`) needs the same guard or a
multi-lineage refusal; it is scheduled in 2a because it is the second independent chainer and
shares the defect.
