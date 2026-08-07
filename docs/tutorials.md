# Tutorials

Task-oriented walkthroughs for getting real work done with AmberMeta. Each uses the sample data in `tests/data/amber/md_test_files/` — a 64,528-atom glycoprotein system (`CH3L1_HUMAN_6NAG.top` + `.crd`) with a five-run NPT production sequence (`ntp_prod_0001` … `ntp_prod_0005`, plus a bare `ntp_prod_0000.rst` that is not itself a run) — so every command below is reproducible. Terminal output is too, with one exception: step and phase ids are `uuid4` slices minted fresh on every `discover`, so the ids inside manifests here will not match yours. Run them from a writable scratch copy so you don't touch the repo's test fixtures:

```bash
mkdir -p /tmp/ambermeta-tutorial
cp tests/data/amber/md_test_files/* /tmp/ambermeta-tutorial/
cd /tmp/ambermeta-tutorial
```

> **Note on IDs.** Phases and steps get a random 8-character id (`uuid4().hex[:8]`) whenever `discover` or the GUI creates them. Every id shown below is real output from one particular run — yours will differ. Everything else (names, paths, findings, validation verdicts) is deterministic.

> **Prerequisite.** `pip install -e ".[all]"` (the NetCDF extra parses `.nc`/`.ncrst` restarts some projects use; the bundled sample restarts are plain binary `.rst`, so the base install is enough for these tutorials).

## Contents

1. [Discover, edit, and export a v2 manifest](#1-discover-edit-and-export-a-v2-manifest)
2. [Validate continuity and catch a sequence hole](#2-validate-continuity-and-catch-a-sequence-hole)
3. [Round-trip a manifest through the GUI](#3-round-trip-a-manifest-through-the-gui)

---

## 1. Discover, edit, and export a v2 manifest

**Goal:** turn a directory of loose AMBER files into a hand-editable, canonical manifest.

### Discover

`discover` scans a directory into a draft `Simulation` — a topology pool, phases grouped by role, and steps with a resolved input-coordinate source for each — using the same engine the GUI's **Discover** button calls.

```bash
ambermeta discover .
```

```
Simulation summary
==================
Topologies (pool): 1
  - top_CH3L1_HUMAN_6NAG [normal]  CH3L1_HUMAN_6NAG.top
Starting structure: CH3L1_HUMAN_6NAG.crd
Phases: 1

Phase: Production [production]
  - ntp_prod_0001  topology=CH3L1_HUMAN_6NAG.top  input=starting structure  (mdin=ntp_prod_0001.mdin, mdout=ntp_prod_0001.mdout)
  - ntp_prod_0002  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0001 (ntp_prod_0001.rst)  (mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)
  - ntp_prod_0003  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0002 (ntp_prod_0002.rst)  (mdin=ntp_prod_0003.mdin, mdout=ntp_prod_0003.mdout)
  - ntp_prod_0004  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0003 (ntp_prod_0003.rst)  (mdin=ntp_prod_0004.mdin, mdout=ntp_prod_0004.mdout)
  - ntp_prod_0005  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0004 (ntp_prod_0004.rst)  (mdin=ntp_prod_0005.mdin, mdout=ntp_prod_0005.mdout)

Suggestions:
  - [applied] CH3L1_HUMAN_6NAG.crd set as the starting structure
  - [applied] Phase roles inferred from file content/names
```

`CH3L1_HUMAN_6NAG.top` was found once and put in the topology pool; `CH3L1_HUMAN_6NAG.crd` (a single-frame restart, no trajectory) was picked as the Simulation's starting structure and feeds `ntp_prod_0001`. Every later step's `input` is `restart of <step> (<file>)` — the previous step's own output restart, the continuity chain. Both suggestions are `[applied]` automatically; a `[needs_you]` suggestion (you'll see one in [§2](#2-validate-continuity-and-catch-a-sequence-hole)) is not.

Write the draft to a v2 manifest with `--write`:

```bash
ambermeta discover . --write draft.yaml
```

```
...
Wrote v2 draft manifest: draft.yaml (yaml)
```

### Edit

`draft.yaml` is plain YAML — edit it in any text editor. Rename the phase and add a note to the first step:

```yaml
# draft.yaml (excerpt, before editing)
phases:
- id: 34e5b79a
  name: Production
  role: production
  order: 0
steps:
- id: 8f9b2e3f
  name: ntp_prod_0001
  ...
  notes: []
```

```yaml
# draft.yaml (after editing)
phases:
- id: 34e5b79a
  name: NPT Production
  role: production
  order: 0
steps:
- id: 8f9b2e3f
  name: ntp_prod_0001
  ...
  notes: ["First production run; starts from the equilibrated starting structure."]
```

Check that the edit didn't break anything:

```bash
ambermeta validate --manifest draft.yaml
```

```
Simulation validation

Validation: OK
```

### Export

`export` reads a v2 manifest and re-emits it as canonical v2 — that's its only output. Re-exporting canonicalizes formatting and lets you switch YAML/JSON:

```bash
ambermeta export draft.yaml -o simulation.yaml
```

```
Wrote v2 manifest: simulation.yaml (yaml)
```

```yaml
# simulation.yaml
version: 2
simulation:
  topologies:
  - id: top_CH3L1_HUMAN_6NAG
    path: CH3L1_HUMAN_6NAG.top
    kind: normal
  starting_structure: CH3L1_HUMAN_6NAG.crd
phases:
- id: 34e5b79a
  name: NPT Production
  role: production
  order: 0
steps:
- id: 8f9b2e3f
  name: ntp_prod_0001
  phase: 34e5b79a
  order: 0
  topology: top_CH3L1_HUMAN_6NAG
  input_coords:
    source: starting_structure
  mdin: ntp_prod_0001.mdin
  mdout: ntp_prod_0001.mdout
  mdcrd: null
  notes:
  - First production run; starts from the equilibrated starting structure.
  rst: ntp_prod_0001.rst
# ... ntp_prod_0002 .. ntp_prod_0005 follow, each chained to the previous step
```

The format follows the `-o` extension — `.yaml`/`.yml` gives YAML, anything else JSON — and `--format json|yaml` overrides that. So the same file as JSON:

```bash
ambermeta export simulation.yaml -o simulation.json
```

```
Wrote v2 manifest: simulation.json (json)
```

With no `-o` at all, the canonical payload goes to stdout as JSON, which is handy for piping into `jq`.

YAML and JSON are the only manifest formats AmberMeta reads or writes. On the way *in*, a `.toml` or `.csv` manifest is rejected outright — `ERROR: Failed to load manifest: <path>: AmberMeta reads and writes manifests as YAML or JSON only; TOML and CSV are not manifest formats.` On the way *out* there is no such guard: because only `.yaml`/`.yml` select YAML, `-o out.toml` writes **JSON into a file named `.toml`** and exits `0`. Pick the extension deliberately, or pass `--format` and let the name follow.

`export` also only reads v2 — a pre-2.0 flat manifest (`stages:`, `global_prmtop`) is no longer a format it understands:

```bash
ambermeta export old.yaml -o new.yaml; echo "exit: $?"
```

```
ERROR: Failed to load manifest: old.yaml is not a v2 manifest (no 'steps' key). Rebuild it with `ambermeta discover <dir> --write <path>`.
exit: 1
```

Do what it says: rebuild from the directory with `discover --write`, then edit the draft as above.

Prefer a browser? [§3](#3-round-trip-a-manifest-through-the-gui) does the same discover → edit → save loop in the GUI, and writes the identical file. Full schema: [manifest reference](manifest.md). Full flag reference: [CLI reference](cli.md).

**Just want the numbers, not a manifest?** `ambermeta plan <dir> --recursive` scans the same directory through the retained flat engine and prints a per-stage *Protocol summary* — durations, thermostat/barostat, frame counts, per-stage statistics — without producing a document to maintain. See [recipes](recipes.md) and [cli.md](cli.md#plan) for that mode.

---

## 2. Validate continuity and catch a sequence hole

**Goal:** confirm a simulation's steps actually connect, and understand the two distinct things AmberMeta checks for.

`ambermeta validate --manifest` runs whole-Simulation validation: per-step file checks, plus two continuity-specific things —

- **Continuity**: does each step's declared input-coordinate time match the end-time of the step it's chained from? A `default_tolerance` (0.1 ps, or half the previous step's frame interval if larger) absorbs floating-point noise; anything bigger is a real finding.
- **Sequence holes**: does a numbered run (`ntp_prod_0001`, `0002`, …) skip an index? This is checked independently of continuity — a missing member is flagged even if every step that *is* present chains perfectly.

### A sequence hole

Copy the sample data but drop `ntp_prod_0003`:

```bash
mkdir -p /tmp/ambermeta-hole && cd /tmp/ambermeta-hole
cp /tmp/ambermeta-tutorial/CH3L1_HUMAN_6NAG.* .
cp /tmp/ambermeta-tutorial/ntp_prod_000{1,2,4,5}.* .
ambermeta discover . --write manifest.yaml
```

```
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

Wrote v2 draft manifest: manifest.yaml (yaml)
```

`discover` already flagged it as `[needs_you]`. `validate --manifest` surfaces the same finding:

```bash
ambermeta validate --manifest manifest.yaml
```

```
Simulation validation

Continuity / sequence findings:
  - ntp_prod sequence is missing member(s) 3: present members of 'ntp_prod' skip index(es) 3

Validation: OK
```

Note the verdict is still `OK` — a sequence hole is a "needs you" finding, not a hard error, because a genuinely non-contiguous set of runs (independent replicas, say) is legitimate. `ntp_prod_0004`'s continuity is *not* separately flagged as broken: its bound input-coordinate source is honestly `ntp_prod_0002`'s own restart (that's the file that exists), so the continuity check — which only compares a step's declared input against its declared predecessor — has nothing to complain about. The hole is a distinct, first-class finding. To make holes count as failures in CI:

```bash
ambermeta validate --manifest manifest.yaml --strict; echo "exit: $?"
```

```
Simulation validation

Continuity / sequence findings:
  - ntp_prod sequence is missing member(s) 3: present members of 'ntp_prod' skip index(es) 3

Validation: OK
exit: 1
```

### A continuity break

This time take the intact 5-step `simulation.yaml` from [§1](#1-discover-edit-and-export-a-v2-manifest) and introduce a real mistake: point `ntp_prod_0003` at `ntp_prod_0001`'s restart instead of `ntp_prod_0002`'s (a copy-paste error while hand-editing).

```bash
cd /tmp/ambermeta-tutorial
cp simulation.yaml broken.yaml
```

```yaml
# broken.yaml — ntp_prod_0003's input_coords, edited
input_coords:
  source: step
  ref: 8f9b2e3f          # was de27bb87 (ntp_prod_0002) — now points at ntp_prod_0001
```

`ref` is the only thing you set. The restart filename is not repeated here: it lives on the producing step's `rst`, and AmberMeta follows `ref` to find it. (Ids are `uuid4` slices regenerated by every `discover` run, so copy the real ones out of *your* `simulation.yaml` rather than the ones printed here.)

```bash
ambermeta validate --manifest broken.yaml
```

```
Simulation validation

Continuity / sequence findings:
  - Continuity note: Stage appears to overlap previous stage by 20000 ps.
  - Continuity note: Gap detected without stated expectation; verify continuity.

Protocol notes:
  - Stage appears to overlap previous stage by 20000 ps.
  - Gap detected without stated expectation; verify continuity.

Validation: OK
```

This time it's a genuine continuity problem: `ntp_prod_0002` really did finish 20000 ps later than the restart `ntp_prod_0003` now claims to start from. `--format json` gives the same finding machine-readably, including which step it's attached to:

```bash
ambermeta validate --manifest broken.yaml --format json
```

```json
{
  "ok": true,
  ...
  "stage_issues": [
    ...
    {
      "name": "ntp_prod_0003",
      "ok": true,
      "degraded": false,
      "errors": [],
      "warnings": [
        "Stage appears to overlap previous stage by 20000 ps.",
        "Gap detected without stated expectation; verify continuity."
      ],
      "info": [],
      "continuity": [
        "Stage appears to overlap previous stage by 20000 ps.",
        "Gap detected without stated expectation; verify continuity."
      ],
      "missing_files": []
    },
    ...
  ],
  "suggestions": [
    ...
    {
      "id": "sug_c_3",
      "kind": "continuity_gap",
      "severity": "needs_you",
      "title": "Continuity note",
      "evidence": "Stage appears to overlap previous stage by 20000 ps.",
      "actions": ["Set as expected", "Investigate"],
      "step_id": "6aa07bf3"
    },
    ...
  ]
}
```

(A step's own `notes` ride along in the same `warnings`/`protocol_issues` channel as real findings — if you added a note in [§1](#1-discover-edit-and-export-a-v2-manifest), you'll see it listed there too. Reserve `notes` for things worth a reviewer's attention.)

`--strict` turns this into exit code 1 the same way it did for the sequence hole. Restore the reference (`ref: de27bb87`, `ntp_prod_0002`'s id) and `validate` goes back to a bare `Validation: OK` — no findings section at all, which is itself the signal that continuity is clean.

**Declaring an intentional gap.** If a step genuinely restarts from a checkpoint after a real time jump, say so — an unstated gap is what triggers "verify continuity"; a stated one that matches is silently confirmed (`INFO`, not surfaced as a problem):

```yaml
- id: st_prod_003
  ...
  gaps: { expected: 2.0, tolerance: 0.5 }   # ps
```

**Replicas are not a gap — don't reach for `--allow-gaps`.** Blanket-suppressing gap findings used to be the only way to stop AmberMeta comparing one replica's first run against another's last, and it was always the wrong tool: it silences every unstated gap in the document, including the real ones inside a member, and it never touched the *overlap* half of the check at all. Declare the members instead — give each replica's steps a `lineage` tag ([manifest §5](manifest.md#5-steps)), or let `discover` infer it from `rep1/`, `rep2/` directories ([manifest §9.1](manifest.md#91-how-discover-infers-members)). Continuity is then measured inside each member and the boundary between members is never a finding, because it was never a transition.

`--allow-gaps` still exists and still works, for what it is actually for: a document with real, unstated time jumps you have decided not to annotate step by step. Using it alongside lineages is not an error. Full field reference: [manifest reference](manifest.md).

---

## 3. Round-trip a manifest through the GUI

**Goal:** discover, edit, validate, and save a manifest without touching a terminal — and confirm it's the exact file the CLI would have produced.

```bash
ambermeta gui .
```

```
Starting AmberMeta GUI...
Base directory: /tmp/ambermeta-tutorial
Server: http://127.0.0.1:8765
API docs: http://127.0.0.1:8765/docs

Opening browser: http://127.0.0.1:8765
```

This launches a local, single-user server (bound to `127.0.0.1` only) and opens a three-pane window at that URL:

1. **Files** (left) — a searchable list of everything under the launch directory. Rows carry data-driven hints (`prmtop`, `mdin`, restart, …).
2. **Canvas** (center) — a continuous vertical timeline: the phase as a section, steps as cards showing their bound topology (▸) and input-coordinate source (◂), with continuity arrows between them (amber only where a real gap exists) and a **missing-run ghost** where a sequence hole was detected.
3. **Inspector** (right) — peek and full-details/raw tabs for whatever's selected, an actions list, and inline editors for the selected step or phase (name, topology, input-coordinate source and "continues from", restart, gaps, notes; name and role for a phase).

Walk through the round trip:

1. Click **Discover**. The Files pane's `CH3L1_HUMAN_6NAG.top`/`.crd` and the five `ntp_prod_*` groups populate the Canvas as one `Production` phase with five steps, exactly like `ambermeta discover .` printed in [§1](#1-discover-edit-and-export-a-v2-manifest). The **Suggestions tray** lists the same `[applied]`/`[needs_you]` items the CLI's `Suggestions:` block shows.
2. Drag a file from **Files** onto a step's `mdin`/`mdout` slot, the topology pool, or the starting-structure slot to rebind it; drag a step card to reorder it within the phase or move it to another phase.
3. Click **Validate**. The panel lists the same findings `ambermeta validate --manifest` would print for this draft, with jump-to-issue.
4. Click **Save** and give it a filename (`gui_manifest.yaml`, say).

**Save writes exactly what the CLI writes.** The GUI's save handler and `ambermeta export`/`ambermeta discover --write` both call the same `ambermeta.simulation.write_simulation` — there is no separate GUI serializer. You can verify this from the terminal without touching the browser at all, since every GUI action is just a call to the local HTTP API (documented in full in the [GUI guide](gui.md)) that the page's own JavaScript calls:

```bash
curl -s -X POST http://127.0.0.1:8765/api/document/discover \
  -H "Content-Type: application/json" -d '{"recursive": true}' \
  | python -c "import json,sys; d=json.load(sys.stdin); print(d['document']['simulation']['phases'][0]['steps'][0]['id'])"
```

```
005b39cd
```

```bash
curl -s -X PUT http://127.0.0.1:8765/api/steps/005b39cd \
  -H "Content-Type: application/json" \
  -d '{"notes": ["Reviewed for the tutorial round-trip."]}' \
  -o /dev/null -w "PUT /api/steps/005b39cd -> %{http_code}\n"
```

```
PUT /api/steps/005b39cd -> 200
```

```bash
curl -s -X POST http://127.0.0.1:8765/api/validate -d '{}' -H "Content-Type: application/json" \
  | python -c "import json,sys; d=json.load(sys.stdin); print('ok:', d['ok'])"
```

```
ok: True
```

```bash
curl -s -X POST http://127.0.0.1:8765/api/document/save \
  -H "Content-Type: application/json" -d '{"path": "gui_manifest.yaml"}' \
  -o /dev/null -w "POST /api/document/save -> %{http_code}\n"
```

```
POST /api/document/save -> 200
```

Stop the server (`Ctrl+C` in its terminal), then check the file it wrote with the plain CLI:

```bash
ambermeta validate --manifest gui_manifest.yaml
```

```
Simulation validation

Validation: OK
```

```yaml
# gui_manifest.yaml (excerpt) — note the step notes made it through the save
steps:
- id: 005b39cd
  name: ntp_prod_0001
  ...
  notes:
  - Reviewed for the tutorial round-trip.
```

Same manifest, same validator, whichever end you edited it from. `Open`/`Save` in the GUI read and write this same v2 manifest the CLI does; `discover` in the GUI is the same `discover_draft` function `ambermeta discover` calls. Full pane-by-pane reference, the HTTP API surface, and the security model (file access is confined to the launch directory; a path-traversal attempt gets a `403`): [GUI guide](gui.md).

---

## See also

- [Recipes](recipes.md) — short copy-paste one-liners
- [CLI reference](cli.md) · [Python API](api.md) · [Manifest schema](manifest.md) · [GUI guide](gui.md) · [Architecture](architecture.md)
