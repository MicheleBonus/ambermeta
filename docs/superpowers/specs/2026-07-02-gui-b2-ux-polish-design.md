# GUI B2 — UX Polish & Reliability (Files / Stages / Properties)

- **Date:** 2026-07-02
- **Branch:** `gui-ux-polish` (off `main`)
- **Status:** Approved (design); pending spec review → implementation plan
- **Scope:** Frontend-only, with small optional backend touch-ups. Targets the shipped **B2** GUI (`ambermeta/gui/frontend`), the version users actually run.

## 1. Context & problem

A user working with a real Amber campaign (`cryst/` inputs, `equil/` with 9 steps, `prod/` with ~51 restart segments) reported the B2 GUI is "clunky and unintuitive," with a screenshot showing five concrete problems. Investigation established that the reported GUI is the **B2 rewrite on `main`** (React 18 + TS + Vite + FastAPI, react-query document cache, single app-level `DndContext`), not the stale GUI on the original working branch.

Re-mapping B2 against the real code found that **most complaints are broken behaviour or discarded data, not missing features** — and surfaced a precisely-located rendering bug plus several smaller correctness issues. This spec fixes them in two milestones.

## 2. Goals / non-goals

**Goals**
- Eliminate the visible layout defect (overlapping stage rows).
- Make the left pane a real, browsable folder tree.
- Make file identity unambiguous everywhere (folder + extension always visible).
- Make the center pane editable, not just a selection surface.
- Improve drag discoverability and feedback.
- Fix the correctness bugs found during mapping (stale caches, absolute/relative path mixing, uncontrolled selects, missing load/error states).

**Non-goals**
- No architecture rewrite. Keep react-query + dnd-kit + the 3-pane layout.
- No in-app switching of the file-scan root directory (base dir is frozen at launch; see §9).
- No new science features (per-stage topology already exists via the right-pane picker; branching/DAG protocols are out of scope).
- No mobile/responsive layout work beyond not regressing desktop.

## 3. Current B2 architecture (as-is)

- **Layout:** `App.tsx` renders a fixed 3-pane workbench under `TopBar` (Open/Save/Discover/Re-link/Validate/Export + Undo/Redo + dirty dot). Panes: `FileBrowser` (left), `StageList` (center), `PropertiesPanel` (right), two `ResizeHandle`s, widths persisted via `lib/usePersistentSize.ts`.
- **State:** one react-query document cache (`DOCUMENT_KEY`); every mutation replaces the document wholesale (`api/hooks.ts`, no optimistic updates). Separate queries for the file tree, per-file metadata, and sequence groups (`useFiles`/`useFileMetadata`/`useSequences`) — **never invalidated on mutation.**
- **DnD:** single app-level `DndContext` in `App.tsx`; `handleDragEnd` → `reorder.ts:resolveDrop` maps draggable `file:<path>` onto droppable `slot:<stageId>:<kind>` and calls `updateStage`. Also drives stage reorder via `SortableContext`.
- **Backend:** FastAPI over the AmberMeta core; server-authoritative in-memory document with bounded undo/redo. `files.py:build_file_tree` returns a **nested** tree already carrying `children[]`, `parent`, and `extension`. Base directory frozen at launch (`server.py:set_base_directory`); no open/switch-folder endpoint.
- **Design tokens:** `tailwind.config.js` (light-mode only; no responsive breakpoints).

### What B2 already handles (do not rebuild)
- Persisted pane widths; "Open" (load saved manifest); Discover modal with recursive search + pattern; per-slot "Pick…" `FilePicker`; per-file metadata preview; design tokens; the **full drag→assign pipeline** (`App.tsx` `DndContext` → `resolveDrop` → `updateStage`).
- Backend already returns everything needed to render folders and disambiguate names (`children`/`parent`/`extension` on `FileInfo`) — the client discards it.
- Sequence grouping exists (`useSequences` + `StageList.tsx`): a base with ≥2 members collapses to one default-collapsed summary row.
- `include_all` is plumbed (`FilePicker` uses `useFiles({recursive:true,include_all:true})`; `client.ts` forwards it; `files.py` honours it).

## 4. Complaint verdict (code-grounded)

| # | Complaint | Status | Root cause (file) |
|---|-----------|--------|-------------------|
| 5 | Rows overlap ("wonky") | Still broken | `StageList.tsx`: virtualized path uses constant `estimateSize:()=>64` + `position:absolute; top:index*64` and **never calls `measureElement`** (`StageList.tsx:64,112–118`). Real `StageCard` is ~70–110px (padding + title + wrap-flex chip row with **default 24px** `FileIcon`s). Triggers when `rows.length > 50` (`VIRTUALIZE_THRESHOLD`, `StageList.tsx:14,65,68`). The user's ~61 stages (51 prod segments ungrouped) trip it, so every row overlaps the next. ≤50 rows use normal flow and do not overlap. |
| 1 | Left = flat dump | Still broken | `FileBrowser.flatten()` pushes only non-directory nodes and **discards every folder** (`FileBrowser.tsx:8–16`); render is a single flat `files.map` (`FileBrowser.tsx:54–59`). No folder rows → no context on scroll. Load/error rendered identically to empty (`FileBrowser.tsx:39`). Data is present in the nested tree; it's a rendering choice. |
| 3 | Same-name ambiguous / no extension | Still broken | Left renders bare `{file.name}` with no folder, no tooltip (`FileBrowser.tsx:31`); `extension`/`parent` fetched but read nowhere (`types/index.ts`). Chips (`FileDropZone.tsx:23`) and right-pane cell (`PropertiesPanel.tsx:112`) **tail-truncate**, ellipsizing the disambiguating filename+extension. No label helper in `format.ts`. |
| 4 | Center inert | Still broken | `StageCard` is display-only (`StageCard.tsx:22–29`); `FileDropZone` is drop-only, no click/pick/clear (`FileDropZone.tsx:17–25`). All edits live in the right-pane form. `GripVertical` imported but unused; whole card is both select target and reorder surface (`StageCard.tsx:18–19`), so select & drag compete on one pointer. |
| 2 | Can't drag into center | Partial | Drag→assign is fully wired. Broken affordances: listeners only on the tiny 24px icon while the filename is a select-only `<button>` (`FileBrowser.tsx:27,30`); **no `<DragOverlay>`** in the `DndContext` (`App.tsx:54`) so nothing follows the cursor; virtualized path breaks drops; empty `StageList` has no droppable (`StageList.tsx:106`). |

### Bonus bugs found (fix the impactful ones)
1. **`FileIcon` renders at lucide default 24px everywhere** (`Icons.tsx`; call sites pass no size) — clunky and directly amplifies the overlap (guarantees row > 64px). *(med)*
2. **Assigned paths stored absolute** (`App.tsx:32` uses `file.path`; `FilePicker.onPick` passes absolute; backend stores verbatim) while discover/load use base-relative — document mixes absolute+relative until save; long absolute paths get truncated. *(med)*
3. **File/sequence caches never invalidated on mutation** (`setDocument` writes only `DOCUMENT_KEY`; `useFiles`/`useSequences` keys untouched, `hooks.ts`) — stale left pane / groups after open/discover/save. *(med)*
4. **`roleLabel` returns the raw role** (`format.ts`), rendering lowercase `production`; `STAGE_ROLE_CONFIG` already has Title Case but is unused. *(low)*
5. **Role selects uncontrolled with `defaultValue=""`** (`PropertiesPanel.tsx:26`, `StageList.tsx:83`) — snap back after choosing; same role can't be re-applied. *(low)*
6. **`FileBrowser` ignores `isPending`/`isError`** (`FileBrowser.tsx:39`) — load & failure look like an empty folder. *(low)*
7. **Persisted pane widths not re-clamped on load** (`usePersistentSize.ts`) — a stale width can survive; with center `min-w-0 overflow-hidden` (`App.tsx:63`) the center can collapse toward 0, forcing chip wrap and worsening overlap. *(low)*

## 5. Design — Milestone 1: Correct & legible

Resolves #1, #3, #5, most of #2, and the bonus bugs. Each unit is independently testable.

### M1.1 — Kill the overlap (headline)
- **Remove the broken virtualized path** in `StageList.tsx`: render rows in normal document flow (`rows.map(renderRow)`), delete the `useVirtualizer`/absolute-positioning branch. Normal flow cannot overlap and un-breaks drag-reorder for long lists.
- Cap `FileIcon` size (default `size=14` in `Icons.tsx`, or pass explicitly) and bound chip max width so `StageCard` height is compact and predictable.
- **Make sequence grouping reliable** so long runs (e.g. 51 prod segments) collapse to one summary row, keeping the rendered list short. Verify `useSequences` groups the folder-qualified stem names the discover produces; fix if it fails to collapse.
- **Acceptance:** with 61+ stages, no row overlaps any other at any scroll position and any pane width; a 51-segment production run shows as one collapsed group by default; drag-reorder works across the whole list.
- **Rationale for removing (vs `measureElement`):** simplest, cannot regress, and fixes virtualized-DnD for free. Grouping is the scalability mechanism. If a real protocol ever renders many hundreds of *ungrouped* rows and lags, re-introduce virtualization correctly (`measureElement` + `DragOverlay`) as a follow-up.

### M1.2 — Unambiguous file identity (`fileLabel` helper)
- Add `fileLabel(pathOrFile, { base })` to `lib/format.ts`: returns a structured label — **basename (strong) + dimmed folder qualifier** relative to `base`, **always including the extension**. Split on `/[\\/]/` (Windows-safe). Include a `title` (full path) for tooltips.
- **Head-truncate** long paths (ellipsize leading folders; keep filename+extension visible) — replace tail `truncate` in `FileDropZone.tsx:23` and `PropertiesPanel.tsx:112`.
- Use `fileLabel` + `title={path}` in: left-pane rows (`FileBrowser`), slot chips (`FileDropZone`), right-pane cells (`PropertiesPanel`), and `FilePicker` rows.
- **Normalize assigned paths to base-relative on assign** (frontend before `updateStage`, or backend `_files_patch`) so display is consistent and matches the manifest. (Addresses bonus bug #2.)
- **Acceptance:** two identically-named files in different folders are always visually distinguishable; extensions are never hidden by truncation; hovering any file reference shows its full path.

### M1.3 — Real folder tree (left pane)
- Replace the flat `flatten()`+`map` with a recursive **indented tree** consuming `FileInfo.children`/`parent`: expand/collapse chevrons, indentation per depth. (Indented tree chosen over sticky headers — matches the user's request to "browse folders and collapse/uncollapse them.")
- Persist expansion state (survives re-render and reload).
- Search auto-expands ancestors of matches (folder context preserved while filtering).
- Add loading / empty / error states (consume `isPending`/`isError`). (Addresses bonus bug #6.)
- Add a **"Show all files" toggle** (default: recognized only) using the existing `include_all` param, so `.pdb`/job-scripts become visible and draggable.
- **Acceptance:** folders render with working collapse; scrolling deep into a folder keeps its header/context reachable; search reveals deep matches; loading and error are visually distinct from empty; toggling "show all" surfaces `.pdb`/extensionless files.

### M1.4 — Drag that feels alive
- Move dnd listeners so the **whole left row** is the drag source (keep click-to-select via a grip or pointer discrimination).
- Add a `<DragOverlay>` to the `DndContext` showing the dragged file's `fileLabel` (visible feedback).
- Enlarge slot chips and strengthen the `isOver` highlight.
- Add a **center empty-state droppable** that creates a new stage from a dropped file.
- **Acceptance:** grabbing anywhere on a left row starts a drag with a visible ghost; dropping on a slot assigns; dropping on the empty center creates a stage.

### M1.5 — Polish & correctness
- `roleLabel` → Title Case via `STAGE_ROLE_CONFIG`; render Title-Case options in role dropdowns. (Bonus #4.)
- Make role selects **controlled** (reflect state; re-applicable). (Bonus #5.)
- **Invalidate `useFiles`/`useSequences`** after open/discover/save mutations. (Bonus #3.)
- Re-clamp persisted pane widths against handle min/max on load; give center a real min-width so it can't collapse. (Bonus #7.)

## 6. Design — Milestone 2: Center becomes an editor

Resolves #4. UI-only (mutations already exist). Reviewed after M1 ships.
- **Interactive slot chips:** click a chip → open `FilePicker` filtered to that slot's kind; hover-× → clear the slot (`updateStage`).
- **Inline stage rename** (double-click the name) and **inline role select** on the card.
- **Dedicated `GripVertical` drag handle** for reorder, so it no longer competes with click-select.
- Right pane retained for advanced/bulk/settings fields (gap/tolerance, notes, global settings, bulk edit).
- **Acceptance:** a user can assign/replace/clear files, rename, and set role entirely from the center card without touching the right pane; reordering via the grip never triggers selection.

## 7. Shared unit: `fileLabel` (interface)
- **Input:** a `FileInfo` or a path string, plus `{ base }` (the document base directory).
- **Output:** `{ name, folder, ext, full }` where `name` includes the extension, `folder` is the base-relative parent (or `""` at root), `ext` is the raw extension, `full` is the absolute/normalized path for tooltips.
- **Behaviour:** Windows-safe path splitting; empty `folder` when the file is at the base; never drops the extension.
- **Consumers:** `FileBrowser`, `FileDropZone`, `PropertiesPanel`, `FilePicker`. One source of truth for display labels.

## 8. Testing & delivery
- B2 ships a **vitest + msw** suite (~12 test files incl. `FileBrowser.test`, `StageList.test`, `PropertiesPanel.test`, `FilePicker.test`, `format.test`, `App.workflows.test`). Work **test-first**: add/extend tests per unit, then implement.
- Add regression tests specifically for: no-overlap at >50 stages, `fileLabel` disambiguation + Windows paths + extension retention, folder-tree collapse/expand, cache invalidation after mutation, controlled role selects.
- **Rebuild the production bundle** (`ambermeta/gui/static/assets/*`) as the final step — the shipped bundle is what `ambermeta gui` serves; without a rebuild none of this is visible. Verify by launching `ambermeta gui <dir>` against a folder resembling the user's layout.
- Keep `tsc`/lint green.

## 9. Risks & open questions (resolved defaults)
- **Removing virtualization** assumes grouping keeps rendered rows modest. Mitigation: fix grouping reliability in M1.1; document the follow-up path (`measureElement`) if huge ungrouped lists appear. *(default: remove virtualization)*
- **"Show all files"** default = recognized-only (avoids clutter); user can opt in. *(default chosen)*
- **Path normalization** on assign = base-relative immediately. *(default chosen)*
- **Same-folder stem collision** (e.g. `prod.rst` and `prod.rst7` both → `inpcrd`): out of scope to fully resolve; surfacing the extension via `fileLabel` at least makes the collision visible. Flag if a warning is wanted later.
- **In-app folder switching** (repoint the scan root): out of scope (needs a backend endpoint + path-guard relaxation). Flag if wanted.

## 10. File touch-list (anticipated)
- `ambermeta/gui/frontend/src/components/StageList/StageList.tsx` (M1.1)
- `ambermeta/gui/frontend/src/components/StageList/StageCard.tsx` (M1.1, M2)
- `ambermeta/gui/frontend/src/components/StageList/FileDropZone.tsx` (M1.1/2/3, M2)
- `ambermeta/gui/frontend/src/components/common/Icons.tsx` (M1.1)
- `ambermeta/gui/frontend/src/lib/format.ts` (M1.2, M1.5)
- `ambermeta/gui/frontend/src/components/FileBrowser/FileBrowser.tsx` (M1.2/3/4)
- `ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.tsx` (M1.2/5)
- `ambermeta/gui/frontend/src/components/FilePicker/FilePicker.tsx` (M1.2)
- `ambermeta/gui/frontend/src/App.tsx` (M1.4, M1.5)
- `ambermeta/gui/frontend/src/api/hooks.ts` (M1.5)
- `ambermeta/gui/frontend/src/lib/usePersistentSize.ts` (M1.5)
- `ambermeta/gui/frontend/src/types/index.ts` (as needed)
- Backend (optional): `ambermeta/gui/api/routes.py` / `files.py` (path relativization, grouping)
- `ambermeta/gui/static/assets/*` (rebuild)
