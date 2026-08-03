# GUI guide

**The AmberMeta GUI is a browser-based editor for a Simulation → Phase → Step manifest, over the same engine the CLI uses.** It runs a small local web server, opens a three-pane app in your browser, and lets you assemble, audit, and save a manifest by dragging files onto a timeline instead of hand-editing YAML. It is single-user, **localhost-only**, and works fully offline — the frontend is a pre-built static bundle, no Node.js and no CDN.

> When to use it: interactively building or sanity-checking a manifest for a directory you're seeing for the first time. For scripting, CI, and cluster/SSH use, the [CLI](cli.md) is the complete headless equivalent — the GUI's **Save** writes the same canonical [v2 manifest](manifest.md) `ambermeta discover --write` or `ambermeta export` would.

---

## 1. Install & launch

The GUI needs the `gui` extra (FastAPI + Uvicorn); the frontend itself is pre-built and bundled under `ambermeta/gui/static/`, so there is no build step.

```bash
python -m pip install -e ".[gui]"
```

```bash
ambermeta gui [directory] [--host HOST] [--port PORT] [--no-browser]
```

| Option | Default | Meaning |
|---|---|---|
| `directory` | `.` | The directory the server may read files from (its containment root) |
| `--host` | `127.0.0.1` | Bind address — localhost only by default |
| `--port` | `8765` | Server port |
| `--no-browser` | _(off)_ | Don't auto-open the browser |

```bash
ambermeta gui tests/data/amber/md_test_files       # opens http://127.0.0.1:8765
ambermeta gui runs/ --port 9000 --no-browser       # then browse there yourself
```

The server (FastAPI + Uvicorn) binds the host/port, resolves `directory` to an absolute path and sets it as the containment root, and — unless `--no-browser` — opens `http://<host>:<port>` in your default browser after a short delay.

> ⚠️ **The launch directory is a hard boundary.** The server only reads files inside `directory` (resolved with `realpath`, symlink-safe). Launch it at the top of the project you want to work with.

---

## 2. The window

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ AmberMeta [Open] [Save] ●   [Discover] [Validate] [Plan] [Export] [↶] [↷]    │
├───────────────┬────────────────────────────────────┬─────────────────────────┤
│               │  Simulation                        │                         │
│  FILES        │  ┌ pool ───────────────────────┐   │  INSPECTOR              │
│               │  │ CH3L1…top [normal ▾] ×      │   │                         │
│  [search…]    │  └────────────────────────────┘   │  (file peek / details / │
│  ⠿ system.top │  starting structure: …6NAG.crd ×  │   assign actions, or    │
│  ⠿ prod_0001… │                                    │   the suggestions      │
│  ...          │  ▎ Production  role ▾  topology ▾  + ⌧                     │
│               │  ┃ ┌ ⠿ ntp_prod_0001  ▸ …top ×  ◂ starting structure · …crd │
│               │  ┃ │   mdin: …0001.mdin  mdout: …0001.mdout  mdcrd: —       │
│               │  ┃ │   rst: ntp_prod_0001.rst ×                              │
│               │  ┃ └───────────────────────────────┘                         │
│               │  ┃      ↓ ntp_prod_0001.rst                                  │
│               │  ┃ ┌ ⠿ ntp_prod_0002  ▸ …top ×  ◂ restart of ntp_prod_0001  │
│               │  ┃ └───────────────────────────────┘                         │
└───────────────┴────────────────────────────────────┴─────────────────────────┘
```

| Pane / control | Role |
|---|---|
| **Files** (left) | A searchable, drag-source file list scanned from the launch directory. |
| **Canvas** (center) | The Simulation header (topology pool + starting structure) above a vertical timeline of phase sections and step cards. |
| **Inspector** (right) | Peek/details/assign actions for the selected file; a stub editor for a selected step or phase; the suggestions tray when the Simulation itself or nothing is selected (§6). |
| **Open / Save** | Load an existing manifest / write the current one to disk (dot = unsaved changes). |
| **Discover** | Discover-as-draft: scan the launch directory into a Simulation draft. |
| **Validate** | Run full validation and show the report. |
| **Plan** | Write the manifest and the summaries `ambermeta plan` produces, in one action. |
| **Export** | Preview the manifest as YAML or JSON and copy it. |
| **↶ / ↷** | Undo / redo, resolved server-side. |

Each pane is resizable (drag the divider); widths persist across sessions.

---

## 3. A typical session

1. **Discover.** Click **Discover**, optionally uncheck "Search subdirectories" or set a filename pattern, then **Run discover**. The server scans the launch directory, groups files by stem, classifies the topology pool (normal vs. HMR), picks a starting structure, and chains later steps' input coordinates to the previous step's output restart — the previous step **of the same lineage**, when the directory layout names members (`rep1/`, `rep2/`, … running the same set of runs); each member then starts from the starting structure and same-role steps of every member share one phase. This **replaces** the current draft (a confirmation guards unsaved changes) and repopulates the suggestions tray.
2. **Assign & adjust.** Drag a file from **Files** onto the topology pool, the starting-structure slot, a step's `mdin`/`mdout`/`mdcrd`/`rst` slot, or a phase's/step's topology target. Or select a file in **Files** and use the Inspector's **Assign** actions (§6) — the same mutations, without dragging.
3. **Arrange.** In the **Canvas**, drag a step's grip handle to reorder it within a phase or drop it onto another phase to move it; drag a phase's grip handle to reorder phases.
4. **Validate.** Click **Validate**. The panel lists per-step issues (missing files, continuity/sequence problems) and protocol-level notes, and lets you jump to a step. A simulation with continuity notes shows as *valid, with N protocol note(s)* — never a silent clean pass when something is worth a look.
5. **Save / Plan / Export.** **Save** writes the canonical **v2 manifest** to disk (YAML or JSON) and reports the path it wrote. **Plan** is the step after that: it writes the manifest *and* the artifacts [`ambermeta plan`](cli.md) produces — `summary.json`, `methods_summary.json`, and optionally a statistics CSV — so the whole pipeline is one action rather than a save followed by a trip to a terminal. **Export** previews YAML or JSON for copying without writing anything.

Undo/redo (**Ctrl+Z** / **Ctrl+Shift+Z**, **Ctrl+Y**) and a dirty-state dot live in the top bar; history is kept on the server (100 steps). **Open** resets it — a different manifest is a new editing session — while **Discover** does not, so a discovery run on the wrong directory is one undo away. Removing something (a step, a phase, a topology, the starting structure) reports itself with an **Undo** button; that offer disappears as soon as you make another change, because undo always reverses the most recent one.

An edit that the chain rules let through but could not honour in full reports itself in the same place, as a **warning-toned message** — deleting a step that runs in several lineages continued from (which also carries an Undo offer), or setting a "continues from" that crosses a lineage boundary (which does not; `lineage` in [`docs/manifest.md` §5](manifest.md#5-steps) says what a member is). It is not an error: the edit landed, and the message says what it cost so you can go and look. It has the same lifetime as an Undo offer and for the same reason — it describes one edit, so the next one clears it.

---

## 4. Files pane

Files are tagged by type from extension, and by canonical Amber default basename when extensionless:

| Type | Extensions | Extensionless default |
|---|---|---|
| `prmtop` | `.prmtop`, `.parm7`, `.top` | `prmtop`, `parm7` |
| `mdin` | `.mdin`, `.in` | `mdin` |
| `mdout` | `.mdout`, `.out` | `mdout` |
| `mdcrd` | `.mdcrd`, `.nc`, `.crd`, `.x`, `.trj` | `mdcrd` |
| `inpcrd` | `.inpcrd`, `.rst`, `.rst7`, `.restrt`, `.ncrst` | `inpcrd`, `restrt` |

> `.in`/`.out` are claimed for Amber `mdin`/`mdout` by convention — a non-Amber `.in`/`.out` in the launch directory would be mis-typed as one. Content sniffing is a possible follow-up, not done today.

The tree descends up to five levels and skips `.`-prefixed directories, `__pycache__`, `node_modules`, and `.git`. Use the search box to filter by name. Every row is a drag source; drop it on a canvas target to assign it, or select it to inspect and use the Assign actions.

---

## 5. Canvas: the timeline

The canvas is a continuous vertical timeline, not a flat list of cards.

**Simulation header** — click "Simulation" to select the Simulation itself (shows the suggestions tray). Below it:
- **Topology pool** — a drop zone. Each entry shows its path and a `normal`/`HMR` badge. Drop a `prmtop` here to add it to the pool.
- **Starting structure** — the single-frame coordinates that feed the first step. Drop a file on it, click it to browse, or clear it with the ×.
- Each pooled topology carries a `normal`/`HMR` selector (the kind is only guessed from the filename when the file is added) and a × that removes it from the pool; the tooltip names how many steps would be left without a topology.

**Phase sections** — one per phase, in protocol order, with a left accent bar. Each header shows the phase name, its role badge (`minimization`/`heating`/`equilibration`/`production`, or none), and a **topology** selector that sets — or, via `— none —`, clears — the topology of every step currently in the phase. A phase stores no topology of its own, so the selector reports what its steps hold: one shared entry, `Mixed` when they disagree, or none. The grip handle drags the whole phase to reorder it.

**Step cards** — inside each phase, grouped by numeric base name (so `ntp_prod_0001..0005` group together) and shown in ascending numeric order:
- `▸ <topology path>` — the step's bound topology; HMR-bound steps get an accent color and an `HMR` badge.
- `◂ <source>` — where this run's coordinates come from: `◂ starting structure · wt.crd`, `◂ restart of 01_min · 01_min.rst` (chained — the **name** of the step it continues from, plus the file that link resolves to), or `◂ <explicit path>`.
- Four dashed drop-target slots: `mdin`, `mdout`, `mdcrd` and `rst`, each showing its filename or `—` and a × to clear it. `rst` is the restart this run **writes**; the next step reads it.
- A grip handle to drag the step within the phase or onto another phase.

**Continuity arrows** sit between consecutive steps in a sequence. When the lower step continues from the upper one, the arrow is labelled with the restart file that passes between them — that file belongs to neither card alone, so the edge is where it is shown. An amber arrow annotated with the gap magnitude (e.g. `20 ps`) marks a real continuity gap.

**Missing-run ghosts** — a dashed, muted card labeled `<name> missing` is inserted at the correct position in a numbered sequence when a member is absent (e.g. `ntp_prod_0003` between `0002` and `0004`), driven by the same sequence-hole detection the CLI uses.

**Long numbered runs collapse**: a group of 6 or more steps sharing a numeric base starts collapsed behind a `<base> × N steps` toggle; expand it to work with the individual cards.

If the Simulation has no phases yet, the canvas shows "Discover or drop files to start".

---

## 6. Inspector pane

The Inspector's content depends on what's selected:

- **A file** (from the Files pane, or a step's bound topology) — a **peek** header (filename plus a few curated fields: atoms, residues, frames, steps, `hmr_active`, box), an **Assign** section (below), and a tabbed detail view: **Overview** (parsed-field count, warning count), **Full details** (every parsed field), **Raw file** (a byte-capped prefix of the file), **Warnings**.
- **A step or a phase** — a placeholder (`Step editor.` / `Phase editor.`). **These inline editors are stubs today**: selecting a step or phase does highlight it and lets Validate jump to it, but editing its name, role, gap tolerance, or notes from the Inspector is not yet wired up. Use drag-and-drop assignment, the Inspector's file-side Assign actions, or the [HTTP API](#11-http-api)/CLI to change those fields in the meantime.
- **The Simulation, or nothing** — the **suggestions tray** (§7).

### Assign actions (per selected file type)

| File type | Actions offered |
|---|---|
| `prmtop` | **Add to pool as HMR** / **Add to pool as normal** (pre-selected by whether the filename contains `hmr`); **Set as phase default ▾** (assigns this topology to every step in a chosen phase); **Assign to a step ▾** (assigns it to one step) |
| `inpcrd` | **Set as starting structure** |
| `mdin` | A **Role** selector (Minimization/Heating/Equilibration/Production/Unassigned) and **Create a step** — reuses an existing phase with that role or creates one, then creates a step named after the file's stem with this `mdin` bound |
| `mdcrd`, `mdout`, other | No assign actions (assign these to an existing step's slot by dragging onto its card instead) |

---

## 7. Suggestions tray

Every inferred thing is surfaced as an explainable suggestion rather than applied silently — this is the draft-first design: roles, the HMR topology, the starting structure, sequence holes, and continuity gaps all show up here. Suggestions are grouped:

- **Needs you** — something the tool can't resolve on its own (`missing_run`: a numbered-sequence hole; `continuity_gap`: a genuine start/end mismatch between consecutive steps; `topology_confirm`: more than one topology in the pool, confirm which is HMR). Each card offers **Accept** / **Adjust** / **Ignore**.
- **Applied** — something already reflected in the draft, shown for transparency (`starting_structure`, `role_guess`, `lineage_group`: the run lineages the document declares, how many runs each holds, and how many carry none). Each card offers **Dismiss**, plus **Undo** (calls the server's undo) when the suggestion says it can be undone.

Every card shows a `title` and a monospace `evidence` string explaining the inference. Dismissing a card only hides it in this browser session — it does not mutate the document; **Undo** is the only action here that does.

A `missing_run` card carries a `lineage` field naming the member it is scoped to (`null` for the untagged bucket), so a replica that stopped early is named rather than pooled with its siblings:

```jsonc
{ "id": "sug_1", "kind": "missing_run", "severity": "needs_you",
  "title": "rep2/prod sequence is missing member(s) 2, 3",
  "evidence": "'rep2/prod' has no run at index(es) 2, 3",
  "base": "prod", "missing": [2, 3], "lineage": "rep2",
  "actions": ["Mark as expected gap", "Locate file", "Ignore"] }
```

`lineage_group` is the `[applied]` card reporting membership itself. Its evidence names each declared member and its run count, and counts the untagged runs separately — left unsaid, "3 lineages" would read as covering all nine runs of a campaign whose shared prep carries no tag at all:

```jsonc
{ "id": "sug_2", "kind": "lineage_group", "severity": "applied",
  "title": "Runs carry 3 declared lineage(s)",
  "evidence": "rep1: 2 run(s); rep2: 2 run(s); rep3: 2 run(s); no lineage: 3 run(s)",
  "actions": ["Undo"] }
```

That card reports what the document **declares**, not where the tags came from — nothing after the fact can tell an inferred tag from a hand-written one, so a manifest whose lineages you typed yourself is described the same way. `discover` announces its own inference by running this over the draft it just built.

(Both blocks above elide the always-present `step_id`/`phase_id`/`base`/`missing`/`lineage` keys where they are `null` — no route sets `exclude_none`, so every key is on the wire on every card.)

The tray re-runs validation (and refills itself) after every document mutation, after Discover, and whenever the Validate panel is opened.

---

## 8. Open, Save, Export

- **Open** loads a **v2 manifest** — YAML or JSON — and resets undo history. There is no other reader. An old flat `stages:` document and a `.toml`/`.csv` path are each rejected with `400` and the core reader's own message (respectively):

  ```
  Could not read manifest: /abs/path/old.yaml is not a v2 manifest (no 'steps' key). Rebuild it with `ambermeta discover <dir> --write <path>`.
  Could not read manifest: /abs/path/old.toml: AmberMeta reads and writes manifests as YAML or JSON only; TOML and CSV are not manifest formats.
  ```

  The embedded path is always absolute: the request path is resolved through `os.path.realpath` before
  the reader ever sees it, so what comes back is never the bare filename the client sent.

  Rebuild such a file with `ambermeta discover <dir> --write <path>` and open the result.
- **Save** always writes the canonical **v2 manifest** — YAML or JSON only, chosen by the target's extension or by the Save dialog's format selector, which offers exactly those two.
- **Export** renders a preview (YAML or JSON) in a modal without touching disk, with a **Copy** button; any writer warnings are listed underneath.

The manifest the GUI writes (real output — `Save` after `Discover` on the sample glycoprotein sequence, path `manifest_test.yaml`):

```yaml
version: 2
simulation:
  topologies:
  - id: top_CH3L1_HUMAN_6NAG
    path: CH3L1_HUMAN_6NAG.top
    kind: normal
  starting_structure: CH3L1_HUMAN_6NAG.crd
phases:
- id: a2a37983
  name: Production
  role: production
  order: 0
steps:
- id: b71986d7
  name: ntp_prod_0001
  phase: a2a37983
  order: 0
  topology: top_CH3L1_HUMAN_6NAG
  input_coords:
    source: starting_structure
  mdin: ntp_prod_0001.mdin
  mdout: ntp_prod_0001.mdout
  mdcrd: null
  notes: []
  rst: ntp_prod_0001.rst
- id: c1e0498e
  name: ntp_prod_0002
  phase: a2a37983
  order: 1
  topology: top_CH3L1_HUMAN_6NAG
  input_coords:
    source: step
    ref: b71986d7
  mdin: ntp_prod_0002.mdin
  mdout: ntp_prod_0002.mdout
  mdcrd: null
  notes: []
  rst: ntp_prod_0002.rst
# ...ntp_prod_0003..0005 follow the same chained-restart pattern
```

Note `discover` here only found one `prmtop`, so it became the sole (`normal`) pool entry and every step bound it — with two topologies present, the second (`hmr`-named) one would also show up in the pool and a `topology_confirm` suggestion would ask you to confirm which is which.

---

## 9. Validation

**Validate** builds a report against the same engine the CLI uses. Real output (`POST /api/validate` after Discover, on the sample data):

```json
{
  "ok": true,
  "totals": { "steps": 25000000.0, "time_ps": 100000.0, "stage_count": 5.0 },
  "protocol_issues": [],
  "stage_issues": [
    { "name": "ntp_prod_0001", "ok": true, "degraded": false,
      "errors": [], "warnings": [], "info": [], "missing_files": [] }
  ],
  "suggestions": [
    { "id": "sug_1", "kind": "starting_structure", "severity": "applied",
      "title": "CH3L1_HUMAN_6NAG.crd set as the starting structure",
      "evidence": "single-frame coordinates; feeds the first run", "actions": ["Undo"] },
    { "id": "sug_2", "kind": "role_guess", "severity": "applied",
      "title": "Phase roles inferred from file content/names",
      "evidence": "Production->production", "actions": ["Undo"] }
  ]
}
```

The panel shows a status badge — `N stage(s) with errors` if any step failed, else `Valid, with N protocol note(s)` if there are protocol-level notes, else `All checks passed` — then any protocol notes, then a per-step card (`ok`/`error` badge, errors/warnings/info) you can click to select that step (subject to the Inspector's step-editor stub, §6). A non-empty `protocol_issues` list means the simulation is *not* fully clean even when every step reports `ok` — the panel reflects that rather than reporting a false all-clear.

---

## 10. Security model

The GUI is built to be safe to run on a workstation; it is not a multi-user service.

| Control | Mechanism |
|---|---|
| **Localhost only** | Binds `127.0.0.1` by default. |
| **CORS pinned** | The CORS middleware allows only `http://localhost:8765` and `http://127.0.0.1:8765` (the default port). The bundled frontend is served same-origin from the API's own host:port, so this mainly hardens against a separately-hosted page targeting the API — it does not widen with `--port`. |
| **No path escape** | Every request-supplied path is resolved with `realpath` against the launch directory and rejected with `403` if it falls outside it (verified: `GET /api/files?path=../../` → `403`). |
| **API can't be spoofed by the SPA** | The catch-all static route returns `404` for any unmatched `/api/*` path (verified: `GET /api/nonexistent` → `404`) and refuses `..`/absolute path segments before serving a file, falling back to the app shell. |
| **Server-authoritative state** | One in-memory `Simulation` document on the server is the source of truth; the browser is a view. Validation and undo/redo run server-side; every mutating response returns the full updated document. |

> ⚠️ Binding `--host 0.0.0.0` exposes the launch directory's file browser to your network. Only do so on a trusted network, and prefer an SSH tunnel for remote access.

---

## 11. HTTP API

The frontend talks to a small REST API under `/api` (`ambermeta/gui/api/routes.py`). You can drive it directly for scripting or testing — every mutating call returns the full updated document.

### Document

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/api/document` | — | Current document |
| `POST` | `/api/document/open` | `{ path }` | Document (history reset); `404` if the file doesn't exist, `400` if it isn't a v2 YAML/JSON manifest |
| `POST` | `/api/document/save` | `{ path?, format? }` | `{ document, warnings[] }`; `400` if no path is known and none is given |
| `POST` | `/api/document/preview` | `{ format }` | `{ content, warnings[], format }` |
| `POST` | `/api/document/discover` | `{ recursive, pattern? }` | `{ document, suggestions[], warnings[] }` |

### Topologies & starting structure

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/topologies` | `{ path, kind }` (`kind` default `normal`) | Document |
| `PUT` | `/api/topologies/{id}` | `{ path?, kind? }` | Document (`404` if unknown) |
| `DELETE` | `/api/topologies/{id}` | — | Document (`404` if unknown; clears the id from any step that referenced it) |
| `PUT` | `/api/simulation/starting-structure` | `{ path? }` | Document |

### Phases & steps

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/phases` | `{ name, role? }` | Document |
| `POST` | `/api/phases/reorder` | `{ phase_ids[] }` | Document (`400` unless the id set matches exactly) |
| `PUT` | `/api/phases/{id}` | `{ name?, role?, topology? }` — `topology` present (including `null`) sets or clears it on **every step of the phase** in one undoable operation | Document (`404` if the phase or the topology id is unknown) |
| `DELETE` | `/api/phases/{id}?reassign_to=<phase_id>` | — | Document (`404`; `400` if `reassign_to` is the phase being deleted); moves the deleted phase's steps to `reassign_to` if given |
| `POST` | `/api/phases/{id}/steps` | `{ name, topology?, input_coords?, mdin?, mdout?, mdcrd?, rst?, lineage?, index?, expected_gap_ps?, gap_tolerance_ps?, notes? }` — `lineage` places the step in that member; `index` (default `-1`) is the position within the phase, appending **within the step's own lineage** | Document (`404` if phase unknown, `400` for an unusable `input_coords.ref` — see below) |
| `POST` | `/api/phases/{id}/steps/reorder` | `{ step_ids[] }` | Document (`404`/`400`) |
| `PUT` | `/api/steps/{id}` | `{ name?, topology?, input_coords?, files?: {mdin?,mdout?,mdcrd?,rst?}, expected_gap_ps?, gap_tolerance_ps?, notes? }` — `topology`, `expected_gap_ps` and `gap_tolerance_ps` use present-vs-absent: sending `null` clears, omitting leaves alone | Document (`404`; `400` for an unusable `input_coords.ref` — see below) |
| `DELETE` | `/api/steps/{id}` | — | Document (`404`) |
| `POST` | `/api/steps/{id}/move` | `{ phase_id, index? }` (`index` default `-1` = append) | Document (`404`) |

#### `input_coords.ref` is validated — three `400`s

`POST /api/phases/{id}/steps` and `PUT /api/steps/{id}` both refuse a "continues from" that cannot mean
anything. Previously either would store one verbatim, so a dead id resolved to no coordinates while the
chain still looked intact, and a self-reference made a one-step cycle:

```
$ curl -X PUT .../api/steps/9831ac9c -d '{"input_coords":{"source":"step","ref":"deadbeef"}}'
400 {"detail":"no step to continue from: deadbeef"}

$ curl -X PUT .../api/steps/9831ac9c -d '{"input_coords":{"source":"step","ref":"9831ac9c"}}'
400 {"detail":"a step cannot continue from itself"}

$ curl -X PUT .../api/steps/9831ac9c -d '{"input_coords":{"source":"step"}}'
400 {"detail":"a step that continues from another must name it"}
```

A **cross-lineage** `ref` is a different case and is **accepted with `200`**: setting one by hand is the only
way to express a genuine branch, so it is honoured and reported in `warnings` rather than rejected
(see [the data model](#data-model-documentresponse) below). No automatic operation will create or maintain
one — [manifest §6](manifest.md#the-chain-invariant) states the invariant.

Adding a step to a **multi-lineage phase without naming a lineage** does not auto-chain it at all: it is
created reading the starting structure rather than continuing whichever step happens to sit last. Silence
is recoverable, a false edge is not — pass `lineage` and it is inserted after that member's last step and
chained to it instead.

`lineage` is **read-only at this surface in this release.** `StepCreate` honours it, so a step can be born
into a member; `StepUpdate` declares the field but no route writes it, so `PUT /api/steps/{id}` with
`{"lineage": "..."}` returns `200` and leaves the tag unchanged. Retag by editing the manifest and
reopening it, or let `discover` infer it.

### Unified assignment, settings, history, validation

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/assign` | `{ path, target_type, target_id?, kind?, slot? }` — `target_type` ∈ `pool \| starting_structure \| phase_topology \| step_topology \| step_slot` (`step_slot` also needs `slot` ∈ `mdin\|mdout\|mdcrd\|rst`) | Document (`404`/`400`) |
| `GET` / `PUT` | `/api/settings` | _(GET)_ / `{ auto_link_restarts?, strict_validation?, allow_gaps?, use_relative_paths? }` | Settings / Document |
| `POST` | `/api/undo` · `/api/redo` | — | Document |
| `POST` | `/api/plan` | `{ save_manifest_path?, summary_path?, methods_summary_path?, stats_csv_path?, summary_format? }` — a `null` path skips that artifact; `summary_format` is `json`\|`yaml` and the methods summary is always JSON | `{ written[], failed[], warnings[], stage_count, totals, document }` — `failed[]` names any artifact that could not be written, so a partial success is reported rather than implied (`400` if nothing was selected or a format is unsupported, `403` outside the launch directory) |
| `POST` | `/api/validate` | — | Validation report (§9) |

### Files

| Method | Path | Query | Returns |
|---|---|---|---|
| `GET` | `/api/files` | `path?`, `recursive?` (default `true`), `include_all?` (default `false`) | File tree (`FileInfo[]`), depth-limited to 5 |
| `GET` | `/api/files/metadata` | `path` | `{ file_path, file_type, metadata, warnings[] }` |
| `GET` | `/api/files/raw` | `path`, `max_bytes?` (default `4096`) | `{ path, content, truncated }` |
| `GET` | `/api/files/related/{stem}` | — | `{ kind: path, ... }` for files sharing `stem`'s basename |

Real session against the sample data (`ambermeta gui tests/data/amber/md_test_files --no-browser --port 8799`):

```bash
$ curl -s http://127.0.0.1:8799/api/document
{"base_directory":"...\\tests\\data\\amber\\md_test_files","manifest_path":null,"dirty":false,
 "can_undo":false,"can_redo":false,
 "settings":{"auto_link_restarts":true,"strict_validation":true,"allow_gaps":false,"use_relative_paths":true},
 "simulation":{"version":2,"topologies":[],"starting_structure":null,"phases":[]}}

$ curl -s -X POST http://127.0.0.1:8799/api/document/discover \
    -H 'Content-Type: application/json' -d '{"recursive": true}'
# -> {"document": {... 1 topology, starting_structure set, 1 phase "Production" with 5 chained steps ...},
#     "suggestions": [{"kind":"starting_structure", ...}, {"kind":"role_guess", ...}], "warnings": []}

$ curl -s "http://127.0.0.1:8799/api/files?recursive=false" | head -c 200
[{"path":"...CH3L1_HUMAN_6NAG.crd","name":"CH3L1_HUMAN_6NAG.crd","file_type":"mdcrd",
  "is_directory":false,"size":2387632,"extension":".crd", ...

$ curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8799/api/files?path=../../'
403

$ curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8799/api/nonexistent'
404
```

### Data model: `DocumentResponse`

```jsonc
{
  "base_directory": "...",
  "manifest_path": null,
  "dirty": false, "can_undo": false, "can_redo": false,
  "settings": { "auto_link_restarts": true, "strict_validation": true,
                "allow_gaps": false, "use_relative_paths": true },
  "simulation": {
    "version": 2,
    "topologies": [ { "id": "top_CH3L1_HUMAN_6NAG", "path": "CH3L1_HUMAN_6NAG.top", "kind": "normal" } ],
    "starting_structure": "CH3L1_HUMAN_6NAG.crd",
    "phases": [
      { "id": "a2a37983", "name": "Production", "role": "production",
        "steps": [
          { "id": "b71986d7", "name": "ntp_prod_0001", "topology": "top_CH3L1_HUMAN_6NAG",
            "input_coords": { "source": "starting_structure", "ref": null, "path": null },
            "mdin": "ntp_prod_0001.mdin", "mdout": "ntp_prod_0001.mdout", "mdcrd": null,
            "rst": "ntp_prod_0001.rst",
            "lineage": null,
            "resolved_input_coords": "CH3L1_HUMAN_6NAG.crd",
            "expected_gap_ps": null, "gap_tolerance_ps": null, "notes": [] }
        ] }
    ]
  },
  "warnings": []
}
```

This is `ambermeta.gui.api.schemas.DocumentResponse` — the same shape the frontend renders and the shape `simulation_to_payload`/`payload_to_simulation` round-trip to a v2 manifest (`docs/manifest.md`).

`warnings` is the one field that describes the **request** rather than the document: what the edit just made could not do without inventing a link nobody declared — a step several lineages continued from deleted, a `ref` set across a lineage boundary. The next **mutation** replaces it, so it is never a running total; a `GET /api/document` in between still shows the last edit's, since a read is not an edit. `save` and `plan` are not mutations of the document and do not clear it, so the copy embedded in their responses is the *previous* edit's — read `warnings` off the mutation's own response, not off a later one. `discover` replaces the document wholesale and so always reports an empty list here. The GUI announces it as a warning-toned message on the edit that raised it (§3); a script driving the API should read it off the mutation's own response.

One field here has no counterpart on disk: **`resolved_input_coords` is read-only and API-only**. The server resolves the chain (`starting_structure`, or `ref` → that step's `rst`, or an explicit `path`) and hands the answer over so the frontend never re-implements the rules. Sending it back is not how you change what a step reads — set `input_coords` instead. `rst`, by contrast, is a real manifest field: the restart this step produces.

---

## 12. Known limitations

- **Step and phase inline editing is stubbed.** The Inspector shows a placeholder (`Step editor.` / `Phase editor.`) when a step or phase is selected — you cannot yet rename a step, change its role, or set its gap tolerance/notes from there. Reach those fields via drag-and-drop assignment, the file-side Assign actions (§6), the HTTP API (§11), or by editing the saved manifest and reopening it.
- **Suggestion cards are advisory**, not bound to their nominal actions beyond Dismiss/Undo — "Accept"/"Adjust"/"Ignore" currently just dismiss the card in the browser; the underlying condition (e.g. a sequence hole) still needs to be fixed via assignment or by adding the missing run's files.
- **Save and Preview write v2 only, as YAML or JSON.** `write_simulation` accepts no other format (anything else raises `ValueError: v2 write supports json/yaml only, got: <fmt>`), and there is no other on-disk form to fall back to — so a manifest leaving the GUI is always one of those two.

---

## 13. Troubleshooting

| Symptom | Fix |
|---|---|
| `ImportError: fastapi` (or the launcher exits with "GUI dependencies not installed") | Install the GUI extra: `pip install -e ".[gui]"` |
| Browser didn't open | Use `--no-browser` and visit `http://127.0.0.1:8765` yourself |
| `Address already in use` | Pick another port: `--port 9000` |
| A file is missing from the Files pane | Check the extension is recognized (§4), the file is readable, and it's under the launch directory (hidden `.`-files are excluded) |
| A path is rejected (`403`) | The path is outside the launch directory; restart the GUI rooted higher up |
| Open fails with `is not a v2 manifest (no 'steps' key)` | Open reads v2 YAML/JSON only (§8). Rebuild the file with `ambermeta discover <dir> --write <path>` and open that |

---

## See also

- [Architecture §9](architecture.md#9-the-gui-bridge--one-engine-enforced) — how the GUI maps onto the core (`core_bridge`)
- [CLI reference](cli.md) — `discover`/`validate --manifest`/`export` are the headless equivalents of Discover/Validate/Export
- [Manifest schema](manifest.md) — the v2 format Open/Save read and write
