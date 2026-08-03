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
| JSON | any other extension except `.toml`/`.csv` | stdlib — always available |

The two are interchangeable in both directions: `load_simulation` parses either to the same plain
dict *before* it inspects the shape, and `write_simulation` takes `fmt` ∈ `{"json", "yaml"}` (anything
else raises `ValueError: v2 write supports json/yaml only, got: <fmt>`). Only the extension decides how a
file is *read* — a `.yaml`/`.yml` path goes through PyYAML, `.toml`/`.csv` are refused outright (below),
and every other extension is parsed as JSON.

TOML and CSV are **not** manifest formats. Pointing any reader at a `.toml` or `.csv` path fails
immediately — that check sits *between* the YAML branch and the JSON fallback, so those two extensions
never reach the JSON parser:

```
<path>: AmberMeta reads and writes manifests as YAML or JSON only; TOML and CSV are not manifest formats.
```

The message is always prefixed with the offending path. Note this guard is on the **read** side only: the
writers pick their format from the extension the same blunt way, so `export -o out.toml` writes JSON into a
file named `.toml` and exits `0`. Pass `--format` if the extension can't be trusted to say what you meant.

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
| `lineage` | no | Which run lineage — replica, branch, pose — this Step belongs to. Steps sharing a tag are one member; a Step with no tag belongs to the implicit single member. Any string; `""` reads as unset, and a number is read as its string form (`lineage: 1` → `"1"`). Omitted entirely when unset, so an untagged Step round-trips as no key. `ambermeta discover` writes it when the directory layout names the members; otherwise it is yours to declare. |
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

### The chain invariant

**No automatic operation will create an `input_coords.ref` that crosses a lineage boundary.** A restart
written by replica 2 was never read by replica 1; a tool that says otherwise has invented the one fact this
model exists to record. The rule holds across every path that maintains the chain on your behalf —
`discover`'s draft, reordering steps or phases, moving a step between phases, adding a step, and the
re-chaining that follows a delete.

A boundary needs **two different declared tags**. An untagged Step is the implicit single member and
continues into, or out of, anything — one shared equilibration feeding N replicas is the commonest layout
there is, and it is a real edge, so `common/equil` → `rep1/prod_0001` is never refused on tag grounds.

What that leaves you, deliberately: **a cross-member `ref` you set by hand is allowed.** It is the only way
to express a genuine branch, so it is honoured and *reported* rather than rejected — the GUI and the HTTP
API surface it as a warning on the edit that made it ([gui.md §11](gui.md#data-model-documentresponse)),
and nothing afterwards will maintain or recreate it. Editing the YAML directly is subject to no check at
all; the invariant constrains what AmberMeta writes, not what you may write.

Where an automatic path *would* have crossed a boundary it falls back to the nearest earlier Step of the
consumer's own member, or to `starting_structure` when that member has none. Deleting a Step that several
members continued from cannot be repaired by re-chaining — the fan-out it was is gone — so each consumer
falls back that way and the operation reports what it cost.

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
structure, group runs into role-named phases, and chain each step's `input_coords` off the previous step of
its own lineage — surfacing each inference as an explainable suggestion rather than silently guessing. When
the layout names members (`rep1/`, `rep2/`, … running the same set of runs) each one is tagged, chained
separately from the head of the starting structure, and reported as an `[applied]` `lineage_group`
suggestion; an ambiguous layout is left untagged rather than guessed at, and is chained and grouped exactly
as it was before lineages existed. It is the only thing
that scans a directory into a *v2 draft* — `plan --recursive` also scans from scratch, but through the flat
analysis engine (§10), and prints a Protocol summary rather than producing a manifest. The member inference
is shared, not exclusive to the draft: `plan --recursive` applies the same rule to the runs it finds, so its
continuity checks stay inside each member too. Its restart auto-detection does as well, with one gap worth
knowing: a leftover restart with no `mdin`/`mdout` beside it is not a run, so it is untagged, and an untagged
producer is not refused to anybody — that one file stays open to every member.

`init` is simpler: it always writes the same fixed, commented v2 YAML template — a starting point you fill
in by hand rather than a draft of what's on disk. It does not scan anything; its positional `directory`
argument (default `.`) only says where the file lands, and `-o/--output` and `--force` are its only flags.
See the [GUI guide](gui.md) and [CLI reference](cli.md).

### 9.1 How `discover` infers members

A lineage is normally **declared** — you write `lineage:` on the steps (§5). `discover` is the one thing
that will propose one for you, and it does so only from **directory layout**, never from file contents.

**The rule.** Group the runs by their directory. A directory is a candidate member only if it sits beside
at least one other directory running *the same set of run bases* — where the base of `prod_0001` is `prod`
(the same stripping `detect_sequence_gaps` uses). Exactly one such cohort must exist, its directories must
all be at the same depth, and exactly one path segment must vary across them. That segment becomes the tag.

Bases, not whole run names, is deliberate: **a replica that died early is the single most important thing
this feature has to catch.** `rep1/prod_0001..0003` beside `rep2/prod_0001` is one crashed member, not two
unrelated directories, and keying the predicate on exact run-name sets would refuse to tag it — silently
disabling the very sequence-hole finding that would have reported the crash.

Everything the rule refuses, refuses to **untagged**, never to a guess. An inference reported as `[applied]`
is a claim, and a wrong claim here is exactly what lineages exist to stop:

| Layout | Result |
|---|---|
| `rep1/prod_000{1,2}`, `rep2/prod_000{1,2}` | tagged `rep1`, `rep2` |
| `rep1/{min,heat,prod}`, `rep2/{min,heat,prod}` … | tagged; a member may run any number of roles |
| `rep1/prod_0001..0003` beside `rep2/prod_0001` (a crashed replica) | tagged — the bases match even though the run sets do not |
| `rep1/prod_000{1,2}` beside `rep2/prod_001{1,2}` (offset numbering) | tagged; each member is numbered on its own scale |
| `common/{min,heat,equil}` beside `rep1..3/prod_*` | `rep1..3` tagged; `common` runs different bases, fails the predicate, stays **untagged** |
| Run files at the tree root beside `rep1/`, `rep2/` | the root runs carry no segment and stay untagged; **the subdirectories are still tagged** |
| One lineage in one subdirectory (`rep1/` alone) | nothing to differ from — untagged |
| `300K/rep1/`, `300K/rep2/`, `310K/rep1/`, `310K/rep2/` (a nested sweep) | two segments vary at once; neither can be shown to name the member — untagged |
| `a1/prod`, `a2/prod` beside `b1/heat`, `b2/heat` (two rival cohorts) | two experiments in one manifest, which this model does not represent — untagged |
| `rep1/prod_0001` beside `x/rep2/prod_0001` (mismatched depth) | untagged |
| `rep1_prod_0001`, `rep2_prod_0001` — flat, replica in the **filename** | **untagged.** Only directory segments are read |
| `01_min_rep1`, `01_min_rep2` — flat, replica as a filename *suffix* | **untagged**, same reason |

The last two rows are the ones people expect to work. Splitting a stem into tokens has no non-arbitrary
rule, and the obvious one tags a plain chunked chain `prod_0001`/`prod_0002` as two members — breaking
every untagged document in the process of helping a few. Tag those layouts by hand instead.

### 9.2 A multi-lineage document is phase-major

This changes the shape of the file, so it is worth stating plainly. When `discover` tags members, same-role
steps from **every** member share one phase. Left contiguous, the replica-major scan order would open a
phase per role *per member* — nine phases for three replicas of three roles, three of them named
"Minimization" — which groups nothing.

The consequence: **a member's steps are not contiguous in document order.** For
`rep{1,2,3}/{min_0001,heat_0001,prod_0001}` the draft is three phases, and `rep1`'s runs sit at document
positions 0, 3, 6 rather than 0, 1, 2:

```
Phase: Heating        rep1/heat_0001  rep2/heat_0001  rep3/heat_0001
Phase: Minimization   rep1/min_0001   rep2/min_0001   rep3/min_0001
Phase: Production     rep1/prod_0001  rep2/prod_0001  rep3/prod_0001
```

(Heating precedes Minimization because phases open in the runs' natural stem order and `heat` sorts before
`min` — phase order follows the scan, not the canonical role sequence.)

Anything reading a manifest **must not treat document order as run order** once more than one member is
declared — group by `lineage` first. That is what `ambermeta.lineages.members()` is for
([api.md](api.md#ambermetalineages-which-steps-form-which-member)), and it is what the continuity engine
does before it compares anything ([architecture §3](architecture.md#3-continuity-and-sequence-hole-detection)).
Within a phase a member's own steps stay in order, and its chain still runs through them.

A single-lineage document is untouched by all of this: one member, contiguous phases, document order *is*
run order.

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
not a path. That shape is documented immediately below. Full signatures for all of the above are in
[api.md](api.md).

### The flat stage-dict shape (in-memory only)

The analysis engine behind `auto_discover`, `plan --recursive`, and `ProtocolBuilder` predates v2 and works
on a **flat list of stages**, not on a `Simulation`. There is no longer any file format for this — nothing
reads it from disk, and `load_simulation` will not parse it — but it is still the live in-memory contract
for `auto_discover(directory, manifest=[...])`, so it is specified here.

`manifest=` accepts a list of stage dicts, a mapping of `name → stage dict` (the key becomes `name`), or a
mapping with a `stages:` list under it. Entries that are not dicts raise
`TypeError: Manifest entries must be dictionaries`; anything that is neither list nor mapping raises
`TypeError: Manifest must be a list or dictionary`.

#### Stage keys

| Key | Required | Meaning |
|---|---|---|
| `name` | **yes** | Stage name. Missing or empty raises `ValueError: Each manifest entry must include a 'name'.` |
| `stage_role` | no | One of the [canonical role tokens](#7-canonical-role-tokens). When absent it is inferred — first from `grouping_rules`, then from the mdin's content. |
| `prmtop`, `mdin`, `mdout`, `mdcrd`, `inpcrd` | no | The five file slots (`ambermeta.manifest.STAGE_FILE_KINDS`). Relative paths resolve against `directory`. |
| `files` | no | A mapping holding the same five keys. Merged with the top-level ones; a top-level key **wins** on conflict. |
| `gaps` / `gap` | no | Expected inter-stage gap — see below. `gaps` is checked first. |
| `notes` | no | A string (appended as one note) or a list (each item appended). |

Unrecognized keys are ignored rather than rejected, so extra bookkeeping of your own rides along harmlessly.

#### Gap configuration

`gaps` and `gap` are interchangeable spellings, and the value takes any of four shapes — a mapping, a bare
number, a bare string, or a list:

```python
{"name": "prod2", "gaps": {"expected": 2.0, "tolerance": 0.5,     # ps
                           "notes": "restarted after a queue eviction"}}
{"name": "prod2", "gaps": {"expected_ps": 2.0, "tolerance_ps": 0.5}}  # aliases
{"name": "prod2", "gaps": 2.0}          # bare number → expected, no tolerance
{"name": "prod2", "gaps": "checkpoint restart, gap is intentional"}   # bare string → a note
{"name": "prod2", "gaps": ["note one", "note two"]}                  # list → several notes
```

Nested `notes` inside the mapping form take a string or a list, same as the top-level `notes` key.

#### Validation behavior

For each adjacent pair of stages the engine measures the gap between the previous stage's end time and this
stage's start time, then:

- **No expectation set** and the gap is within the default tolerance → normalised to exactly `0.0`, i.e.
  treated as floating-point noise rather than a finding. The default tolerance is `0.1` ps, or half the
  previous stage's frame interval if that is larger — an absolute floor, deliberately *not* scaled by
  elapsed time, so a real gap cannot hide inside a long run.
- **Within an explicit `expected ± tolerance` window** → an `INFO` note confirming the match. A healthy
  declared transition is never surfaced as a problem.
- **Shorter than, or beyond, that window** → a real (non-`INFO`) continuity note.
- **Non-zero with no expectation set** → `Gap detected without stated expectation; verify continuity.`,
  unless gaps were allowed, in which case it is `INFO`.
- **Overlap** (negative gap) beyond the default tolerance → `Stage appears to overlap previous stage by N ps.`
- **Beyond ±1e6 ps** (1 µs) → treated as a unit or parsing error: an `INFO` note, and the continuity check
  for that pair is skipped rather than reported as a discontinuity.

#### Role rules and injected restarts

`grouping_rules` maps a regex to a role and fills in `stage_role` where the entry didn't set one, emitting
`INFO: stage_role '<role>' inferred from stage_role_rules` (that note names the internal parameter, not the
one you pass). A pattern that fails to compile is **not** an error — it is escaped and matched as a literal
string. Only the mapping form works; a list of pairs is not accepted. The same rules apply on the
disk-discovery path, when `manifest` is `None`.

`restart_files` injects an `inpcrd` for stages that don't name one, keyed by stage **name or role** (name is
tried first):

```python
from ambermeta import auto_discover

protocol = auto_discover(
    "runs/",
    manifest=[
        {"name": "equil", "stage_role": "equilibration", "mdin": "equil.in", "mdout": "equil.out"},
        {"name": "prod1", "stage_role": "production",    "mdin": "prod1.in", "mdout": "prod1.out",
         "gaps": {"expected": 0.0, "tolerance": 0.1}},
    ],
    grouping_rules={r"^equil": "equilibration"},
    restart_files={"prod1": "runs/equil.rst7"},
)
```

`ProtocolBuilder` wraps the same engine with a fluent API (`.from_directory()`, `.with_grouping_rules()`,
`.with_stage_tolerance()`, `.auto_detect_restarts()`, `.build()`); see [api.md](api.md#protocolbuilder).

---

## 11. Errors

Reading a manifest raises one of these. The **Surfaces as** column is what the CLI actually prints — the
two forms differ, and only the first is a message AmberMeta wrote for you to read.

| Error | Cause | Surfaces as | Fix |
|---|---|---|---|
| `AmberMetaError`: `<path> is not a v2 manifest (no 'steps' key).` | The file is some other document — most often a manifest from before the v2 format | `ERROR:` | `ambermeta discover <dir> --write <path>` to rebuild it. |
| `AmberMetaError`: `<path> is a v2 manifest but is missing its 'steps' list.` | The document announces itself as v2 (`version: 2`, or a `simulation`/`phases` key) but has no steps | `ERROR:` | Restore the steps, or rebuild with `discover --write`. |
| `AmberMetaError`: `<path>: AmberMeta reads and writes manifests as YAML or JSON only; TOML and CSV are not manifest formats.` | A `.toml` or `.csv` path was handed to a reader | `ERROR:` | Convert the document to YAML or JSON (§1). |
| `AmberMetaError`: `Manifest references missing files:` | `plan --strict -m` and a path in the manifest doesn't exist | `ERROR:` | Fix the paths, or drop `--strict` to have the files skipped and recorded per-stage. |
| `FileNotFoundError`: `Manifest not found: <path>` | Manifest missing | `ERROR:` under `export`/`validate --manifest` (each pre-checks the path itself); `Unexpected error` under `plan -m` | Check the path. |
| `TypeError`: `Manifest must be a mapping or list of stage entries.` | The parsed file is a scalar — neither a mapping nor a list | `Unexpected error` | Use the shape in §2. |
| `TypeError`: `Manifest entries must be dictionaries` / `Manifest must be a list or dictionary` | An in-memory `manifest=` container of the wrong shape (§10) | `Unexpected error` | Pass stage dicts. |
| `ValueError`: `Each manifest entry must include a 'name'.` | An in-memory stage dict with no `name` (§10) | `Unexpected error` | Give every entry a `name`. |
| `json.JSONDecodeError` (a `ValueError`) | A malformed JSON manifest | `ERROR:` under `export`/`validate --manifest`; `Unexpected error` under `plan -m` | Fix the syntax at the reported line/column. |
| `yaml.YAMLError` (e.g. `ScannerError`) | A malformed YAML manifest | `Unexpected error` everywhere | Fix the syntax at the reported line/column. |
| `ImportError` | `pyyaml` not installed and the path ends in `.yaml`/`.yml` | `Unexpected error` | `pip install -e ".[yaml]"` |
| `ValueError`: `v2 write supports json/yaml only, got: <fmt>` | `write_simulation` called with another `fmt` | — (not reachable from the CLI: `--format` is restricted to `json`/`yaml` by the parser) | Ask for `json` or `yaml`. |
| `RuntimeError` | YAML output requested without `pyyaml` installed | `Unexpected error` | `pip install -e ".[yaml]"` |

Everything above exits `1`. The two surfaces are:

- **`ERROR: <message>`** — a deliberate, readable failure. `ambermeta export` and
  `ambermeta validate --manifest` additionally prefix load failures with `Failed to load manifest: `;
  `plan -m` prints the message unprefixed. (The `Manifest not found` row is the exception to its own
  prefix: `export` and `validate` catch it in their own pre-check, before the loader is reached, so it
  prints as a bare `ERROR: Manifest not found: <path>`.)
- **`Unexpected error (<Type>: <message>). Re-run with --log-level DEBUG for the full traceback.`** — the
  catch-all. These types are outside the handlers' `except` tuples, or are raised by `write_simulation`
  outside the guarded block. Reaching one is not a documented contract; treat it as a bug report worth
  filing rather than an error surface to script against.

Validation (`ambermeta validate`, `plan`, `validate_simulation`) produces **warnings/findings**, not hard
errors, for: missing files that block a check, atom-count mismatches, timing/box inconsistencies,
unexpected inter-step gaps, and sequence holes in a numbered run sequence. See
[architecture §3](architecture.md#3-continuity-and-sequence-hole-detection) and [cli.md](cli.md#validate).
