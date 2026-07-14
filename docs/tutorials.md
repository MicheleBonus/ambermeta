# Tutorials

Task-oriented walkthroughs for getting real work done with AmberMeta. Each uses the sample data in `tests/data/amber/md_test_files/` — a 64,528-atom glycoprotein system (`CH3L1_HUMAN_6NAG.top` + `.crd`) with a six-member NPT production sequence (`ntp_prod_0001` … `ntp_prod_0005`) — so every command and every line of output below is reproducible. Run them from a writable scratch copy so you don't touch the repo's test fixtures:

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
3. [Upgrade a v1 manifest with `export`](#3-upgrade-a-v1-manifest-with-export)
4. [Round-trip a manifest through the GUI](#4-round-trip-a-manifest-through-the-gui)

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
  - ntp_prod_0002  topology=CH3L1_HUMAN_6NAG.top  input=step 8f9b2e3f  (mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)
  - ntp_prod_0003  topology=CH3L1_HUMAN_6NAG.top  input=step de27bb87  (mdin=ntp_prod_0003.mdin, mdout=ntp_prod_0003.mdout)
  - ntp_prod_0004  topology=CH3L1_HUMAN_6NAG.top  input=step 6aa07bf3  (mdin=ntp_prod_0004.mdin, mdout=ntp_prod_0004.mdout)
  - ntp_prod_0005  topology=CH3L1_HUMAN_6NAG.top  input=step 71f7cca0  (mdin=ntp_prod_0005.mdin, mdout=ntp_prod_0005.mdout)

Suggestions:
  - [applied] CH3L1_HUMAN_6NAG.crd set as the starting structure
  - [applied] Phase roles inferred from file content/names
```

`CH3L1_HUMAN_6NAG.top` was found once and put in the topology pool; `CH3L1_HUMAN_6NAG.crd` (a single-frame restart, no trajectory) was picked as the Simulation's starting structure and feeds `ntp_prod_0001`. Every later step's `input` is `step <id>` — the previous step's own output restart, the continuity chain. Both suggestions are `[applied]` automatically; a `[needs_you]` suggestion (you'll see one in [§2](#2-validate-continuity-and-catch-a-sequence-hole)) is not.

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

`export` re-emits any manifest (v1 auto-migrated) as canonical v2, or as a legacy flat manifest for tools that still expect one. Re-exporting to v2 canonicalizes formatting and lets you switch YAML/JSON:

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
# ... ntp_prod_0002 .. ntp_prod_0005 follow, each chained to the previous step
```

Or hand it to a tool that only understands the flat `stages:` shape:

```bash
ambermeta export simulation.yaml --to legacy -o legacy_export.json
```

```
Wrote legacy manifest: legacy_export.json (json)
```

```json
{
  "global_prmtop": "CH3L1_HUMAN_6NAG.top",
  "stages": [
    {
      "name": "ntp_prod_0001",
      "stage_role": "production",
      "prmtop": "CH3L1_HUMAN_6NAG.top",
      "mdin": "ntp_prod_0001.mdin",
      "mdout": "ntp_prod_0001.mdout",
      "inpcrd": "CH3L1_HUMAN_6NAG.crd",
      "notes": ["First production run; starts from the equilibrated starting structure."]
    },
    {
      "name": "ntp_prod_0002",
      "stage_role": "production",
      "prmtop": "CH3L1_HUMAN_6NAG.top",
      "mdin": "ntp_prod_0002.mdin",
      "mdout": "ntp_prod_0002.mdout",
      "inpcrd": "ntp_prod_0001.rst"
    }
    // ... ntp_prod_0003 .. ntp_prod_0005, each inpcrd chained to the previous stage's restart
  ]
}
```

Note what's lost going to legacy: the topology pool collapses to one `global_prmtop`, phases disappear (each step becomes a bare stage), and each step's continuity is flattened into a plain `inpcrd` path — the explicit `source`/`ref` distinction is gone. Round-trip through `--to v2` if you need it back.

Prefer a browser? [§4](#4-round-trip-a-manifest-through-the-gui) does the same discover → edit → save loop in the GUI, and writes the identical file. Full schema: [manifest reference](manifest.md). Full flag reference: [CLI reference](cli.md).

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
  - ntp_prod_0002  topology=CH3L1_HUMAN_6NAG.top  input=step baf48c84  (mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)
  - ntp_prod_0004  topology=CH3L1_HUMAN_6NAG.top  input=step f11face0  (mdin=ntp_prod_0004.mdin, mdout=ntp_prod_0004.mdout)
  - ntp_prod_0005  topology=CH3L1_HUMAN_6NAG.top  input=step dbee856a  (mdin=ntp_prod_0005.mdin, mdout=ntp_prod_0005.mdout)

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
  path: ntp_prod_0001.rst
```

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

`--strict` turns this into exit code 1 the same way it did for the sequence hole. Fix the reference (`ref: de27bb87`, `path: ntp_prod_0002.rst`) and `validate` goes back to a bare `Validation: OK` — no findings section at all, which is itself the signal that continuity is clean.

**Declaring an intentional gap.** If a step genuinely restarts from a checkpoint after a real time jump, say so — an unstated gap is what triggers "verify continuity"; a stated one that matches is silently confirmed (`INFO`, not surfaced as a problem):

```yaml
- id: st_prod_003
  ...
  gaps: { expected: 2.0, tolerance: 0.5 }   # ps
```

For genuinely independent, non-contiguous runs (replicas), pass `--allow-gaps` instead of annotating every step. Full field reference: [manifest reference](manifest.md).

---

## 3. Upgrade a v1 manifest with `export`

**Goal:** take a manifest written for AmberMeta 1.0 (flat `stages:`, `global_prmtop`) and get a canonical v2 file out of it — without hand-translating anything.

v1 manifests still open: the reader auto-migrates a flat `stages:` list (with `global_prmtop`/`hmr_prmtop`/per-stage `inpcrd`) into a `Simulation` in memory. Here's a v1 manifest, unchanged from what 1.0 would have read:

```yaml
# v1.yaml
global_prmtop: CH3L1_HUMAN_6NAG.top
stages:
  - name: ntp_prod_0001
    stage_role: production
    mdin: ntp_prod_0001.mdin
    mdout: ntp_prod_0001.mdout
    inpcrd: CH3L1_HUMAN_6NAG.crd

  - name: ntp_prod_0002
    stage_role: production
    mdin: ntp_prod_0002.mdin
    mdout: ntp_prod_0002.mdout
    inpcrd: ntp_prod_0001.rst

  - name: ntp_prod_0003
    stage_role: production
    mdin: ntp_prod_0003.mdin
    mdout: ntp_prod_0003.mdout
    inpcrd: ntp_prod_0002.rst
```

`plan --manifest` still reads it exactly as 1.0 did — a v1 flat manifest keeps the classic per-stage **Protocol summary** (the retained flat engine, not the new model):

```bash
ambermeta plan . --manifest v1.yaml
```

```
Loading manifest: v1.yaml

Protocol summary
================
Stages: 3
Total steps: 15000000
Total simulated time (ps): 60000.000

- ntp_prod_0001
  intent: production
  result: Completed
  prmtop: atoms=64528, box=98.34×76.05×81.23 Å, density=0.843 g/cc
  mdin: steps=5000000, dt=0.004 ps
  mdout: status=complete, steps=5000000, dt=0.004 ps, thermostat=Langevin @ 300 K, barostat=Berendsen, box=RECTILINEAR
  inpcrd: atoms=64528, box
  stats: frames=200, time=1020–20920 ps, temp=300.43 ± 1.25 K, density=1.0370 ± 0.0012 g/cc
  restart: /tmp/ambermeta-tutorial/CH3L1_HUMAN_6NAG.crd
  evidence: INFO: using global prmtop: CH3L1_HUMAN_6NAG.top
  note: INFO: using global prmtop: CH3L1_HUMAN_6NAG.top
...
```

`validate --manifest`, by contrast, always goes through the new model — it auto-migrates the v1 file first:

```bash
ambermeta validate --manifest v1.yaml
```

```
Simulation validation

Validation: OK
```

Now convert it for real:

```bash
ambermeta export v1.yaml -o v1_as_v2.yaml
```

```
Wrote v2 manifest: v1_as_v2.yaml (yaml)
```

```yaml
# v1_as_v2.yaml
version: 2
simulation:
  topologies:
  - id: top_0
    path: CH3L1_HUMAN_6NAG.top
    kind: normal
  starting_structure: null
phases:
- id: ph_0
  name: Production
  role: production
  order: 0
steps:
- id: st_0
  name: ntp_prod_0001
  phase: ph_0
  order: 0
  topology: top_0
  input_coords:
    source: path
    path: CH3L1_HUMAN_6NAG.crd
  mdin: ntp_prod_0001.mdin
  mdout: ntp_prod_0001.mdout
  mdcrd: null
  notes: []
- id: st_1
  name: ntp_prod_0002
  phase: ph_0
  order: 1
  topology: top_0
  input_coords: { source: step, ref: st_0 }
  mdin: ntp_prod_0002.mdin
  mdout: ntp_prod_0002.mdout
  mdcrd: null
  notes: []
- id: st_2
  name: ntp_prod_0003
  phase: ph_0
  order: 2
  topology: top_0
  input_coords: { source: step, ref: st_1 }
  mdin: ntp_prod_0003.mdin
  mdout: ntp_prod_0003.mdout
  mdcrd: null
  notes: []
```

`global_prmtop` became a single `normal` pool entry; the three flat stages became three steps under one auto-named `Production` phase, chained `st_0 → st_1 → st_2`. One thing worth noticing: `starting_structure` came back `null`. The migrator only promotes coordinates to the Simulation-level starting structure when v1 declared them that way (a top-level `initial_coordinates` key); this v1 file set `inpcrd` explicitly on the first *stage* instead, so the migrator kept that as an explicit `path` on `st_0` rather than guessing it should be global. That's a good moment to clean it up by hand:

```yaml
# v1_as_v2.yaml, hand-edited
simulation:
  ...
  starting_structure: CH3L1_HUMAN_6NAG.crd   # was null
steps:
- id: st_0
  ...
  input_coords:
    source: starting_structure               # was {source: path, path: CH3L1_HUMAN_6NAG.crd}
```

```bash
ambermeta validate --manifest v1_as_v2.yaml
```

```
Simulation validation

Validation: OK
```

```bash
ambermeta plan . --manifest v1_as_v2.yaml
```

```
Simulation summary
==================
Topologies (pool): 1
  - top_0 [normal]  CH3L1_HUMAN_6NAG.top
Starting structure: CH3L1_HUMAN_6NAG.crd
Phases: 1

Phase: Production [production]
  - ntp_prod_0001  topology=CH3L1_HUMAN_6NAG.top  input=starting structure  (mdin=ntp_prod_0001.mdin, mdout=ntp_prod_0001.mdout)
  - ntp_prod_0002  topology=CH3L1_HUMAN_6NAG.top  input=step st_0  (mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)
  - ntp_prod_0003  topology=CH3L1_HUMAN_6NAG.top  input=step st_1  (mdin=ntp_prod_0003.mdin, mdout=ntp_prod_0003.mdout)

Validation: OK
```

Note that `plan` now prints the new **Simulation summary** rather than the old **Protocol summary** — the only thing that changed between the two `plan` invocations above is that the file on disk is v2, not the command. That's the whole point: whether a manifest reads as a flat protocol or a three-level Simulation is a property of the file, and `export` is how you move a file from the former to the latter for good.

If you only need one field checked (`hmr_prmtop`, a stage role, …) rather than a full rewrite, the [manifest reference](manifest.md) documents exactly which v1 key becomes which v2 field. And if your downstream tooling can't take TOML/CSV *and* an HMR topology (CSV can't represent `hmr_prmtop` alongside `global_prmtop`), keep both a v2 (`export --to v2`) and a legacy (`export --to legacy`) copy side by side.

---

## 4. Round-trip a manifest through the GUI

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
3. **Inspector** (right) — peek and full-details/raw tabs for whatever's selected, plus an actions list. The step/phase inline editors here are still stubs in this release — do structural edits (renaming, gap tolerances, notes) by editing the saved YAML/JSON directly, as in [§1](#1-discover-edit-and-export-a-v2-manifest), until they land.

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
