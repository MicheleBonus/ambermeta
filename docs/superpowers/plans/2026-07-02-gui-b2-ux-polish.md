# GUI B2 — UX Polish & Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the five reported B2 GUI complaints (overlapping stage rows, flat file tree, ambiguous same-name files, inert center pane, dead-looking drag) plus the impactful bonus bugs, in two review-gated milestones.

**Architecture:** Frontend-first changes to the existing React 18 + TypeScript + Vite + react-query + dnd-kit SPA in `ambermeta/gui/frontend`. Milestone 1 makes the current 3-pane design correct and legible; Milestone 2 makes the center card an inline editor. No architecture rewrite.

**Tech Stack:** React 18, TypeScript, Vite, Tailwind (design tokens in `tailwind.config.js`), @tanstack/react-query, @dnd-kit/core + /sortable, lucide-react. Tests: vitest + @testing-library/react + @testing-library/user-event + msw.

## Global Constraints

- Work in the worktree `C:\Users\Miche\Documents\GitHub\ambermeta-gui-b2` on branch `gui-ux-polish`.
- All frontend commands run from `ambermeta/gui/frontend`. Run tests with `npm run test` (vitest run); a single file with `npx vitest run src/<path>`. Type-check + build with `npm run build` (`tsc && vite build`).
- `vite build` writes to `../static` (the directory `ambermeta/gui/server.py` serves). The shipped bundle MUST be rebuilt at the end of each milestone or users see no change.
- Import alias: `@` → `ambermeta/gui/frontend/src`.
- Use existing design tokens only (`app`, `surface`, `hairline`, `ink`/`ink-secondary`/`ink-muted`, `accent`/`accent-subtle`, `valid`, `warning`, `error`). No new colors, no dark mode.
- `StageModel.role` is typed `string`; the editable role union is `StageRole = "minimization" | "heating" | "equilibration" | "production" | ""`.
- Keep `tsc` and the full vitest suite green after every task.
- Commit after every task. Do not push unless asked.

---

# Milestone 1 — Correct & legible

Resolves complaints #1, #3, #5, most of #2, and the bonus bugs. Ends with a working, testable, rebuilt GUI. **Review gate after Task 14 before starting Milestone 2.**

---

### Task 1: `fileLabel`, `relativizePath`, Title-case `roleLabel` (format helpers)

**Files:**
- Modify: `ambermeta/gui/frontend/src/lib/format.ts`
- Test: `ambermeta/gui/frontend/src/lib/format.test.ts`

**Interfaces:**
- Produces:
  - `relativizePath(path: string, base: string | null): string` — strips a leading `base` (with either `/` or `\` separators) and the following separator; returns `path` unchanged if not under `base`.
  - `fileLabel(input: string, base?: string | null): { folder: string; name: string; full: string }` — `name` is the basename **with extension**; `folder` is the base-relative parent (`""` at root); `full` is the original path. Splits on `/[\\/]/` (Windows-safe).
  - `roleLabel(role: string): string` — Title-case via `STAGE_ROLE_CONFIG`.

- [ ] **Step 1: Write the failing tests** — replace the existing `roleLabel` assertion and add new cases.

```ts
import { describe, it, expect } from "vitest";
import { formatPs, formatCount, roleLabel, fileLabel, relativizePath } from "./format";

describe("format helpers", () => {
  it("formats ps and null", () => {
    expect(formatPs(2)).toBe("2 ps");
    expect(formatPs(0.5)).toBe("0.5 ps");
    expect(formatPs(null)).toBe("—");
  });
  it("formats counts with thousands separators", () => {
    expect(formatCount(32000)).toBe("32,000");
    expect(formatCount(null)).toBe("—");
  });
  it("labels roles in Title Case, empty as Unknown", () => {
    expect(roleLabel("")).toBe("Unknown");
    expect(roleLabel("production")).toBe("Production");
    expect(roleLabel("equilibration")).toBe("Equilibration");
    expect(roleLabel("weird")).toBe("weird"); // unknown role passes through
  });
});

describe("relativizePath", () => {
  it("strips a posix base and separator", () => {
    expect(relativizePath("/work/equil/01_min.mdin", "/work")).toBe("equil/01_min.mdin");
  });
  it("strips a windows base and separator", () => {
    expect(relativizePath("C:\\work\\cryst\\a.pdb", "C:\\work")).toBe("cryst\\a.pdb");
  });
  it("returns the path unchanged when not under base", () => {
    expect(relativizePath("/other/x.mdin", "/work")).toBe("/other/x.mdin");
    expect(relativizePath("/work/x.mdin", null)).toBe("/work/x.mdin");
  });
});

describe("fileLabel", () => {
  it("keeps the extension and derives a base-relative folder", () => {
    expect(fileLabel("/work/equil/01_min.mdin", "/work"))
      .toEqual({ folder: "equil", name: "01_min.mdin", full: "/work/equil/01_min.mdin" });
  });
  it("empty folder at the base root", () => {
    expect(fileLabel("/work/system.prmtop", "/work"))
      .toEqual({ folder: "", name: "system.prmtop", full: "/work/system.prmtop" });
  });
  it("handles windows separators", () => {
    expect(fileLabel("C:\\work\\cryst\\m.crd", "C:\\work"))
      .toEqual({ folder: "cryst", name: "m.crd", full: "C:\\work\\cryst\\m.crd" });
  });
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/lib/format.test.ts`
Expected: FAIL (`fileLabel`/`relativizePath` not exported; `roleLabel("production")` returns `"production"`).

- [ ] **Step 3: Implement**

```ts
import { STAGE_ROLE_CONFIG } from "@/types";

export function formatPs(v: number | null): string {
  if (v === null) return "—";
  return `${v} ps`;
}

export function formatCount(n: number | null): string {
  if (n === null) return "—";
  return n.toLocaleString("en-US");
}

export function roleLabel(role: string): string {
  return STAGE_ROLE_CONFIG[role]?.label ?? (role || "Unknown");
}

function splitPath(p: string): string[] {
  return p.split(/[\\/]/);
}

export function relativizePath(path: string, base: string | null): string {
  if (!base) return path;
  const nb = base.replace(/[\\/]+$/, "");
  if (path === nb) return "";
  if (path.startsWith(nb + "/") || path.startsWith(nb + "\\")) {
    return path.slice(nb.length + 1);
  }
  return path;
}

export function fileLabel(
  input: string,
  base?: string | null
): { folder: string; name: string; full: string } {
  const rel = relativizePath(input, base ?? null);
  const parts = splitPath(rel);
  const name = parts.pop() ?? rel;
  return { folder: parts.join("/"), name, full: input };
}
```

- [ ] **Step 4: Run and confirm pass**

Run: `npx vitest run src/lib/format.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/lib/format.ts ambermeta/gui/frontend/src/lib/format.test.ts
git commit -m "feat(gui): fileLabel/relativizePath helpers + Title-case roleLabel"
```

---

### Task 2: `FileLabel` presentational component (shared, unambiguous rendering)

**Files:**
- Create: `ambermeta/gui/frontend/src/components/common/FileLabel.tsx`
- Modify: `ambermeta/gui/frontend/src/components/common/index.ts`
- Test: `ambermeta/gui/frontend/src/components/common/FileLabel.test.tsx`

**Interfaces:**
- Consumes: `fileLabel` (Task 1).
- Produces: `FileLabel({ path, base }: { path: string | null; base: string | null })` — renders the folder qualifier in a shrinkable, ellipsizing span and the basename+extension in a non-shrinking span (so the extension is never truncated away); `title` is the full path. Renders `—` for a null path.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FileLabel } from "./FileLabel";

describe("FileLabel", () => {
  it("shows folder qualifier + basename with extension and a full-path tooltip", () => {
    render(<FileLabel path="/work/equil/01_min.mdin" base="/work" />);
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
    expect(screen.getByText("equil/")).toBeInTheDocument();
    expect(screen.getByTitle("/work/equil/01_min.mdin")).toBeInTheDocument();
  });
  it("renders a dash for a null path", () => {
    render(<FileLabel path={null} base="/work" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/common/FileLabel.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement + export**

`FileLabel.tsx`:
```tsx
import { fileLabel } from "@/lib/format";

export function FileLabel({ path, base }: { path: string | null; base: string | null }) {
  if (!path) return <span className="text-ink-muted">—</span>;
  const { folder, name, full } = fileLabel(path, base);
  return (
    <span className="inline-flex min-w-0 items-baseline" title={full}>
      {folder && <span className="truncate text-ink-muted">{folder}/</span>}
      <span className="shrink-0 text-ink">{name}</span>
    </span>
  );
}
```

Add to `components/common/index.ts`:
```ts
export { FileLabel } from "./FileLabel";
```

- [ ] **Step 4: Run and confirm pass**

Run: `npx vitest run src/components/common/FileLabel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/common/FileLabel.tsx ambermeta/gui/frontend/src/components/common/FileLabel.test.tsx ambermeta/gui/frontend/src/components/common/index.ts
git commit -m "feat(gui): shared FileLabel component (folder qualifier + kept extension + tooltip)"
```

---

### Task 3: Shrink `FileIcon` to a sane default size

**Files:**
- Modify: `ambermeta/gui/frontend/src/components/common/Icons.tsx`
- Test: `ambermeta/gui/frontend/src/components/common/Icons.test.tsx`

**Interfaces:**
- Produces: `FileIcon` gains an optional `size?: number` prop (default `16`) passed to the lucide icon; existing `type`/`className`/`isOpen` unchanged.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { FileIcon } from "./Icons";

describe("FileIcon", () => {
  it("defaults to a 16px glyph (not lucide's 24)", () => {
    const { container } = render(<FileIcon type="mdin" />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("16");
  });
  it("honors an explicit size", () => {
    const { container } = render(<FileIcon type="folder" size={20} />);
    expect(container.querySelector("svg")?.getAttribute("width")).toBe("20");
  });
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/common/Icons.test.tsx`
Expected: FAIL (width is `24`; `size` prop not supported).

- [ ] **Step 3: Implement** — update `FileIconProps` and both return sites.

```tsx
interface FileIconProps {
  type: FileType;
  className?: string;
  isOpen?: boolean;
  size?: number;
}

export function FileIcon({ type, className = '', isOpen, size = 16 }: FileIconProps) {
  if (type === 'folder') {
    const Icon = isOpen ? FolderOpen : Folder;
    return <Icon size={size} className={`text-ink-muted ${className}`} />;
  }

  const Icon = FILE_TYPE_ICONS[type] || File;
  const colorClass = {
    prmtop: 'text-ink',
    mdin: 'text-ink',
    mdout: 'text-ink',
    mdcrd: 'text-ink',
    inpcrd: 'text-ink',
    other: 'text-ink-muted',
  }[type];

  return <Icon size={size} className={`${colorClass} ${className}`} />;
}
```

- [ ] **Step 4: Run and confirm pass**

Run: `npx vitest run src/components/common/Icons.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/common/Icons.tsx ambermeta/gui/frontend/src/components/common/Icons.test.tsx
git commit -m "fix(gui): FileIcon defaults to 16px (de-clunk chips/rows)"
```

---

### Task 4: Remove `StageList` virtualization (kills the row-overlap bug)

**Files:**
- Modify: `ambermeta/gui/frontend/src/components/StageList/StageList.tsx`
- Test: `ambermeta/gui/frontend/src/components/StageList/StageList.test.tsx`

**Rationale:** The virtualized path (`>50` rows) positions rows `absolute` at `index*64` with a constant estimate and no `measureElement`; real cards are taller, so rows overlap. Removing virtualization renders rows in normal document flow (cannot overlap) and un-breaks drag-reorder for long lists. Sequence grouping (already present) keeps the visible count modest.

**Interfaces:**
- Produces: `StageList` renders `rows.map(renderRow)` unconditionally; no `useVirtualizer`, no absolute positioning, no `VIRTUALIZE_THRESHOLD`.

- [ ] **Step 1: Add the failing regression test** (append to the existing `describe`).

```tsx
  it("renders every row past the old virtualization threshold (no windowing)", async () => {
    const stages = Array.from({ length: 60 }, (_, i) =>
      mkStage({ id: String(i), name: `s${i}`, role: "" }));
    server.use(
      http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, stages })),
      http.get("/api/sequences", () => HttpResponse.json({})),
    );
    renderList();
    await waitFor(() => expect(screen.getByText("s0")).toBeInTheDocument());
    // Row #58 would be outside a virtualized window (0-height jsdom scroller); require it present.
    expect(screen.getByText("s58")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/StageList/StageList.test.tsx`
Expected: FAIL (`s58` not rendered — virtualizer windows it out in jsdom).

- [ ] **Step 3: Implement** — rewrite `StageList.tsx` without virtualization.

```tsx
import { useMemo, useState } from "react";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { ChevronRight, ChevronDown } from "lucide-react";
import { useDocument, useSequences, useBulkUpdate } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { StageCard } from "./StageCard";
import { roleLabel } from "@/lib/format";
import type { StageModel, StageRole } from "@/types";

interface Group { base: string; ids: string[]; }
type Row = { type: "stage"; stage: StageModel } | { type: "group"; group: Group };
const ROLE_OPTIONS: StageRole[] = ["", "minimization", "heating", "equilibration", "production"];

export function StageList() {
  const { data: doc } = useDocument();
  const { data: sequences = {} } = useSequences();
  const bulk = useBulkUpdate();
  const { selectedIds, select } = useSelection();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const stages = doc?.stages ?? [];

  const groups: Group[] = useMemo(
    () => Object.entries(sequences)
      .filter(([, ids]) => ids.length >= 2)
      .map(([base, ids]) => ({ base, ids })),
    [sequences]
  );

  const rows: Row[] = useMemo(() => {
    const out: Row[] = [];
    const emittedGroup = new Set<string>();
    for (const s of stages) {
      const g = groups.find((gr) => gr.ids.includes(s.id));
      if (g) {
        if (!emittedGroup.has(g.base)) { out.push({ type: "group", group: g }); emittedGroup.add(g.base); }
        if (expanded[g.base]) out.push({ type: "stage", stage: s });
      } else {
        out.push({ type: "stage", stage: s });
      }
    }
    return out;
  }, [stages, groups, expanded]);

  const toggle = (base: string) => setExpanded((e) => ({ ...e, [base]: !e[base] }));

  function renderRow(row: Row) {
    if (row.type === "group") {
      return (
        <div key={`g:${row.group.base}`}
          className="flex items-center gap-2 px-3 py-1.5 bg-app border-b border-hairline text-sm">
          <button aria-label="toggle group" onClick={() => toggle(row.group.base)}
            className="flex items-center gap-1 font-medium">
            {expanded[row.group.base] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            {row.group.base} · {row.group.ids.length} runs
          </button>
          <span className="flex-1" />
          <select aria-label="group role"
            className="text-xs border border-hairline rounded bg-surface px-1 py-0.5"
            value=""
            onChange={(e) => {
              const v = e.target.value;
              if (v) bulk.mutate({ ids: row.group.ids, update: { role: v as StageRole } });
            }}>
            <option value="">set role…</option>
            {ROLE_OPTIONS.filter(Boolean).map((r) => (
              <option key={r} value={r}>{roleLabel(r)}</option>
            ))}
          </select>
        </div>
      );
    }
    return (
      <StageCard key={row.stage.id} stage={row.stage}
        index={stages.indexOf(row.stage)}
        isSelected={selectedIds.includes(row.stage.id)}
        onSelect={(e) => select(row.stage.id, { additive: e.ctrlKey || e.metaKey })} />
    );
  }

  return (
    <SortableContext items={stages.map((s) => s.id)} strategy={verticalListSortingStrategy}>
      <div className="h-full overflow-auto">
        {rows.length === 0 && (
          <p className="p-4 text-sm text-ink-muted">No stages. Use Discover or drag files in.</p>
        )}
        {rows.map((row) => renderRow(row))}
      </div>
    </SortableContext>
  );
}
```

- [ ] **Step 4: Run and confirm the whole file passes**

Run: `npx vitest run src/components/StageList/StageList.test.tsx`
Expected: PASS (new test + the two existing tests; the group role select now uses Title-case labels via `roleLabel`).

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/StageList/StageList.tsx ambermeta/gui/frontend/src/components/StageList/StageList.test.tsx
git commit -m "fix(gui): remove StageList virtualization (fixes stage-row overlap); controlled group role select"
```

---

### Task 5: Unambiguous chips in the center (`FileDropZone`)

**Files:**
- Modify: `ambermeta/gui/frontend/src/components/StageList/FileDropZone.tsx`
- Test: `ambermeta/gui/frontend/src/components/StageList/FileDropZone.test.tsx`

**Interfaces:**
- Consumes: `useDocument` (for `base_directory`), `FileLabel` (Task 2), `FileIcon` (Task 3).
- Produces: chip renders `<FileLabel>` (folder qualifier + kept extension + tooltip) instead of a tail-truncated raw path; keeps the droppable id `slot:<stageId>:<kind>`; caps its width.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { FileDropZone } from "./FileDropZone";

function renderZone(current: string | null) {
  queryClient.clear();
  server.use(http.get("/api/document", () =>
    HttpResponse.json({ ...emptyDocument, base_directory: "/work" })));
  return render(
    <QueryClientProvider client={queryClient}>
      <DndContext><FileDropZone stageId="1" kind="mdin" current={current} /></DndContext>
    </QueryClientProvider>
  );
}

describe("FileDropZone", () => {
  it("shows the kind label and a folder-qualified, extension-bearing filename", async () => {
    renderZone("/work/equil/01_min.mdin");
    expect(await screen.findByText("01_min.mdin")).toBeInTheDocument();
    expect(screen.getByText("equil/")).toBeInTheDocument();
    expect(screen.getByText("mdin")).toBeInTheDocument();
  });
  it("shows a dash when empty", async () => {
    renderZone(null);
    expect(await screen.findByText("—")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/StageList/FileDropZone.test.tsx`
Expected: FAIL (module renders raw path text, no `equil/` split).

- [ ] **Step 3: Implement**

```tsx
import { useDroppable } from "@dnd-kit/core";
import { FileIcon, FileLabel } from "@/components/common";
import { useDocument } from "@/api/hooks";
import type { FileType } from "@/types";

interface Props {
  stageId: string;
  kind: "prmtop" | "mdin" | "mdout" | "mdcrd" | "inpcrd";
  current: string | null;
}

const KIND_TYPE: Record<Props["kind"], FileType> = {
  prmtop: "prmtop", mdin: "mdin", mdout: "mdout", mdcrd: "mdcrd", inpcrd: "inpcrd",
};

export function FileDropZone({ stageId, kind, current }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: `slot:${stageId}:${kind}` });
  const { data: doc } = useDocument();
  return (
    <div ref={setNodeRef}
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-xs font-mono max-w-[16rem] min-w-0
        ${isOver ? "border-accent bg-accent-subtle" : "border-hairline"}`}>
      <FileIcon type={KIND_TYPE[kind]} size={14} />
      <span className="text-ink-muted shrink-0">{kind}</span>
      <span className="min-w-0 truncate">
        <FileLabel path={current} base={doc?.base_directory ?? null} />
      </span>
    </div>
  );
}
```

- [ ] **Step 4: Run and confirm pass**

Run: `npx vitest run src/components/StageList/FileDropZone.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/StageList/FileDropZone.tsx ambermeta/gui/frontend/src/components/StageList/FileDropZone.test.tsx
git commit -m "feat(gui): center chips show folder-qualified filename with extension + tooltip"
```

---

### Task 6: Unambiguous file rows in the right pane (`StageForm`)

**Files:**
- Modify: `ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.tsx`
- Test: `ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.test.tsx`

**Interfaces:**
- Consumes: `FileLabel` (Task 2), `useDocument` for `base_directory`.
- Produces: the per-kind file rows in `StageForm` render `<FileLabel>` (head-safe, tooltip) instead of `flex-1 truncate` raw path; Pick…/clear behavior unchanged.

- [ ] **Step 1: Add the failing test** — append to the existing `PropertiesPanel.test.tsx` describe (follow the file's existing render helper; it already mounts providers). Add:

```tsx
  it("renders assigned file paths folder-qualified with extension", async () => {
    // (uses the file's existing helper that selects a single stage with mdin set to
    //  "/work/equil/01_min.mdin" and base_directory "/work")
    expect(await screen.findByText("01_min.mdin")).toBeInTheDocument();
    expect(screen.getByText("equil/")).toBeInTheDocument();
  });
```

If the existing helper does not set an assigned file / base, extend that helper's msw `document` response so the selected stage has `mdin: "/work/equil/01_min.mdin"` and `base_directory: "/work"`, then keep the assertion above.

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/PropertiesPanel/PropertiesPanel.test.tsx`
Expected: FAIL (raw path shown, no `equil/` split).

- [ ] **Step 3: Implement** — in `PropertiesPanel.tsx`, import `FileLabel` and read the base. Change the file-row value span.

Add import: `import { Button, FileLabel } from "@/components/common";`
In `StageForm`, add near the top: `const { data: doc } = useDocument();` (import `useDocument` is already present in the file). Replace the value span inside the `FILE_KINDS.map(...)` row:

```tsx
            <span className="flex-1 min-w-0 truncate font-mono text-xs">
              <FileLabel path={stage[k]} base={doc?.base_directory ?? null} />
            </span>
```

- [ ] **Step 4: Run and confirm pass**

Run: `npx vitest run src/components/PropertiesPanel/PropertiesPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.tsx ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.test.tsx
git commit -m "feat(gui): right-pane file rows show folder-qualified filename with extension"
```

---

### Task 7: Real collapsible folder tree in `FileBrowser` (+ states + show-all)

**Files:**
- Modify: `ambermeta/gui/frontend/src/components/FileBrowser/FileBrowser.tsx`
- Test: `ambermeta/gui/frontend/src/components/FileBrowser/FileBrowser.test.tsx`

**Interfaces:**
- Consumes: `useFiles({ recursive, include_all })`, `useFileMetadata`, `useSelection`, `FileIcon`, `FileLabel`, `useDocument` (base).
- Produces: a recursive indented tree (folders with chevrons, files draggable via `file:<path>`), loading/empty/error states, a "Show all files" checkbox (drives `include_all`), and search that prunes to matches and their ancestor folders (auto-expanded).

- [ ] **Step 1: Write the failing tests** — replace `FileBrowser.test.tsx` with tree-aware tests (keep the metadata test).

```tsx
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { FileBrowser } from "./FileBrowser";

const tree = [
  { path: "/work/equil", name: "equil", file_type: "folder", is_directory: true,
    size: null, extension: null, parent: "/work", children: [
      { path: "/work/equil/01_min.mdin", name: "01_min.mdin", file_type: "mdin",
        is_directory: false, size: 50, extension: ".mdin", parent: "/work/equil", children: null },
    ] },
  { path: "/work/system.prmtop", name: "system.prmtop", file_type: "prmtop",
    is_directory: false, size: 100, extension: ".prmtop", parent: "/work", children: null },
];

function renderFB() {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, base_directory: "/work" })));
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider><DndContext><FileBrowser /></DndContext></SelectionProvider>
    </QueryClientProvider>
  );
}

describe("FileBrowser tree", () => {
  it("renders folders and their files, with a working collapse toggle", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    renderFB();
    await waitFor(() => expect(screen.getByText("equil")).toBeInTheDocument());
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument(); // top levels expanded by default
    await userEvent.click(screen.getByText("equil"));            // collapse
    expect(screen.queryByText("01_min.mdin")).not.toBeInTheDocument();
  });

  it("search prunes to matches and reveals their folder", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    renderFB();
    await waitFor(() => expect(screen.getByText("system.prmtop")).toBeInTheDocument());
    await userEvent.type(screen.getByPlaceholderText(/search/i), "01_min");
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
    expect(screen.getByText("equil")).toBeInTheDocument();          // ancestor kept
    expect(screen.queryByText("system.prmtop")).not.toBeInTheDocument();
  });

  it("shows an empty state when the folder has no recognized files", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json([])));
    renderFB();
    expect(await screen.findByText(/no files/i)).toBeInTheDocument();
  });

  it("shows metadata on selecting a file", async () => {
    server.use(
      http.get("/api/files", () => HttpResponse.json(tree)),
      http.get("/api/files/metadata", () => HttpResponse.json({
        file_path: "/work/system.prmtop", file_type: "prmtop",
        metadata: { details: { natom: 1234 }, warnings: [], kind: "prmtop" }, warnings: [],
      })),
    );
    renderFB();
    await userEvent.click(await screen.findByText("system.prmtop"));
    await waitFor(() => expect(screen.getByTestId("file-metadata")).toHaveTextContent("1234"));
  });
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/FileBrowser/FileBrowser.test.tsx`
Expected: FAIL (current flat list shows no `equil` folder row; no empty state).

- [ ] **Step 3: Implement** — rewrite `FileBrowser.tsx`.

```tsx
import { useMemo, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { useFiles, useFileMetadata } from "@/api/hooks";
import { useDocument } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { FileIcon, FileLabel, ChevronRight, ChevronDown } from "@/components/common";
import type { FileInfo } from "@/types";

// Prune the tree to files whose name matches q, keeping ancestor folders.
function filterTree(nodes: FileInfo[], q: string): FileInfo[] {
  if (!q) return nodes;
  const out: FileInfo[] = [];
  for (const n of nodes) {
    if (n.is_directory) {
      const kids = filterTree(n.children ?? [], q);
      if (kids.length) out.push({ ...n, children: kids });
    } else if (n.name.toLowerCase().includes(q)) {
      out.push(n);
    }
  }
  return out;
}

function FileRow({ file, base, depth }: { file: FileInfo; base: string | null; depth: number }) {
  const { attributes, listeners, setNodeRef } = useDraggable({ id: `file:${file.path}` });
  const { selectedFile, selectFile } = useSelection();
  const selected = selectedFile === file.path;
  return (
    <div ref={setNodeRef} {...listeners} {...attributes}
      onClick={() => selectFile(file.path)}
      style={{ paddingLeft: depth * 12 + 8 }}
      className={`flex items-center gap-2 w-full pr-2 py-1 text-sm rounded cursor-grab
        ${selected ? "bg-accent-subtle" : "hover:bg-app"}`}>
      <FileIcon type={file.file_type} size={14} />
      <span className="min-w-0 truncate"><FileLabel path={file.path} base={base} /></span>
    </div>
  );
}

function TreeNode({ node, base, depth, expanded, toggle, forceOpen }: {
  node: FileInfo; base: string | null; depth: number;
  expanded: Record<string, boolean>; toggle: (p: string) => void; forceOpen: boolean;
}) {
  if (!node.is_directory) return <FileRow file={node} base={base} depth={depth} />;
  const isOpen = forceOpen || expanded[node.path] || (expanded[node.path] === undefined && depth < 2);
  return (
    <div>
      <div onClick={() => toggle(node.path)} style={{ paddingLeft: depth * 12 }}
        className="flex items-center gap-1 py-1 text-sm cursor-pointer hover:bg-app rounded">
        {isOpen ? <ChevronDown size={14} className="text-ink-muted" />
                : <ChevronRight size={14} className="text-ink-muted" />}
        <FileIcon type="folder" size={14} isOpen={isOpen} />
        <span className="truncate">{node.name}</span>
      </div>
      {isOpen && node.children?.map((c) => (
        <TreeNode key={c.path} node={c} base={base} depth={depth + 1}
          expanded={expanded} toggle={toggle} forceOpen={forceOpen} />
      ))}
    </div>
  );
}

export function FileBrowser() {
  const [q, setQ] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const { data: tree = [], isPending, isError } = useFiles({ recursive: true, include_all: showAll });
  const { data: doc } = useDocument();
  const { selectedFile } = useSelection();
  const { data: meta, isPending: metaPending } = useFileMetadata(selectedFile);

  const query = q.toLowerCase();
  const shown = useMemo(() => filterTree(tree, query), [tree, query]);
  const toggle = (p: string) =>
    setExpanded((e) => ({ ...e, [p]: !(e[p] ?? true) })); // first click on a default-open folder collapses it

  return (
    <div className="flex flex-col h-full">
      <div className="p-2 border-b border-hairline space-y-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search files"
          className="w-full px-2 py-1 text-sm border border-hairline rounded bg-app" />
        <label className="flex items-center gap-2 text-xs text-ink-secondary">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
          Show all files
        </label>
      </div>
      <div className="flex-1 overflow-auto p-1">
        {isPending && <p className="p-2 text-xs text-ink-muted">Loading…</p>}
        {isError && <p className="p-2 text-xs text-error">Could not load files.</p>}
        {!isPending && !isError && shown.length === 0 && (
          <p className="p-2 text-xs text-ink-muted">No files found.</p>
        )}
        {shown.map((n) => (
          <TreeNode key={n.path} node={n} base={doc?.base_directory ?? null} depth={0}
            expanded={expanded} toggle={toggle} forceOpen={query.length > 0} />
        ))}
      </div>
      {selectedFile && (
        <div data-testid="file-metadata" className="border-t border-hairline p-2 text-xs font-mono">
          {metaPending && <span className="text-ink-muted">Reading…</span>}
          {meta?.metadata.details && (
            <dl className="grid grid-cols-2 gap-x-2 gap-y-0.5">
              {Object.entries(meta.metadata.details)
                .filter(([, v]) => v !== null && typeof v !== "object")
                .slice(0, 8)
                .map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-ink-muted">{k}</dt>
                    <dd className="text-ink truncate">{String(v)}</dd>
                  </div>
                ))}
            </dl>
          )}
          {meta?.metadata.warnings?.map((w, i) => (
            <p key={i} className="text-warning mt-1">{w}</p>
          ))}
        </div>
      )}
    </div>
  );
}
```

Note the `toggle` semantics: default-open (depth<2) folders use `expanded[p] ?? true`, so the first click collapses them; deeper folders default closed. This matches the collapse test.

- [ ] **Step 4: Run and confirm pass**

Run: `npx vitest run src/components/FileBrowser/FileBrowser.test.tsx`
Expected: PASS (all four tests).

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/FileBrowser/FileBrowser.tsx ambermeta/gui/frontend/src/components/FileBrowser/FileBrowser.test.tsx
git commit -m "feat(gui): FileBrowser renders a real collapsible folder tree + states + show-all"
```

---

### Task 8: Drag feels alive — whole-row drag source already done; add `DragOverlay`

**Files:**
- Modify: `ambermeta/gui/frontend/src/App.tsx`
- Test: `ambermeta/gui/frontend/src/App.test.tsx` (extend) — if brittle in jsdom, assert the overlay renders during a simulated drag via dnd-kit is hard; instead unit-test the overlay label helper. See Step 1.

**Interfaces:**
- Consumes: `fileLabel` (Task 1), `DragOverlay`, `DragStartEvent` from `@dnd-kit/core`, `useDocument`.
- Produces: a `<DragOverlay>` inside the app `DndContext` showing the dragged file's basename while dragging (`activeId` tracked via `onDragStart`).

Note: Task 7 already makes the whole left row the drag source (listeners on the row div). This task adds visible drag feedback.

- [ ] **Step 1: Write the failing test** — verify the overlay label derivation (pure, reliable in jsdom).

Create `ambermeta/gui/frontend/src/components/common/DragChip.tsx`:
```tsx
import { fileLabel } from "@/lib/format";
export function DragChip({ activeId, base }: { activeId: string | null; base: string | null }) {
  if (!activeId || !activeId.startsWith("file:")) return null;
  const { name } = fileLabel(activeId.slice("file:".length), base);
  return (
    <div className="px-2 py-1 rounded border border-accent bg-surface text-xs font-mono shadow">
      {name}
    </div>
  );
}
```
Test `ambermeta/gui/frontend/src/components/common/DragChip.test.tsx`:
```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DragChip } from "./DragChip";

describe("DragChip", () => {
  it("shows the dragged file's basename", () => {
    render(<DragChip activeId="file:/work/equil/01_min.mdin" base="/work" />);
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
  });
  it("renders nothing when not dragging a file", () => {
    const { container } = render(<DragChip activeId={null} base="/work" />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/common/DragChip.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** — add `DragChip` (above), export it from `components/common/index.ts` (`export { DragChip } from "./DragChip";`), then wire the overlay in `App.tsx`:
  - Add imports: `DragOverlay, DragStartEvent` to the `@dnd-kit/core` import; `import { DragChip } from "@/components/common";`.
  - Add state: `const [activeId, setActiveId] = useState<string | null>(null);`
  - On the `DndContext`: `onDragStart={(e: DragStartEvent) => setActiveId(String(e.active.id))}` and change `onDragEnd` to also `setActiveId(null)` at the top of `handleDragEnd`.
  - Before `</DndContext>` add: `<DragOverlay><DragChip activeId={activeId} base={doc?.base_directory ?? null} /></DragOverlay>`.

- [ ] **Step 4: Run and confirm pass + suite green**

Run: `npx vitest run src/components/common/DragChip.test.tsx` then `npm run test`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/common/DragChip.tsx ambermeta/gui/frontend/src/components/common/DragChip.test.tsx ambermeta/gui/frontend/src/components/common/index.ts ambermeta/gui/frontend/src/App.tsx
git commit -m "feat(gui): DragOverlay ghost for file drags (visible drag feedback)"
```

---

### Task 9: Drop on the empty center to create a stage

**Files:**
- Modify: `ambermeta/gui/frontend/src/components/StageList/reorder.ts`
- Modify: `ambermeta/gui/frontend/src/components/StageList/reorder.test.ts`
- Modify: `ambermeta/gui/frontend/src/components/StageList/StageList.tsx` (empty-state droppable)
- Modify: `ambermeta/gui/frontend/src/App.tsx` (handle create)

**Interfaces:**
- Produces: `resolveDrop` returns `{ type: "create"; path: string }` when a `file:` is dropped on the droppable id `new-stage`. `DropResult` union gains that variant.

- [ ] **Step 1: Write the failing test** — append to `reorder.test.ts`.

```ts
  it("resolves a file dropped on the empty canvas to a create", () => {
    expect(resolveDrop("file:/work/equil/01_min.mdin", "new-stage"))
      .toEqual({ type: "create", path: "/work/equil/01_min.mdin" });
  });
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/StageList/reorder.test.ts`
Expected: FAIL (returns `null`).

- [ ] **Step 3: Implement**
  - In `reorder.ts`, extend the union and add a branch **before** the reorder branch:
```ts
export type DropResult =
  | { type: "assign"; stageId: string; kind: string; path: string }
  | { type: "reorder"; activeId: string; overId: string }
  | { type: "create"; path: string };
```
```ts
  if (activeId.startsWith("file:") && overId === "new-stage") {
    return { type: "create", path: activeId.slice("file:".length) };
  }
```
  - In `StageList.tsx`, make the empty state a droppable. Import `useDroppable` from `@dnd-kit/core`; inside the component add `const { setNodeRef: emptyRef } = useDroppable({ id: "new-stage" });` and render the empty paragraph with `ref={emptyRef}`:
```tsx
        {rows.length === 0 && (
          <p ref={emptyRef} className="p-4 text-sm text-ink-muted border-2 border-dashed border-hairline m-2 rounded">
            No stages. Use Discover or drag a file here to create one.
          </p>
        )}
```
  - In `App.tsx` `handleDragEnd`, handle the new variant (add `useCreateStage` to the hooks import and call it):
```tsx
    if (drop.type === "assign") {
      updateStage.mutate({ id: drop.stageId, update: { files: { [drop.kind]: relativizePath(drop.path, doc?.base_directory ?? null) } } });
    } else if (drop.type === "create") {
      const { name } = fileLabel(drop.path, doc?.base_directory ?? null);
      createStage.mutate({ name: name.replace(/\.[^.]+$/, "") });
    } else {
      reorder.mutate(reorderIds((doc?.stages ?? []).map((s) => s.id), drop.activeId, drop.overId));
    }
```
(Imports for `relativizePath`/`fileLabel` and `useCreateStage` are added here; the `relativizePath` on assign also delivers Task 10 — keep it.)

- [ ] **Step 4: Run and confirm pass + suite green**

Run: `npx vitest run src/components/StageList/reorder.test.ts` then `npm run test`
Expected: PASS; suite green.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/StageList/reorder.ts ambermeta/gui/frontend/src/components/StageList/reorder.test.ts ambermeta/gui/frontend/src/components/StageList/StageList.tsx ambermeta/gui/frontend/src/App.tsx
git commit -m "feat(gui): drop a file on the empty canvas to create a stage; relativize assigned paths"
```

---

### Task 10: Normalize picked paths to base-relative (right pane)

**Files:**
- Modify: `ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.tsx`
- Test: `ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.test.tsx`

**Note:** Task 9 already relativizes drag-assign in `App.tsx`. This task relativizes the right-pane `FilePicker` pick so both assignment paths agree with discover's relative convention.

**Interfaces:**
- Consumes: `relativizePath` (Task 1), `useDocument` base.

- [ ] **Step 1: Write the failing test** — simulate picking a file and assert the committed path is relative. Extend `PropertiesPanel.test.tsx`: intercept the `PUT /api/stages/:id` body.

```tsx
  it("commits a base-relative path when a file is picked", async () => {
    let sentPath: unknown;
    server.use(
      http.get("/api/files", () => HttpResponse.json([
        { path: "/work/equil/02_nvt.mdin", name: "02_nvt.mdin", file_type: "mdin",
          is_directory: false, size: 1, extension: ".mdin", parent: "/work/equil", children: null },
      ])),
      http.put("/api/stages/:id", async ({ request }) => {
        const body = await request.json() as { files?: { mdin?: string } };
        sentPath = body.files?.mdin;
        return HttpResponse.json({ ...emptyDocument, base_directory: "/work" });
      }),
    );
    // (render with a single selected stage + base_directory "/work" via the file's helper)
    await userEvent.click(screen.getAllByText("Pick…")[1]); // mdin row
    await userEvent.click(await screen.findByText("02_nvt.mdin"));
    await waitFor(() => expect(sentPath).toBe("equil/02_nvt.mdin"));
  });
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/PropertiesPanel/PropertiesPanel.test.tsx`
Expected: FAIL (absolute `/work/equil/02_nvt.mdin` sent).

- [ ] **Step 3: Implement** — in `StageEditor`, relativize on pick. Import `relativizePath`; read `const { data: doc } = useDocument();` (already used in Task 6). Change the picker `onPick`:

```tsx
        onPick={({ path }) => {
          if (pickSlot) onCommit({ files: { [pickSlot]: relativizePath(path, doc?.base_directory ?? null) } });
          setPickSlot(null);
        }}
```

- [ ] **Step 4: Run and confirm pass**

Run: `npx vitest run src/components/PropertiesPanel/PropertiesPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.tsx ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.test.tsx
git commit -m "feat(gui): relativize picked file paths to the base directory"
```

---

### Task 11: Invalidate file & sequence caches on document mutations

**Files:**
- Modify: `ambermeta/gui/frontend/src/api/queryClient.ts`
- Modify: `ambermeta/gui/frontend/src/api/hooks.ts`
- Test: `ambermeta/gui/frontend/src/api/queryClient.test.ts` (create)

**Interfaces:**
- Produces: `setDocument(doc)` also invalidates `["sequences"]`; `useOpen`/`useDiscover` additionally invalidate `["files"]`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { queryClient, setDocument, DOCUMENT_KEY } from "./queryClient";
import { emptyDocument } from "@/test/server";

describe("setDocument cache coherence", () => {
  beforeEach(() => queryClient.clear());
  it("stores the document and invalidates the sequences query", () => {
    queryClient.setQueryData(["sequences"], { a: ["1", "2"] });
    setDocument({ ...emptyDocument });
    expect(queryClient.getQueryData(DOCUMENT_KEY)).toBeTruthy();
    expect(queryClient.getQueryState(["sequences"])?.isInvalidated).toBe(true);
  });
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/api/queryClient.test.ts`
Expected: FAIL (`isInvalidated` is `false`).

- [ ] **Step 3: Implement**
  - `queryClient.ts`:
```ts
export function setDocument(doc: DocumentResponse): void {
  queryClient.setQueryData(DOCUMENT_KEY, doc);
  queryClient.invalidateQueries({ queryKey: ["sequences"] });
}
```
  - `hooks.ts` — make open/discover also refresh the file tree:
```ts
export const useOpen = () =>
  useMutation({
    mutationFn: (path: string) => api.openDocument(path),
    onSuccess: (doc) => { setDocument(doc); queryClient.invalidateQueries({ queryKey: ["files"] }); },
  });
export const useDiscover = () =>
  useMutation({
    mutationFn: (a: { recursive: boolean; pattern?: string }) => api.discover(a),
    onSuccess: (doc) => { setDocument(doc); queryClient.invalidateQueries({ queryKey: ["files"] }); },
  });
```
(`queryClient` is already imported in `hooks.ts`.)

- [ ] **Step 4: Run and confirm pass + suite green**

Run: `npx vitest run src/api/queryClient.test.ts` then `npm run test`
Expected: PASS; suite green.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/api/queryClient.ts ambermeta/gui/frontend/src/api/hooks.ts ambermeta/gui/frontend/src/api/queryClient.test.ts
git commit -m "fix(gui): invalidate files/sequences caches on document mutations (no stale panes)"
```

---

### Task 12: Controlled bulk role select (Properties panel)

**Files:**
- Modify: `ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.tsx`
- Test: `ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.test.tsx`

**Note:** The single-stage Role select is already controlled; the group role select was fixed in Task 4. This task fixes the multi-select **bulk** role select (`defaultValue=""`, snaps back, can't re-apply) and Title-cases its options.

- [ ] **Step 1: Write the failing test** — select 2 stages, choose a role twice, assert both fire.

```tsx
  it("bulk role select is controlled and Title-cased, and re-applies", async () => {
    let calls = 0;
    server.use(http.put("/api/stages/bulk", () => { calls++; return HttpResponse.json(emptyDocument); }));
    // (render with two selected stages via the file's helper)
    const sel = screen.getByLabelText(/set role for all/i) as HTMLSelectElement;
    expect(screen.getByRole("option", { name: "Production" })).toBeInTheDocument();
    await userEvent.selectOptions(sel, "production");
    await userEvent.selectOptions(sel, "equilibration");
    await waitFor(() => expect(calls).toBe(2));
  });
```

If the file's helper lacks a two-stage render, add a `renderBulk()` helper that seeds `document` with two stages and pre-selects both (dispatch two `select` clicks on stage rows is out of scope here — instead render `PropertiesPanel` inside a `SelectionProvider` and select via the exposed UI, or seed selection by clicking two `StageCard`s in an `App`-level test). Keep this test in whichever harness the file already uses for multi-select.

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/PropertiesPanel/PropertiesPanel.test.tsx`
Expected: FAIL (label not `Production`; re-applying the same first value would not re-fire with `defaultValue`).

- [ ] **Step 3: Implement** — controlled value + Title-case + always-fire. Import `roleLabel`. Replace the bulk `<select>`:

```tsx
          <select className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app"
            aria-label="Set role for all"
            value=""
            onChange={(e) => {
              const v = e.target.value;
              if (v) bulk.mutate({ ids: selectedIds, update: { role: v as StageRole } });
            }}>
            <option value="">set role…</option>
            {ROLES.filter(Boolean).map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
          </select>
```
Add the accessible label text `Set role for all` (the existing `<span>` already reads "Set role for all" — ensure the `<select>` `aria-label` matches so the test's `getByLabelText` resolves).

- [ ] **Step 4: Run and confirm pass**

Run: `npx vitest run src/components/PropertiesPanel/PropertiesPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.tsx ambermeta/gui/frontend/src/components/PropertiesPanel/PropertiesPanel.test.tsx
git commit -m "fix(gui): controlled, Title-cased, re-appliable bulk role select"
```

---

### Task 13: Clamp persisted pane widths on load

**Files:**
- Modify: `ambermeta/gui/frontend/src/lib/usePersistentSize.ts`
- Modify: `ambermeta/gui/frontend/src/App.tsx`
- Test: `ambermeta/gui/frontend/src/lib/usePersistentSize.test.ts` (create)

**Interfaces:**
- Produces: `usePersistentSize(key, initial, opts?: { min?: number; max?: number })` clamps the value read from `localStorage` (and the initial) into `[min, max]`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { usePersistentSize } from "./usePersistentSize";

describe("usePersistentSize", () => {
  beforeEach(() => localStorage.clear());
  it("clamps a stale stored value into [min,max] on load", () => {
    localStorage.setItem("files-w", "5000");
    const { result } = renderHook(() => usePersistentSize("files-w", 280, { min: 200, max: 480 }));
    expect(result.current[0]).toBe(480);
  });
  it("keeps an in-range stored value", () => {
    localStorage.setItem("files-w", "300");
    const { result } = renderHook(() => usePersistentSize("files-w", 280, { min: 200, max: 480 }));
    expect(result.current[0]).toBe(300);
  });
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/lib/usePersistentSize.test.ts`
Expected: FAIL (returns 5000).

- [ ] **Step 3: Implement**

```ts
import { useCallback, useState } from "react";

export function usePersistentSize(
  key: string, initial: number, opts?: { min?: number; max?: number }
): [number, (n: number) => void] {
  const clamp = (n: number) =>
    Math.min(opts?.max ?? Infinity, Math.max(opts?.min ?? -Infinity, n));
  const [size, setSize] = useState<number>(() => {
    const raw = localStorage.getItem(key);
    const n = raw ? Number(raw) : NaN;
    return clamp(Number.isFinite(n) ? n : initial);
  });
  const set = useCallback((n: number) => {
    const c = clamp(n);
    setSize(c);
    localStorage.setItem(key, String(c));
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return [size, set];
}
```
Then in `App.tsx` pass the same bounds used by the handles:
```tsx
  const [filesW, setFilesW] = usePersistentSize("files-w", 280, { min: 200, max: 480 });
  const [propsW, setPropsW] = usePersistentSize("props-w", 340, { min: 260, max: 520 });
```

- [ ] **Step 4: Run and confirm pass + suite green**

Run: `npx vitest run src/lib/usePersistentSize.test.ts` then `npm run test`
Expected: PASS; suite green.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/lib/usePersistentSize.ts ambermeta/gui/frontend/src/App.tsx ambermeta/gui/frontend/src/lib/usePersistentSize.test.ts
git commit -m "fix(gui): clamp persisted pane widths so the center can't collapse"
```

---

### Task 14: Milestone 1 delivery — full suite, type-check, rebuild bundle, verify

**Files:**
- Modify: `ambermeta/gui/static/assets/*` (generated), `ambermeta/gui/static/index.html` (generated)

- [ ] **Step 1: Full test suite + type-check + build**

Run (from `ambermeta/gui/frontend`): `npm run test` then `npm run build`
Expected: all tests pass; `tsc` clean; `vite build` writes fresh `../static/assets/index-*.{js,css}` and `../static/index.html`.

- [ ] **Step 2: Manual smoke test** — launch the real app against a folder resembling the report (cryst/equil/prod with a long prod run).

Run: `ambermeta gui <path-to-a-test-dir>` and confirm in the browser:
- Stage rows never overlap, even with 60+ stages.
- Left pane shows folders you can collapse/expand; scrolling keeps folder context; "Show all files" reveals `.pdb`/scripts.
- Chips and right-pane show `folder/name.ext`; hovering shows the full path.
- Dragging a file shows a ghost and drops onto a slot; dropping on the empty canvas creates a stage.

- [ ] **Step 3: Commit the rebuilt bundle**

```bash
git add ambermeta/gui/static
git commit -m "build(gui): rebuild static bundle with M1 UX fixes"
```

- [ ] **Step 4: STOP — Milestone 1 review gate.** Report results to the user and get approval before Milestone 2.

---

# Milestone 2 — Center becomes an editor

Resolves complaint #4. UI-only (all mutations already exist). Begin only after the M1 review gate.

---

### Task 15: Interactive slot chips in the center (click to pick, × to clear)

**Files:**
- Modify: `ambermeta/gui/frontend/src/components/StageList/FileDropZone.tsx`
- Modify: `ambermeta/gui/frontend/src/components/StageList/StageCard.tsx`
- Test: `ambermeta/gui/frontend/src/components/StageList/FileDropZone.test.tsx`

**Interfaces:**
- Consumes: `useUpdateStage`, `relativizePath`, `FilePicker`.
- Produces: `FileDropZone` gains a click target that opens a kind-filtered `FilePicker` and a clear (`×`) button when a file is set; both call `updateStage`.

- [ ] **Step 1: Write the failing test** — clicking a chip opens a picker; clicking a listed file commits a relative path; the × clears.

```tsx
  it("clicking a chip opens a picker and assigns; × clears", async () => {
    let sent: unknown;
    queryClient.clear();
    server.use(
      http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, base_directory: "/work" })),
      http.get("/api/files", () => HttpResponse.json([
        { path: "/work/equil/03_npt.mdin", name: "03_npt.mdin", file_type: "mdin",
          is_directory: false, size: 1, extension: ".mdin", parent: "/work/equil", children: null },
      ])),
      http.put("/api/stages/:id", async ({ request }) => {
        sent = ((await request.json()) as { files?: { mdin?: string } }).files?.mdin;
        return HttpResponse.json({ ...emptyDocument });
      }),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <DndContext><FileDropZone stageId="1" kind="mdin" current={null} /></DndContext>
      </QueryClientProvider>
    );
    await userEvent.click(await screen.findByRole("button", { name: /assign mdin/i }));
    await userEvent.click(await screen.findByText("03_npt.mdin"));
    await waitFor(() => expect(sent).toBe("equil/03_npt.mdin"));
  });
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/StageList/FileDropZone.test.tsx`
Expected: FAIL (no assign button / picker).

- [ ] **Step 3: Implement** — make the chip a button that opens a `FilePicker` (reused modal) filtered to `kind`, and add a clear button. `FileDropZone` gains its own `useUpdateStage` + local `open` state.

```tsx
import { useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import { FileIcon, FileLabel } from "@/components/common";
import { FilePicker } from "@/components/FilePicker";
import { useDocument, useUpdateStage } from "@/api/hooks";
import { relativizePath } from "@/lib/format";
import type { FileType } from "@/types";

interface Props {
  stageId: string;
  kind: "prmtop" | "mdin" | "mdout" | "mdcrd" | "inpcrd";
  current: string | null;
}
const KIND_TYPE: Record<Props["kind"], FileType> = {
  prmtop: "prmtop", mdin: "mdin", mdout: "mdout", mdcrd: "mdcrd", inpcrd: "inpcrd",
};

export function FileDropZone({ stageId, kind, current }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: `slot:${stageId}:${kind}` });
  const { data: doc } = useDocument();
  const update = useUpdateStage();
  const [open, setOpen] = useState(false);
  const base = doc?.base_directory ?? null;
  const commit = (path: string | null) =>
    update.mutate({ id: stageId, update: { files: { [kind]: path === null ? "" : relativizePath(path, base) } } });
  return (
    <div ref={setNodeRef}
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-xs font-mono max-w-[16rem] min-w-0
        ${isOver ? "border-accent bg-accent-subtle" : "border-hairline"}`}>
      <FileIcon type={KIND_TYPE[kind]} size={14} />
      <button type="button" aria-label={`assign ${kind}`} onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        className="flex items-center gap-1 min-w-0">
        <span className="text-ink-muted shrink-0">{kind}</span>
        <span className="min-w-0 truncate"><FileLabel path={current} base={base} /></span>
      </button>
      {current && (
        <button type="button" aria-label={`clear ${kind}`} className="text-ink-muted shrink-0"
          onClick={(e) => { e.stopPropagation(); commit(null); }}>×</button>
      )}
      <FilePicker open={open} mode="open" title={`Pick ${kind} file`}
        onClose={() => setOpen(false)}
        onPick={({ path }) => { commit(path); setOpen(false); }} />
    </div>
  );
}
```
In `StageCard.tsx`, ensure the chip row does not trigger card selection: wrap the chip row `<div>` with `onClick={(e) => e.stopPropagation()}` (the card's `onClick={onSelect}` is on the outer div).

- [ ] **Step 4: Run and confirm pass + suite green**

Run: `npx vitest run src/components/StageList/FileDropZone.test.tsx` then `npm run test`
Expected: PASS; suite green.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/StageList/FileDropZone.tsx ambermeta/gui/frontend/src/components/StageList/StageCard.tsx ambermeta/gui/frontend/src/components/StageList/FileDropZone.test.tsx
git commit -m "feat(gui): center chips are click-to-pick / ×-to-clear editors"
```

---

### Task 16: Inline stage rename + role on the card

**Files:**
- Modify: `ambermeta/gui/frontend/src/components/StageList/StageCard.tsx`
- Test: `ambermeta/gui/frontend/src/components/StageList/StageCard.test.tsx` (create)

**Interfaces:**
- Consumes: `useUpdateStage`, `roleLabel`, `STAGE_ROLE_CONFIG`.
- Produces: double-clicking the name shows an inline `<input>` that commits on blur/Enter; the role Badge becomes an inline `<select>` committing on change.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { StageCard } from "./StageCard";
import type { StageModel } from "@/types";

const stage: StageModel = { id: "1", name: "min", role: "", prmtop: null, mdin: null,
  mdout: null, mdcrd: null, inpcrd: null, expected_gap_ps: null, gap_tolerance_ps: null, notes: [] };

function renderCard() {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json({ ...emptyDocument })));
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider><DndContext>
        <StageCard stage={stage} index={0} isSelected={false} onSelect={() => {}} />
      </DndContext></SelectionProvider>
    </QueryClientProvider>
  );
}

describe("StageCard inline edit", () => {
  it("renames on double-click + Enter", async () => {
    let sentName: unknown;
    server.use(http.put("/api/stages/:id", async ({ request }) =>
      { sentName = ((await request.json()) as { name?: string }).name; return HttpResponse.json(emptyDocument); }));
    renderCard();
    await userEvent.dblClick(screen.getByText("min"));
    const input = screen.getByDisplayValue("min");
    await userEvent.clear(input);
    await userEvent.type(input, "minim{Enter}");
    await waitFor(() => expect(sentName).toBe("minim"));
  });
  it("changes role via inline select", async () => {
    let sentRole: unknown;
    server.use(http.put("/api/stages/:id", async ({ request }) =>
      { sentRole = ((await request.json()) as { role?: string }).role; return HttpResponse.json(emptyDocument); }));
    renderCard();
    await userEvent.selectOptions(screen.getByLabelText(/stage role/i), "production");
    await waitFor(() => expect(sentRole).toBe("production"));
  });
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/StageList/StageCard.test.tsx`
Expected: FAIL (name is static; no role select).

- [ ] **Step 3: Implement** — add inline rename + role select to `StageCard.tsx`. Keep the drag listeners OFF the interactive controls (they move to a grip in Task 17; for now, stop propagation on the name input and select so clicks don't start a drag/select).

```tsx
import { useState } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { FileDropZone } from "./FileDropZone";
import { roleLabel, formatPs } from "@/lib/format";
import { useUpdateStage } from "@/api/hooks";
import { STAGE_ROLE_CONFIG } from "@/types";
import type { StageModel, StageRole } from "@/types";

const KINDS = ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"] as const;
const ROLE_OPTIONS: StageRole[] = ["", "minimization", "heating", "equilibration", "production"];

export function StageCard(
  { stage, index, isSelected, onSelect }:
  { stage: StageModel; index: number; isSelected: boolean; onSelect: (e: React.MouseEvent) => void }
) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: stage.id });
  const style = { transform: CSS.Transform.toString(transform), transition };
  const hasGap = stage.expected_gap_ps != null && stage.expected_gap_ps > 0;
  const update = useUpdateStage();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(stage.name);

  const commitName = () => {
    setEditing(false);
    if (name !== stage.name) update.mutate({ id: stage.id, update: { name } });
  };

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}
      onClick={onSelect}
      className={`border-b border-hairline px-3 py-2 cursor-pointer
        ${isSelected ? "bg-accent-subtle" : "hover:bg-app"}`}>
      <div className="flex items-center gap-2">
        <span className="text-xs text-ink-muted w-6 tabular-nums">{index + 1}</span>
        {editing ? (
          <input autoFocus aria-label="Rename stage" value={name}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setName(e.target.value)}
            onBlur={commitName}
            onKeyDown={(e) => { if (e.key === "Enter") commitName(); if (e.key === "Escape") { setName(stage.name); setEditing(false); } }}
            className="font-medium flex-1 min-w-0 px-1 border border-hairline rounded bg-app" />
        ) : (
          <span className="font-medium truncate flex-1"
            onDoubleClick={(e) => { e.stopPropagation(); setName(stage.name); setEditing(true); }}>
            {stage.name}
          </span>
        )}
        <select aria-label="stage role" value={stage.role}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => update.mutate({ id: stage.id, update: { role: e.target.value as StageRole } })}
          className="text-xs border border-hairline rounded bg-surface px-1 py-0.5">
          {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{STAGE_ROLE_CONFIG[r]?.label ?? roleLabel(r)}</option>)}
        </select>
        {hasGap && (
          <span className="text-warning text-xs">+{formatPs(stage.expected_gap_ps)} gap</span>
        )}
      </div>
      <div className="flex flex-wrap gap-1 mt-1 pl-8" onClick={(e) => e.stopPropagation()}>
        {KINDS.map((k) => (
          <FileDropZone key={k} stageId={stage.id} kind={k} current={stage[k]} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run and confirm pass + suite green**

Run: `npx vitest run src/components/StageList/StageCard.test.tsx` then `npm run test`
Expected: PASS; suite green.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/StageList/StageCard.tsx ambermeta/gui/frontend/src/components/StageList/StageCard.test.tsx
git commit -m "feat(gui): inline stage rename + inline role select on the card"
```

---

### Task 17: Dedicated grip handle so reorder stops fighting click-select

**Files:**
- Modify: `ambermeta/gui/frontend/src/components/StageList/StageCard.tsx`
- Test: `ambermeta/gui/frontend/src/components/StageList/StageCard.test.tsx`

**Interfaces:**
- Produces: `useSortable` `listeners`/`attributes` move from the whole card to a dedicated `GripVertical` handle; the card `onClick` still selects; the handle has an accessible name.

- [ ] **Step 1: Add the failing test** (append).

```tsx
  it("exposes a dedicated drag handle and keeps card click for select", async () => {
    let selected = false;
    queryClient.clear();
    server.use(http.get("/api/document", () => HttpResponse.json({ ...emptyDocument })));
    render(
      <QueryClientProvider client={queryClient}>
        <SelectionProvider><DndContext>
          <StageCard stage={stage} index={0} isSelected={false} onSelect={() => { selected = true; }} />
        </DndContext></SelectionProvider>
      </QueryClientProvider>
    );
    expect(screen.getByLabelText(/drag to reorder/i)).toBeInTheDocument();
    await userEvent.click(screen.getByText("min"));
    expect(selected).toBe(true);
  });
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run src/components/StageList/StageCard.test.tsx`
Expected: FAIL (no element labeled "drag to reorder").

- [ ] **Step 3: Implement** — remove `{...attributes} {...listeners}` from the outer card `<div>`; add a grip button as the first header child:

```tsx
import { GripVertical } from "@/components/common";
```
Outer div: keep `ref={setNodeRef} style={style} onClick={onSelect}` but drop the spread listeners/attributes. Add inside the header row, before the index span:
```tsx
        <button aria-label="drag to reorder" {...attributes} {...listeners}
          onClick={(e) => e.stopPropagation()}
          className="cursor-grab text-ink-muted shrink-0"><GripVertical size={14} /></button>
```

- [ ] **Step 4: Run and confirm pass + suite green**

Run: `npx vitest run src/components/StageList/StageCard.test.tsx` then `npm run test`
Expected: PASS; suite green.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/StageList/StageCard.tsx ambermeta/gui/frontend/src/components/StageList/StageCard.test.tsx
git commit -m "feat(gui): dedicated grip handle for stage reorder (no more select/drag conflict)"
```

---

### Task 18: Milestone 2 delivery — suite, type-check, rebuild bundle, verify

- [ ] **Step 1: Full test + type-check + build**

Run (from `ambermeta/gui/frontend`): `npm run test` then `npm run build`
Expected: all pass; `../static` regenerated.

- [ ] **Step 2: Manual smoke test** — `ambermeta gui <test-dir>`; confirm you can assign/replace/clear files, rename, and set role entirely from the center card; reorder via the grip without selecting.

- [ ] **Step 3: Commit the rebuilt bundle**

```bash
git add ambermeta/gui/static
git commit -m "build(gui): rebuild static bundle with M2 editable center"
```

- [ ] **Step 4: Finish the branch** — use superpowers:finishing-a-development-branch to choose merge/PR/cleanup.

---

## Self-Review

**Spec coverage:**
- Complaint #5 (overlap) → Task 4 (+ Task 3 icon size). ✓
- Complaint #1 (flat tree) → Task 7. ✓
- Complaint #3 (ambiguous names) → Tasks 1, 2, 5, 6 (+ Task 9/10 relativization). ✓
- Complaint #4 (inert center) → Tasks 15, 16, 17. ✓
- Complaint #2 (drag) → Task 7 (whole-row source), Task 8 (DragOverlay), Task 9 (empty-drop create). ✓
- Bonus bugs: icons (Task 3), abs/rel paths (Tasks 9, 10), cache invalidation (Task 11), role label case (Task 1), uncontrolled selects (Tasks 4, 12), FileBrowser load/error (Task 7), width clamp (Task 13). ✓
- Bundle rebuild (Tasks 14, 18). ✓

**Placeholder scan:** No TBD/TODO. Test bodies that depend on an existing file's render helper (Tasks 6, 10, 12) name the exact assertions and the msw handlers to add; the implementer wires them to that file's existing harness.

**Type consistency:** `fileLabel`/`relativizePath`/`roleLabel` signatures match across Tasks 1, 5, 6, 9, 10, 15. `DropResult` gains `create` in Task 9 and is consumed in the same task's `App.tsx` change. `FileIcon`'s `size` (Task 3) is used in Tasks 5, 7. `usePersistentSize` opts (Task 13) match the call sites.
