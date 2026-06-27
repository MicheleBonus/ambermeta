# GUI guide

**The AmberMeta GUI is a browser-based manifest editor over the same engine the CLI uses.** It runs a small local web server, opens a three-pane app in your browser, and lets you assemble, audit, and save a protocol manifest by clicking and dragging instead of hand-editing YAML. It is single-user, **localhost-only**, and works fully offline.

> When to use it: interactively building or sanity-checking a manifest, especially for a directory you're seeing for the first time. For scripting, CI, and cluster/SSH use, the [CLI](cli.md) is the complete headless equivalent — the GUI's **Save** writes the *same canonical manifest* `ambermeta init --auto` would.

---

## 1. Install & launch

The GUI needs the `gui` extra (FastAPI + Uvicorn); the frontend itself is pre-built and bundled, so there is no Node.js or build step.

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

The server (FastAPI + Uvicorn) binds the host/port, sets the launch directory as its containment root, and — unless `--no-browser` — opens `http://<host>:<port>` after a short delay.

> ⚠️ **The launch directory is a hard boundary.** The server will only read files inside `directory` (resolved through symlinks). Launch it at the top of the project you want to work with.

---

## 2. The window

```
┌────────────────────────────────────────────────────────────────────────────┐
│ AmberMeta   [Open] [Save]   [Discover] [Link Restarts]   [Export] [Validate] │
├──────────────────┬───────────────────────────────┬───────────────────────────┤
│                  │                               │                           │
│   FILES          │   STAGES                      │   PROPERTIES              │
│                  │                               │                           │
│   runs/          │   ┌─────────────────────────┐ │   Stage: ntp_prod_0001   │
│     system.top   │   │ ⠿ ntp_prod_0001   prod  │ │   ───────────────────    │
│     prod_0001.in │   │   4/5 files        ok   │ │   Name   [____________]  │
│     prod_0001.out│   └─────────────────────────┘ │   Role   [Production ▾]  │
│     prod_0002.in │   ┌─────────────────────────┐ │   prmtop (using global)  │
│     ...          │   │ ⠿ ntp_prod_0002   prod  │ │   mdin   prod_0001.in    │
│                  │   │   4/5 files        ok   │ │   mdout  prod_0001.out   │
│   [search…]      │   └─────────────────────────┘ │   Gap (ps) [__] ±[__]    │
│                  │            [+ Add stage]      │   Notes  [____________]  │
└──────────────────┴───────────────────────────────┴───────────────────────────┘
```

| Pane / control | Role |
|---|---|
| **Files** (left) | The directory tree, file-type-tagged, searchable. Drag files onto stage slots. |
| **Stages** (center) | Ordered stage cards. Drag the handle to reorder; click a card to select it. |
| **Properties** (right) | Edits for the selected stage, or global settings when none is selected. |
| **Open / Save** | Load an existing manifest / write the current one to disk. |
| **Discover** | Auto-group the directory into stages (one stage per file group). |
| **Link Restarts** | Auto-detect and assign the restart chain across stages. |
| **Export** | Preview the manifest in any format and save it. |
| **Validate** | Run full validation and show the report. |

The design is deliberately restrained: an off-white surface, a neutral sans-serif UI face with a monospace face for file paths and data, and color/icons used only where they carry meaning (file-type tags, validation state).

---

## 3. A typical session

1. **Discover.** Click **Discover** (optionally recursive, with a filename regex). The server scans the directory, groups files by stem into stages, detects numbered sequences, and classifies the topology (normal vs. HMR). One file group → one stage; numbered runs are kept separate, not collapsed.
2. **Assign & adjust.** Drag a file from **Files** onto a stage's slot, or open the file picker from **Properties**. Existing slots are preserved — a drop only fills the slot you target.
3. **Edit.** Select a stage and set its name, role, expected gap/tolerance, and notes. Set a shared topology once under global settings instead of per stage.
4. **Link restarts.** Click **Link Restarts** to chain `inpcrd` files across consecutive stages automatically.
5. **Validate.** Click **Validate**. The panel lists per-stage issues (missing files, continuity gaps) and a protocol-level summary, and lets you jump to each one. A protocol with continuity notes shows as *valid, with N notes* — never a silent clean pass.
6. **Save / Export.** **Save** writes the canonical manifest to disk; **Export** lets you preview and choose the format first.

Undo/redo and a dirty-state indicator live in the top bar; history is kept on the server.

---

## 4. Files pane

Files are tagged by type, detected from extension (and basename):

| Type | Extensions |
|---|---|
| `prmtop` | `.prmtop`, `.parm7`, `.top` |
| `mdin` | `.mdin`, `.in` |
| `mdout` | `.mdout`, `.out` |
| `mdcrd` | `.mdcrd`, `.nc`, `.crd`, `.x` |
| `inpcrd` | `.inpcrd`, `.rst`, `.rst7`, `.restrt`, `.ncrst` |

The tree descends up to five levels and skips noise (`.`-prefixed dirs, `__pycache__`, `node_modules`, `.git`). Use the search box to filter by name. Drag a file onto a stage slot to assign it.

---

## 5. Stages pane

Each stage is a card showing its name, role tag, file count (e.g. `4/5 files`), and validation state. Drag the handle to reorder; the order is the protocol order. **+ Add stage** creates an empty stage. Each stage exposes the five file slots (`prmtop`, `mdin`, `mdout`, `mdcrd`, `inpcrd`) as drop targets.

---

## 6. Properties pane

**With a stage selected**, you edit:

| Field | Notes |
|---|---|
| Name | Unique stage identifier |
| Role | `minimization` / `heating` / `equilibration` / `production` / _(unset)_ |
| File slots | Each of the five kinds; shows "(using global)" when inheriting the global topology |
| Expected gap / tolerance (ps) | Drives continuity validation |
| Notes | Free-text, one per line |

**With no stage selected**, the pane shows global settings:

| Setting | Default | Meaning |
|---|---|---|
| `global_prmtop` | _(none)_ | Shared topology for stages without their own |
| `hmr_prmtop` | _(none)_ | HMR topology (used when a stage's timestep warrants it) |
| `initial_coordinates` | _(none)_ | Starting coordinates for the first stage |
| `auto_link_restarts` | `true` | Link restarts on discover |
| `strict_validation` | `true` | Run cross-stage continuity checks |
| `allow_gaps` | `false` | Treat unconfigured positive gaps as info, not warnings |
| `use_relative_paths` | `true` | Write relative paths on save |

---

## 7. Validation

**Validate** builds a report against the same engine the CLI uses. Its shape:

```jsonc
{
  "ok": false,
  "totals": { "steps": 25000000, "time_ps": 100000.0, "stage_count": 7 },
  "protocol_issues": ["..."],
  "stage_issues": [
    {
      "name": "ntp_prod_0001",
      "ok": true,
      "degraded": false,
      "errors": [],
      "warnings": [],
      "info": ["INFO: Part of sequence 'ntp_prod' (item 2 of 6)"],
      "missing_files": [{ "kind": "mdcrd", "path": "" }]
    }
  ]
}
```

A non-empty `protocol_issues` means the protocol is *not* fully clean even when individual stages are `ok` — the panel reflects that rather than reporting a false all-clear.

---

## 8. Open, Save, Export

- **Open** loads any supported manifest (YAML / JSON / TOML / CSV) for editing and resets undo history.
- **Save** writes the current document as a **canonical manifest** — byte-identical to the CLI's output for the same protocol.
- **Export** previews the manifest in a chosen format before writing, so you can copy it or pick a format.

The on-disk manifest the GUI writes:

```yaml
global_prmtop: systems/complex.prmtop      # omitted if unset
hmr_prmtop: systems/complex_hmr.prmtop     # omitted if unset
stages:
  - name: prod_0001
    stage_role: production                  # omitted if unset
    mdin: production/prod_0001.in
    mdout: production/prod_0001.out
    inpcrd: restarts/equil.rst7
    gaps: { expected: 0.0, tolerance: 0.1 } # omitted if unset
    notes: [ "..." ]                        # omitted if empty
```

Toggle `use_relative_paths` in global settings to choose relative vs. absolute paths. Save/export warnings (for example, CSV cannot represent a separate HMR topology) are surfaced as toasts — they are never dropped silently.

---

## 9. Security model

The GUI is built to be safe to run on a workstation; it is not a multi-user service.

| Control | Mechanism |
|---|---|
| **Localhost only** | Binds `127.0.0.1` by default; CORS is pinned to `http://localhost:8765` / `http://127.0.0.1:8765`. |
| **No path escape** | Every requested path is resolved with `realpath` and rejected (`403`) if it falls outside the launch directory — including sibling-prefix tricks. |
| **API can't be spoofed by the SPA** | The catch-all route returns `404` for unknown `/api/*` paths and refuses `..`/absolute paths before serving the app shell. |
| **Server-authoritative state** | One in-memory document on the server is the source of truth; the browser is a view. Undo/redo and validation run server-side. |

> ⚠️ Binding `--host 0.0.0.0` exposes the file browser of the launch directory to your network. Only do so on a trusted network, and prefer an SSH tunnel for remote access.

---

## 10. HTTP API

The frontend talks to a small REST API under `/api`. You can drive it directly for scripting or testing. All paths are constrained to the launch directory; responses that mutate state return the full updated document.

### Document

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/api/document` | — | Current document |
| `POST` | `/api/document/open` | `{ path }` | Document (history reset) |
| `POST` | `/api/document/save` | `{ path?, format? }` | `{ document, warnings[] }` |
| `POST` | `/api/document/preview` | `{ format }` | `{ content, warnings[], format }` |
| `POST` | `/api/document/discover` | `{ recursive, pattern? }` | Document |

### Stages

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/stages` | `{ name, role?, files?, expected_gap_ps?, gap_tolerance_ps?, notes? }` | Document |
| `PUT` | `/api/stages/{id}` | partial stage | Document (`404` if unknown) |
| `DELETE` | `/api/stages/{id}` | — | Document (`404` if unknown) |
| `POST` | `/api/stages/reorder` | `{ stage_ids[] }` | Document (`400` unless all IDs present) |
| `PUT` | `/api/stages/bulk` | `{ stage_ids[], update }` | Document |

### Settings, history, validation, restarts

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` / `PUT` | `/api/settings` | _(GET)_ / partial settings | Settings / Document |
| `POST` | `/api/undo` · `/api/redo` | — | Document |
| `POST` | `/api/validate` | — | Validation report |
| `POST` | `/api/link-restarts` | — | Document |
| `GET` | `/api/sequences` | — | `{ sequence_base: [stage_id, ...] }` |

### Files

| Method | Path | Query | Returns |
|---|---|---|---|
| `GET` | `/api/files` | `path?`, `recursive?`, `include_all?` | File tree (`FileInfo[]`) |
| `GET` | `/api/files/metadata` | `path` | `{ file_path, file_type, metadata, warnings[] }` |
| `GET` | `/api/files/related/{stem}` | — | `{ kind: path, ... }` for same-stem files |

```bash
curl http://127.0.0.1:8765/api/document
curl -X POST http://127.0.0.1:8765/api/document/discover \
  -H 'Content-Type: application/json' -d '{"recursive": true}'
curl -X POST http://127.0.0.1:8765/api/validate
```

### Data models

The server's document and its persisted manifest:

```jsonc
// GET /api/document
{
  "base_directory": "...", "manifest_path": null,
  "dirty": false, "can_undo": false, "can_redo": false,
  "settings": { "global_prmtop": null, "hmr_prmtop": null, "initial_coordinates": null,
                "auto_link_restarts": true, "strict_validation": true,
                "allow_gaps": false, "use_relative_paths": true },
  "stages": [
    { "id": "a1b2c3d4", "name": "prod_0001", "role": "production",
      "prmtop": null, "mdin": "prod_0001.in", "mdout": "prod_0001.out",
      "mdcrd": null, "inpcrd": "equil.rst7",
      "expected_gap_ps": 0.0, "gap_tolerance_ps": 0.1, "notes": [] }
  ]
}
```

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `ImportError: fastapi` on launch | Install the GUI extra: `pip install -e ".[gui]"` |
| Browser didn't open | Use `--no-browser` and visit `http://127.0.0.1:8765` yourself |
| `Address already in use` | Pick another port: `--port 9000` |
| A file is missing from the tree | Check the extension is recognized (§4), the file is readable, and it's under the launch directory (hidden `.`-files are excluded) |
| A path is rejected (`403`) | The path is outside the launch directory; restart the GUI rooted higher up |

---

## See also

- [Architecture §9](architecture.md#9-the-gui-bridge--one-engine-enforced) — how the GUI maps onto the core
- [CLI reference](cli.md) — the headless equivalent of every GUI action
- [Manifest schema](manifest.md) — the format Open/Save read and write
