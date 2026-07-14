# P3 — GUI Frontend (Simulation model) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the React GUI against the new P2 `Simulation → Phase → Step` API — the mocked-up UX: a continuous-timeline canvas with continuity arrows, a file panel with data-driven assign actions, a full-detail inspector, and a draft-first suggestions tray.

**Architecture:** Server-authoritative, single react-query `["document"]` cache + mutation funnel (every mutation returns the whole `DocumentResponse`, written to the one cache key). No client-side document/undo state — undo/redo are server endpoints. UI-only state (selection, collapsed bands) is local React state. ONE app-level dnd-kit `DndContext` whose `onDragEnd` routes through a pure `resolveDrop` reducer to the right endpoint call. The v1 data-layer/tokens/harness/`common`+`lib` primitives are reused; the v1 feature components (FileBrowser/StageList/PropertiesPanel) are replaced.

**Tech Stack:** React 18 + TypeScript + Vite + Tailwind + @tanstack/react-query 5 + @dnd-kit + @tanstack/react-virtual + lucide-react; Vitest + @testing-library + MSW 2 (jsdom). All already in `package.json` — **no new dependencies**.

## Global Constraints

- **Offline / no-CDN:** bundled `@fontsource` fonts only; no network fonts/assets (unchanged from v1).
- **Single `["document"]` cache + mutation funnel; server-authoritative:** every doc-returning mutation goes through `setDocument(doc)` (from `api/queryClient.ts`, reused). NO client-side document or undo/redo state — `useUndo`/`useRedo` call the server. Selection and collapsed-band state are local React state only.
- **Match the v1 design tokens** (Tailwind theme in `tailwind.config`): surfaces `bg-app`/`bg-surface`, text `text-ink`/`text-ink-muted`, borders `border-hairline`, `accent` for functional highlights; `font-sans` (Inter) for UI, `font-mono` (JetBrains Mono) for data/paths. Color/icons only where functional. Reuse `components/common` (`Button`, `Badge`, `Modal`, `Icons`, `ResizeHandle`, `Toaster`) and `lib` (`usePersistentSize`, `useUnsavedGuard`, `toast`).
- **Canonical role tokens come from the API** (`"minimization"|"heating"|"equilibration"|"production"|""`); never invent role strings client-side.
- **Tests:** Vitest + the MSW harness (`src/test/setup.ts`, `src/test/server.ts`); every mocked endpoint returns the real response shape. `onUnhandledRequest: "error"` — mock every endpoint a test hits.
- **Branch:** `phase-step-redesign`.
- **Every task ends green:** `npm test` (Vitest) passes AND `npx tsc --noEmit` is clean. The final task additionally runs `npm run build` (`tsc && vite build`) successfully.
- Reference `docs/superpowers/plans/2026-06-27-gui-b2-frontend.md` for the established v1 patterns (funnel, DndContext, tokens, harness) — follow them, don't reinvent.

---

## File Structure

**Rewrite (data layer):**
- `src/types/index.ts` — TS types mirroring the new Python schemas (A1).
- `src/api/client.ts` — one method per new endpoint (A2).
- `src/api/hooks.ts` — react-query wrappers funnelling through `setDocument` (A3).
- `src/test/server.ts` — MSW `emptyDocument` in the new shape + default handlers (A3).
- `src/state/selection.tsx` — selection context for the new model (file | step | phase | sim) (A4).
- `src/App.tsx` — shell: 3 panes + one `DndContext` + `resolveDrop` wiring (A4, C3).

**Create (features):**
- `src/components/FilePanel/FilePanel.tsx` (+ `DraggableFile`) (B1).
- `src/components/Inspector/Inspector.tsx`, `FilePeek.tsx`, `FileDetails.tsx`, `AssignActions.tsx`, `StepEditor.tsx` (B2, B3).
- `src/components/Canvas/Canvas.tsx`, `SimHeader.tsx`, `PhaseSection.tsx`, `StepNode.tsx`, `ContinuityArrow.tsx` (C1, C2).
- `src/components/Canvas/resolveDrop.ts` (+ `resolveDrop.test.ts`) — pure drop router (C3).
- `src/components/Suggestions/SuggestionsTray.tsx` (D1).
- `src/components/TopBar/TopBar.tsx`, `DiscoverModal.tsx`, `ExportModal.tsx`, `ValidationPanel.tsx` (rebuilt for new hooks) (D2).

**Reuse unchanged:** `src/api/queryClient.ts`, `src/lib/*`, `src/components/common/*`, `src/components/FilePicker/*`, `src/main.tsx`, `src/index.css`, `tailwind.config.*`, `vite.config.*`.

**Delete (replaced):** `src/components/FileBrowser/*`, `src/components/StageList/*`, `src/components/PropertiesPanel/*`, and the old `src/App.test.tsx` / `src/App.workflows.test.tsx` (their flat-model assertions) — each removed in the task that replaces it.

---

## Group A — Foundation (data layer + shell)

### Task A1: TS types mirror the new schemas

**Files:** Rewrite `src/types/index.ts`; Test `src/types/types.test.ts`.

**Interfaces:** Produces `TopologyKind`, `StageRole`, `TopologyModel`, `InputCoordsModel`, `StepModel`, `PhaseModel`, `SimulationModel`, `RuntimeSettings`, `DocumentResponse`, `Suggestion`, `StageIssue`, `ValidationReport`, `DiscoverResult`, `FileInfo`, `FileMetadata`, `RawFile`, `ExportFormat`, and request bodies `AddTopology`/`UpdateTopology`/`SetStartingStructure`/`PhaseCreate`/`PhaseUpdate`/`StepCreatePayload`/`StepUpdatePayload`/`StepMovePayload`/`AssignRequest`.

- [ ] **Step 1: Write the failing test**
```ts
// src/types/types.test.ts
import { describe, it, expect } from "vitest";
import type { DocumentResponse, SimulationModel, AssignRequest } from "@/types";

it("document response nests a simulation", () => {
  const doc: DocumentResponse = {
    base_directory: "/w", manifest_path: null, dirty: false, can_undo: false, can_redo: false,
    settings: { auto_link_restarts: true, strict_validation: true, allow_gaps: false, use_relative_paths: true },
    simulation: { version: 2, topologies: [], starting_structure: null, phases: [] },
  };
  expect(doc.simulation.version).toBe(2);
  const sim: SimulationModel = doc.simulation;
  expect(sim.phases).toEqual([]);
  const a: AssignRequest = { path: "wt.prmtop", target_type: "pool", kind: "normal" };
  expect(a.target_type).toBe("pool");
});
```

- [ ] **Step 2: Run → RED**

Run: `npx vitest run src/types/types.test.ts`
Expected: FAIL (module has no such exports / `@/types` old shape).

- [ ] **Step 3: Rewrite `src/types/index.ts`**
```ts
export type TopologyKind = "normal" | "hmr";
export type StageRole = "minimization" | "heating" | "equilibration" | "production" | "";
export type ExportFormat = "yaml" | "json";

export interface TopologyModel { id: string; path: string; kind: TopologyKind; }
export interface InputCoordsModel { source: "starting_structure" | "step" | "path"; ref: string | null; path: string | null; }
export interface StepModel {
  id: string; name: string; topology: string | null; input_coords: InputCoordsModel;
  mdin: string | null; mdout: string | null; mdcrd: string | null;
  expected_gap_ps: number | null; gap_tolerance_ps: number | null; notes: string[];
}
export interface PhaseModel { id: string; name: string; role: StageRole; steps: StepModel[]; }
export interface SimulationModel {
  version: number; topologies: TopologyModel[]; starting_structure: string | null; phases: PhaseModel[];
}
export interface RuntimeSettings {
  auto_link_restarts: boolean; strict_validation: boolean; allow_gaps: boolean; use_relative_paths: boolean;
}
export interface DocumentResponse {
  base_directory: string; manifest_path: string | null; dirty: boolean;
  can_undo: boolean; can_redo: boolean; settings: RuntimeSettings; simulation: SimulationModel;
}
export interface Suggestion {
  id: string; kind: string; severity: "needs_you" | "applied" | "info";
  title: string; evidence: string; actions: string[];
}
export interface MissingFile { kind: string; path: string; }
export interface StageIssue {
  name: string; ok: boolean; degraded: boolean;
  errors: string[]; warnings: string[]; info: string[]; missing_files: MissingFile[];
}
export interface ValidationReport {
  ok: boolean; totals: Record<string, number>; protocol_issues: string[];
  stage_issues: StageIssue[]; suggestions: Suggestion[];
}
export interface DiscoverResult { document: DocumentResponse; suggestions: Suggestion[]; warnings: string[]; }

export type FileType = "prmtop" | "mdin" | "mdout" | "mdcrd" | "inpcrd" | "folder" | "other";
export interface FileInfo {
  path: string; name: string; file_type: FileType; is_directory: boolean;
  size: number | null; extension: string | null; parent: string | null; children: FileInfo[] | null;
}
export interface FileMetadata { file_path: string; file_type: FileType; metadata: Record<string, unknown>; warnings: string[]; }
export interface RawFile { path: string; content: string; truncated: boolean; }

// --- request bodies ---
export interface AddTopology { path: string; kind: TopologyKind; }
export interface UpdateTopology { path?: string; kind?: TopologyKind; }
export interface SetStartingStructure { path: string | null; }
export interface PhaseCreate { name: string; role: StageRole; }
export interface PhaseUpdate { name?: string; role?: StageRole; }
export interface StepFilesPatch { mdin?: string; mdout?: string; mdcrd?: string; }
export interface StepCreatePayload {
  name: string; topology?: string | null; input_coords?: InputCoordsModel;
  mdin?: string; mdout?: string; mdcrd?: string;
  expected_gap_ps?: number; gap_tolerance_ps?: number; notes?: string[];
}
export interface StepUpdatePayload {
  name?: string; topology?: string | null; input_coords?: InputCoordsModel; files?: StepFilesPatch;
  expected_gap_ps?: number; gap_tolerance_ps?: number; notes?: string[];
}
export interface StepMovePayload { phase_id: string; index: number; }
export type AssignTarget = "pool" | "starting_structure" | "phase_topology" | "step_topology" | "step_slot";
export interface AssignRequest {
  path: string; target_type: AssignTarget; target_id?: string; kind?: TopologyKind; slot?: "mdin" | "mdout" | "mdcrd";
}
```

- [ ] **Step 4: Run → GREEN**

Run: `npx vitest run src/types/types.test.ts && npx tsc --noEmit`
Expected: PASS + clean (tsc will show errors in `client.ts`/`hooks.ts`/old components that reference removed types — those are rewritten/deleted in A2–A4; if tsc is not clean yet, that is expected and resolved by end of A4. Run tsc green only after A4).

> **Note on tsc during A1–A3:** rewriting the data layer transiently breaks the old components' imports. Each of A2/A3 keeps its OWN test green; the FULL `tsc --noEmit` + `npm test` green gate is satisfied at the end of **A4** (which deletes the old components). State this in each commit. (This is the one unavoidable transitional window — it is contained to Group A and closed by A4.)

- [ ] **Step 5: Commit**
```bash
git add src/types/index.ts src/types/types.test.ts
git commit -m "feat(gui): TS types for the Simulation->Phase->Step API"
```

### Task A2: API client — one method per new endpoint

**Files:** Rewrite `src/api/client.ts`; Test `src/api/client.test.ts`.

**Interfaces:** Consumes A1 types. Produces `api` with: `getDocument, openDocument, saveDocument, previewDocument, discover, validate, undo, redo, getSettings, updateSettings, addTopology, updateTopology, removeTopology, setStartingStructure, createPhase, updatePhase, reorderPhases, deletePhase, createStep, updateStep, deleteStep, moveStep, reorderSteps, assign, listFiles, fileMetadata, fileRaw, relatedFiles`. Keep the `ApiError` class + `request` helper verbatim from v1.

- [ ] **Step 1: Write the failing test**
```ts
// src/api/client.test.ts
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { api, ApiError } from "./client";
import { emptyDocument } from "@/test/server";

const server = setupServer(
  http.post("/api/topologies", async ({ request }) => {
    const body = (await request.json()) as { path: string; kind: string };
    return HttpResponse.json({ ...emptyDocument, simulation: { ...emptyDocument.simulation,
      topologies: [{ id: "t0", path: body.path, kind: body.kind }] } });
  }),
  http.post("/api/assign", () => HttpResponse.json(emptyDocument)),
  http.get("/api/files/raw", () => HttpResponse.json({ path: "/w/x", content: "hi", truncated: false })),
  http.put("/api/steps/s0", () => new HttpResponse(null, { status: 404 })),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

it("addTopology posts and returns the document", async () => {
  const doc = await api.addTopology({ path: "wt.prmtop", kind: "hmr" });
  expect(doc.simulation.topologies[0].kind).toBe("hmr");
});
it("fileRaw fetches the head", async () => {
  expect((await api.fileRaw("x")).content).toBe("hi");
});
it("surfaces ApiError on 404", async () => {
  await expect(api.updateStep("s0", { name: "x" })).rejects.toBeInstanceOf(ApiError);
});
```

- [ ] **Step 2: Run → RED**

Run: `npx vitest run src/api/client.test.ts`
Expected: FAIL (`api.addTopology` undefined).

- [ ] **Step 3: Rewrite `src/api/client.ts`** (keep the `ApiError`/`request`/`post`/`put` helpers from v1 verbatim, then:)
```ts
import type {
  DocumentResponse, SaveResult, PreviewResponse, ValidationReport, DiscoverResult,
  RuntimeSettings, SettingsPatch, FileInfo, FileMetadata, RawFile, ExportFormat,
  AddTopology, UpdateTopology, PhaseCreate, PhaseUpdate,
  StepCreatePayload, StepUpdatePayload, StepMovePayload, AssignRequest,
} from "@/types";
// (SaveResult / SettingsPatch below)
export interface SaveResult { document: DocumentResponse; warnings: string[]; }
export interface SettingsPatch { auto_link_restarts?: boolean; strict_validation?: boolean; allow_gaps?: boolean; use_relative_paths?: boolean; }

// ... ApiError, request, post, put — copy verbatim from the v1 client.ts ...

const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

export const api = {
  getDocument: () => request<DocumentResponse>("/document"),
  openDocument: (path: string) => post<DocumentResponse>("/document/open", { path }),
  saveDocument: (a: { path?: string; format?: ExportFormat }) => post<SaveResult>("/document/save", a),
  previewDocument: (format: ExportFormat) => post<PreviewResponse>("/document/preview", { format }),
  discover: (a: { recursive: boolean; pattern?: string }) => post<DiscoverResult>("/document/discover", a),
  validate: () => post<ValidationReport>("/validate"),
  undo: () => post<DocumentResponse>("/undo"),
  redo: () => post<DocumentResponse>("/redo"),
  getSettings: () => request<RuntimeSettings>("/settings"),
  updateSettings: (p: SettingsPatch) => put<DocumentResponse>("/settings", p),

  addTopology: (b: AddTopology) => post<DocumentResponse>("/topologies", b),
  updateTopology: (id: string, b: UpdateTopology) => put<DocumentResponse>(`/topologies/${id}`, b),
  removeTopology: (id: string) => del<DocumentResponse>(`/topologies/${id}`),
  setStartingStructure: (path: string | null) => put<DocumentResponse>("/simulation/starting-structure", { path }),

  createPhase: (b: PhaseCreate) => post<DocumentResponse>("/phases", b),
  updatePhase: (id: string, b: PhaseUpdate) => put<DocumentResponse>(`/phases/${id}`, b),
  reorderPhases: (phase_ids: string[]) => post<DocumentResponse>("/phases/reorder", { phase_ids }),
  deletePhase: (id: string, reassign_to?: string) =>
    del<DocumentResponse>(`/phases/${id}${reassign_to ? `?reassign_to=${encodeURIComponent(reassign_to)}` : ""}`),

  createStep: (phaseId: string, b: StepCreatePayload) => post<DocumentResponse>(`/phases/${phaseId}/steps`, b),
  reorderSteps: (phaseId: string, step_ids: string[]) => post<DocumentResponse>(`/phases/${phaseId}/steps/reorder`, { step_ids }),
  updateStep: (id: string, b: StepUpdatePayload) => put<DocumentResponse>(`/steps/${id}`, b),
  deleteStep: (id: string) => del<DocumentResponse>(`/steps/${id}`),
  moveStep: (id: string, b: StepMovePayload) => post<DocumentResponse>(`/steps/${id}/move`, b),

  assign: (b: AssignRequest) => post<DocumentResponse>("/assign", b),

  listFiles: (a: { path?: string; recursive?: boolean; include_all?: boolean }) => {
    const q = new URLSearchParams();
    if (a.path) q.set("path", a.path);
    if (a.recursive !== undefined) q.set("recursive", String(a.recursive));
    if (a.include_all !== undefined) q.set("include_all", String(a.include_all));
    return request<FileInfo[]>(`/files?${q.toString()}`);
  },
  fileMetadata: (path: string) => request<FileMetadata>(`/files/metadata?path=${encodeURIComponent(path)}`),
  fileRaw: (path: string, maxBytes = 4096) => request<RawFile>(`/files/raw?path=${encodeURIComponent(path)}&max_bytes=${maxBytes}`),
  relatedFiles: (stem: string) => request<Record<string, string>>(`/files/related/${encodeURIComponent(stem)}`),
};
```

- [ ] **Step 4: Run → GREEN**

Run: `npx vitest run src/api/client.test.ts`
Expected: PASS (3 passed). (Full `tsc` is green at A4 — see A1 note.)

- [ ] **Step 5: Commit**
```bash
git add src/api/client.ts src/api/client.test.ts
git commit -m "feat(gui): API client for the Simulation-model endpoints"
```

### Task A3: react-query hooks (funnel) + MSW empty document

**Files:** Rewrite `src/api/hooks.ts`; Rewrite `src/test/server.ts`; Test `src/api/hooks.test.tsx`.

**Interfaces:** Consumes `api` (A2), `queryClient`/`setDocument`/`DOCUMENT_KEY` (unchanged `queryClient.ts`). Produces `useDocument`, `useFiles`, `useFileMetadata`, `useFileRaw`, and doc-mutations `useOpen, useSave, useDiscover, useValidate, usePreview, useUndo, useRedo, useUpdateSettings, useAddTopology, useUpdateTopology, useRemoveTopology, useSetStartingStructure, useCreatePhase, useUpdatePhase, useReorderPhases, useDeletePhase, useCreateStep, useUpdateStep, useDeleteStep, useMoveStep, useReorderSteps, useAssign`.

- [ ] **Step 1: Write the failing test** (single-tree render — the v1 lesson: query + mutation in ONE tree)
```tsx
// src/api/hooks.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { useDocument, useAddTopology } from "@/api/hooks";

function Probe() {
  const { data } = useDocument();
  const add = useAddTopology();
  return (
    <div>
      <span data-testid="n">{data?.simulation.topologies.length ?? -1}</span>
      <button onClick={() => add.mutate({ path: "wt.prmtop", kind: "hmr" })}>add</button>
    </div>
  );
}

it("addTopology writes the returned doc into the one cache", async () => {
  server.use(http.post("/api/topologies", () => HttpResponse.json(
    { ...emptyDocument, simulation: { ...emptyDocument.simulation, topologies: [{ id: "t0", path: "wt.prmtop", kind: "hmr" }] } })));
  render(<QueryClientProvider client={queryClient}><Probe /></QueryClientProvider>);
  await waitFor(() => expect(screen.getByTestId("n").textContent).toBe("0"));
  await act(async () => { screen.getByText("add").click(); });
  await waitFor(() => expect(screen.getByTestId("n").textContent).toBe("1"));
});
```

- [ ] **Step 2: Run → RED**

Run: `npx vitest run src/api/hooks.test.tsx`
Expected: FAIL (`useAddTopology` undefined).

- [ ] **Step 3a: Rewrite `src/test/server.ts`** to the new empty-document shape:
```ts
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import type { DocumentResponse } from "@/types";

export const emptyDocument: DocumentResponse = {
  base_directory: "/work", manifest_path: null, dirty: false, can_undo: false, can_redo: false,
  settings: { auto_link_restarts: true, strict_validation: true, allow_gaps: false, use_relative_paths: true },
  simulation: { version: 2, topologies: [], starting_structure: null, phases: [] },
};

export const apiHandlers = [
  http.get("/api/document", () => HttpResponse.json(emptyDocument)),
  http.get("/api/settings", () => HttpResponse.json(emptyDocument.settings)),
  http.get("/api/files", () => HttpResponse.json([])),
];
export const server = setupServer(...apiHandlers);
```

- [ ] **Step 3b: Rewrite `src/api/hooks.ts`**
```ts
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type SaveResult, type SettingsPatch } from "./client";
import { DOCUMENT_KEY, queryClient, setDocument } from "./queryClient";
import { pushToast } from "@/lib/toast";
import type {
  DocumentResponse, AddTopology, UpdateTopology, PhaseCreate, PhaseUpdate,
  StepCreatePayload, StepUpdatePayload, StepMovePayload, AssignRequest, ExportFormat,
} from "@/types";

export function useDocument() { return useQuery({ queryKey: DOCUMENT_KEY, queryFn: api.getDocument }); }
function docMutation<V>(fn: (v: V) => Promise<DocumentResponse>) {
  return useMutation({ mutationFn: fn, onSuccess: (doc) => setDocument(doc) });
}

export const useOpen = () => docMutation((path: string) => api.openDocument(path));
export const useUpdateSettings = () => docMutation((p: SettingsPatch) => api.updateSettings(p));
export const useUndo = () => docMutation((_: void) => api.undo());
export const useRedo = () => docMutation((_: void) => api.redo());

export const useAddTopology = () => docMutation((b: AddTopology) => api.addTopology(b));
export const useUpdateTopology = () => docMutation((a: { id: string; body: UpdateTopology }) => api.updateTopology(a.id, a.body));
export const useRemoveTopology = () => docMutation((id: string) => api.removeTopology(id));
export const useSetStartingStructure = () => docMutation((path: string | null) => api.setStartingStructure(path));

export const useCreatePhase = () => docMutation((b: PhaseCreate) => api.createPhase(b));
export const useUpdatePhase = () => docMutation((a: { id: string; body: PhaseUpdate }) => api.updatePhase(a.id, a.body));
export const useReorderPhases = () => docMutation((ids: string[]) => api.reorderPhases(ids));
export const useDeletePhase = () => docMutation((a: { id: string; reassignTo?: string }) => api.deletePhase(a.id, a.reassignTo));

export const useCreateStep = () => docMutation((a: { phaseId: string; body: StepCreatePayload }) => api.createStep(a.phaseId, a.body));
export const useUpdateStep = () => docMutation((a: { id: string; body: StepUpdatePayload }) => api.updateStep(a.id, a.body));
export const useDeleteStep = () => docMutation((id: string) => api.deleteStep(id));
export const useMoveStep = () => docMutation((a: { id: string; body: StepMovePayload }) => api.moveStep(a.id, a.body));
export const useReorderSteps = () => docMutation((a: { phaseId: string; ids: string[] }) => api.reorderSteps(a.phaseId, a.ids));

export const useAssign = () => docMutation((b: AssignRequest) => api.assign(b));

export const useDiscover = () =>
  useMutation({
    mutationFn: (a: { recursive: boolean; pattern?: string }) => api.discover(a),
    onSuccess: (res) => { setDocument(res.document); res.warnings.forEach((w) => pushToast(w, "warning")); },
  });
export const useSave = () =>
  useMutation({
    mutationFn: (a: { path?: string; format?: ExportFormat }) => api.saveDocument(a),
    onSuccess: (res: SaveResult) => { setDocument(res.document); res.warnings.forEach((w) => pushToast(w, "warning")); },
  });
export const useValidate = () => useMutation({ mutationFn: () => api.validate() });
export const usePreview = () => useMutation({ mutationFn: (format: ExportFormat) => api.previewDocument(format) });

export function useFiles(a: { path?: string; recursive?: boolean; include_all?: boolean }) {
  return useQuery({ queryKey: ["files", a.path ?? null, a.recursive ?? null, a.include_all ?? null], queryFn: () => api.listFiles(a) });
}
export function useFileMetadata(path: string | null) {
  return useQuery({ queryKey: ["file-metadata", path], enabled: !!path,
    queryFn: () => (path ? api.fileMetadata(path) : Promise.reject(new Error("path required"))) });
}
export function useFileRaw(path: string | null) {
  return useQuery({ queryKey: ["file-raw", path], enabled: !!path,
    queryFn: () => (path ? api.fileRaw(path) : Promise.reject(new Error("path required"))) });
}
export { queryClient, DOCUMENT_KEY };
```

- [ ] **Step 4: Run → GREEN**

Run: `npx vitest run src/api/hooks.test.tsx`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**
```bash
git add src/api/hooks.ts src/test/server.ts src/api/hooks.test.tsx
git commit -m "feat(gui): react-query hooks (funnel) for the Simulation model"
```

### Task A4: Selection context + app shell (deletes v1 feature components)

**Files:** Rewrite `src/state/selection.tsx`; Rewrite `src/App.tsx`; Delete `src/components/{FileBrowser,StageList,PropertiesPanel}/` and `src/App.test.tsx`, `src/App.workflows.test.tsx`; Test `src/App.test.tsx` (new).

**Interfaces:** Produces `SelectionProvider`, `useSelection()` → `{ sel, select }` where `sel` is `{ kind: "file"|"step"|"phase"|"sim"|null; id: string | null }` (id = file path / step id / phase id). App renders TopBar + 3 panes (`FilePanel` | `Canvas` | `Inspector`) inside one `DndContext` (drop wiring lands in C3 — until then a no-op `onDragEnd`).

- [ ] **Step 1: Write the failing test**
```tsx
// src/App.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/api/queryClient";
import App from "@/App";

it("renders the three panes over an empty document", async () => {
  render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);
  await waitFor(() => {
    expect(screen.getByTestId("pane-files")).toBeInTheDocument();
    expect(screen.getByTestId("pane-canvas")).toBeInTheDocument();
    expect(screen.getByTestId("pane-inspector")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run → RED**

Run: `npx vitest run src/App.test.tsx`
Expected: FAIL (old App imports deleted components / new panes absent).

- [ ] **Step 3a: Rewrite `src/state/selection.tsx`**
```tsx
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
export type SelKind = "file" | "step" | "phase" | "sim" | null;
export interface Selection { kind: SelKind; id: string | null; }
interface Ctx { sel: Selection; select: (kind: SelKind, id: string | null) => void; }
const SelectionCtx = createContext<Ctx | null>(null);
export function SelectionProvider({ children }: { children: ReactNode }) {
  const [sel, setSel] = useState<Selection>({ kind: null, id: null });
  const value = useMemo<Ctx>(() => ({ sel, select: (kind, id) => setSel({ kind, id }) }), [sel]);
  return <SelectionCtx.Provider value={value}>{children}</SelectionCtx.Provider>;
}
export function useSelection(): Ctx {
  const c = useContext(SelectionCtx);
  if (!c) throw new Error("useSelection outside SelectionProvider");
  return c;
}
```

- [ ] **Step 3b: Rewrite `src/App.tsx`** (panes stubbed where a later task fills them; DndContext present with a no-op drop until C3)
```tsx
import { useState } from "react";
import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SelectionProvider } from "@/state/selection";
import { ResizeHandle, Toaster } from "@/components/common";
import { usePersistentSize } from "@/lib/usePersistentSize";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useDocument } from "@/api/hooks";
import { TopBar } from "@/components/TopBar/TopBar";
import { FilePanel } from "@/components/FilePanel/FilePanel";
import { Canvas } from "@/components/Canvas/Canvas";
import { Inspector } from "@/components/Inspector/Inspector";

export default function App() {
  const [filesW, setFilesW] = usePersistentSize("files-w", 280);
  const [inspW, setInspW] = usePersistentSize("insp-w", 360);
  const { data: doc } = useDocument();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  const onDragEnd = (_e: DragEndEvent) => { /* wired in C3 */ };
  useUnsavedGuard(!!doc?.dirty);

  return (
    <SelectionProvider>
      <DndContext sensors={sensors} onDragEnd={onDragEnd}>
        <div className="flex flex-col h-full">
          <TopBar />
          <div className="flex flex-1 min-h-0">
            <div data-testid="pane-files" style={{ width: filesW }}
              className="shrink-0 border-r border-hairline overflow-auto bg-surface"><FilePanel /></div>
            <ResizeHandle direction="left" currentWidth={filesW} onResize={setFilesW} minWidth={200} maxWidth={480} />
            <div data-testid="pane-canvas" className="flex-1 min-w-0 overflow-auto"><Canvas /></div>
            <ResizeHandle direction="right" currentWidth={inspW} onResize={setInspW} minWidth={280} maxWidth={560} />
            <div data-testid="pane-inspector" style={{ width: inspW }}
              className="shrink-0 border-l border-hairline overflow-auto bg-surface"><Inspector /></div>
          </div>
        </div>
        <Toaster />
      </DndContext>
    </SelectionProvider>
  );
}
```

- [ ] **Step 3c:** Create minimal placeholder components so the shell compiles (each is fleshed out in its own task): `src/components/TopBar/TopBar.tsx` (`export function TopBar(){ return <header data-testid="topbar" className="h-12 border-b border-hairline"/>; }`), `src/components/FilePanel/FilePanel.tsx`, `src/components/Canvas/Canvas.tsx`, `src/components/Inspector/Inspector.tsx` (each `export function X(){ return <div/>; }`). Then delete the v1 dirs: `git rm -r src/components/FileBrowser src/components/StageList src/components/PropertiesPanel` and `git rm src/App.workflows.test.tsx`.

- [ ] **Step 4: Run → GREEN (full gate)**

Run: `npx vitest run && npx tsc --noEmit`
Expected: PASS + tsc clean (the transitional window from A1 is now closed — old components removed, shell compiles).

- [ ] **Step 5: Commit**
```bash
git add -A src/state/selection.tsx src/App.tsx src/App.test.tsx src/components
git commit -m "feat(gui): selection context + app shell (3 panes, one DndContext); remove v1 components"
```

---

## Group B — File panel + inspector

### Task B1: File panel with data-driven rows + drag sources

**Files:** Create `src/components/FilePanel/FilePanel.tsx`; Test `src/components/FilePanel/FilePanel.test.tsx`.

**Interfaces:** Consumes `useFiles`, `useSelection`. Each file row is `useDraggable({ id: 'file:' + path })`, shows the file name + a data-driven subtitle from `file_type`, and a suggestion hint for likely topology/coords (heuristic on `file_type` + name until metadata loads). Clicking a row `select("file", path)`.

- [ ] **Step 1: Write the failing test**
```tsx
// src/components/FilePanel/FilePanel.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { FilePanel } from "./FilePanel";

function wrap(ui: React.ReactNode) {
  return <QueryClientProvider client={queryClient}><SelectionProvider><DndContext>{ui}</DndContext></SelectionProvider></QueryClientProvider>;
}
it("lists files with a kind subtitle", async () => {
  server.use(http.get("/api/files", () => HttpResponse.json([
    { path: "/work/wt_hmr.prmtop", name: "wt_hmr.prmtop", file_type: "prmtop", is_directory: false, size: 1, extension: ".prmtop", parent: "/work", children: null },
  ])));
  render(wrap(<FilePanel />));
  await waitFor(() => expect(screen.getByText("wt_hmr.prmtop")).toBeInTheDocument());
  expect(screen.getByText(/prmtop/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run → RED** — `npx vitest run src/components/FilePanel/FilePanel.test.tsx` → FAIL.

- [ ] **Step 3: Implement `FilePanel.tsx`** (flat, recursive-flattened list + search; row = draggable + select; hint heuristic). [Full component code: a `flatten(FileInfo[])`; a `<input>` search bound to local state; map rows to `DraggableFile` using `useDraggable({id:'file:'+path})` with `listeners` on the icon span and `onClick` on the name button calling `select("file", path)`; subtitle = `file_type`; a green hint when `name.includes("hmr")` → "looks like your HMR topology" or `file_type==="inpcrd"` → "looks like the starting structure". Use `bg-surface`/`text-ink`/`font-mono` tokens; icons from `lucide-react` via `components/common/Icons`.]

- [ ] **Step 4: Run → GREEN** — `npx vitest run src/components/FilePanel/FilePanel.test.tsx && npx tsc --noEmit` → PASS.

- [ ] **Step 5: Commit** — `git add src/components/FilePanel && git commit -m "feat(gui): file panel with data-driven rows + drag sources"`

### Task B2: Inspector — Peek + Full-details / Raw tabs

**Files:** Create `src/components/Inspector/Inspector.tsx`, `FilePeek.tsx`, `FileDetails.tsx`; Test `Inspector.test.tsx`.

**Interfaces:** Consumes `useSelection`, `useFileMetadata`, `useFileRaw`. When a file is selected: a Peek (curated top fields from `metadata.metadata`) + tabs Overview / Full details (all parsed fields grouped) / Raw file (`useFileRaw`) / Warnings. When a step/phase/sim is selected: renders `StepEditor` / phase editor / sim settings (B3/C-tasks fill these; here a stub is acceptable). Empty selection → a hint to pick a file.

- [ ] **Step 1: Failing test** — select a file (via a test harness that sets selection), mock `/api/files/metadata` returning `{ metadata: { details: { atoms: 42318, hmr_active: true }, kind: "prmtop" }, warnings: [] }`, assert the Peek shows "42318" and switching to the Raw tab fetches `/api/files/raw`.
- [ ] **Step 2: RED.**
- [ ] **Step 3: Implement** the tabbed inspector (Peek row + 4 tabs; Full details maps `Object.entries(metadata.details)` into grouped rows; Raw tab lazy-loads `useFileRaw`; Warnings lists `metadata.warnings`). [Complete TSX per the mockup: `file-details` styling with the token classes; `font-mono` for values.]
- [ ] **Step 4: GREEN** (`npx vitest run src/components/Inspector && npx tsc --noEmit`).
- [ ] **Step 5: Commit** — `git commit -m "feat(gui): inspector Peek + full-details/raw tabs"`

### Task B3: Assign actions (file → pool / starting-structure / step / create-step)

**Files:** Create `src/components/Inspector/AssignActions.tsx`; Modify `Inspector.tsx`; Test `AssignActions.test.tsx`.

**Interfaces:** Consumes `useAddTopology`, `useSetStartingStructure`, `useAssign`, `useCreatePhase`+`useCreateStep`, `useDocument` (for phase/step targets). Renders role-appropriate buttons keyed off `file_type`, the detected one marked primary: prmtop → "Add to pool as HMR/normal", "Set as phase default ▾", "Assign to a step ▾"; coord (`inpcrd`) → "Set as starting structure" (primary), "Assign as a step's input ▾"; `mdin` → "Create a step" (role from a select). Each calls the matching mutation (`assign` with the right `target_type`).

- [ ] **Step 1: Failing test** — mock `/api/topologies` and `/api/assign`; render AssignActions for a prmtop path; click "Add to pool as HMR" → asserts `POST /api/topologies {kind:"hmr"}` fired and the returned doc has the topology.
- [ ] **Step 2: RED.**
- [ ] **Step 3: Implement** the assign block. For "Add to pool as HMR": `addTopology.mutate({ path, kind: "hmr" })`. For "Set as starting structure": `setStartingStructure.mutate(path)`. For "Assign to a step": `assign.mutate({ path, target_type: "step_topology", target_id: stepId })`. For a slot: `assign.mutate({ path, target_type: "step_slot", target_id: stepId, slot })`. For "Create a step": `createStep.mutate({ phaseId, body: { name, mdin: path } })` (creating a phase first if none). [Complete TSX.]
- [ ] **Step 4: GREEN.**
- [ ] **Step 5: Commit** — `git commit -m "feat(gui): data-driven file assign actions in the inspector"`

---

## Group C — Canvas + drag routing

### Task C1: Canvas — sim header (topology pool + starting structure), phases, step nodes

**Files:** Create `src/components/Canvas/Canvas.tsx`, `SimHeader.tsx`, `PhaseSection.tsx`, `StepNode.tsx`; Test `Canvas.test.tsx`.

**Interfaces:** Consumes `useDocument`, `useSelection`, drop targets via `useDroppable`. `SimHeader` renders topology pool chips (each `TopologyModel`, normal/HMR badge) + a "+ add prmtop" affordance + the starting-structure slot (droppable id `starting`, `pool`). `PhaseSection` renders a phase header (name + `role` badge + cascade "set topology ▾") and its steps; `StepNode` shows the step name, its bound topology chip (`▸ <pool path>`), and its input-coords source (`◂ starting structure` | `◂ <ref restart>` | `◂ <path>`). Selecting a phase/step calls `select`. Long numbered runs (a phase whose steps share a numeric base with ≥ N members) collapse to one band with an expand toggle (local state).

- [ ] **Step 1: Failing test** — mock `/api/document` returning a sim with one Production phase + two steps (one bound to an HMR topology); assert the phase name, both step names, and the HMR chip render; empty sim → "Discover or drop files to start".
- [ ] **Step 2: RED.**
- [ ] **Step 3: Implement** the canvas spine. [Complete TSX: map `doc.simulation.phases` → `PhaseSection`; within, map `phase.steps` → `StepNode`; resolve a step's topology chip via `sim.topologies.find(t=>t.id===step.topology)?.path`; input-source label from `step.input_coords`. Collapse: group a phase's steps by numeric base (`name.replace(/[-_.]?\d+$/,'')`); if a group has ≥ 6 members, render a collapsed band unless expanded. Droppable slots: `slot:<stepId>:<kind>`, `pool`, `starting`, `phase:<id>`. Tokens: `bg-surface`, phase header `border-l-4`, HMR chip `text-accent`.]
- [ ] **Step 4: GREEN.**
- [ ] **Step 5: Commit** — `git commit -m "feat(gui): canvas sim header + phase sections + step nodes"`

### Task C2: Continuity arrows, gaps, missing-member ghosts, collapse

**Files:** Create `src/components/Canvas/ContinuityArrow.tsx`; Modify `Canvas.tsx`/`PhaseSection.tsx`; Modify state to hold the latest `ValidationReport` (from a `useValidate` call on load/after mutations, stored in local state or a `["validation"]` query); Test `Canvas.continuity.test.tsx`.

**Interfaces:** Between consecutive steps render a `ContinuityArrow` (down glyph). When the latest validation `protocol_issues`/`suggestions` include a `continuity_gap` for the pair, render it amber with the magnitude (parsed from the suggestion evidence/title). A `missing_run` suggestion renders a dashed ghost node at the sequence position. A `SuggestionsContext` (or prop) carries the current suggestions so both the canvas and the tray (D1) read the same list.

- [ ] **Step 1: Failing test** — provide a document + a `ValidationReport` with a `continuity_gap` suggestion ("...+20 ps...") and a `missing_run` ("prod_0002 ... missing"); assert an amber gap marker with "20 ps" and a dashed "prod_0002" ghost render.
- [ ] **Step 2: RED.**
- [ ] **Step 3: Implement** arrows + gap/ghost rendering keyed off the suggestions list. [Complete TSX + a small `parseGap(evidence)` helper.]
- [ ] **Step 4: GREEN.**
- [ ] **Step 5: Commit** — `git commit -m "feat(gui): continuity arrows, gap badges, missing-run ghosts"`

### Task C3: App DndContext + `resolveDrop` router (all drags → endpoints)

**Files:** Create `src/components/Canvas/resolveDrop.ts` + `resolveDrop.test.ts`; Modify `src/App.tsx` (`onDragEnd`).

**Interfaces:** Produces a pure `resolveDrop(activeId: string, overId: string | null): DropAction | null` where `DropAction` is a discriminated union: `{type:"pool"; path}` | `{type:"starting"; path}` | `{type:"step_slot"; stepId; kind; path}` | `{type:"step_topology"; stepId; path}` | `{type:"phase_topology"; phaseId; path}` | `{type:"reorder_steps"; phaseId; activeStepId; overStepId}` | `{type:"move_step"; stepId; phaseId}` | `{type:"reorder_phases"; activePhaseId; overPhaseId}`. Drag ids: `file:<path>`, `step:<id>`, `phase:<id>`, `slot:<stepId>:<kind>`, `pool`, `starting`, `phase:<id>`. `App.onDragEnd` maps the action to the matching hook mutation.

- [ ] **Step 1: Write the failing test** (pure — no React)
```ts
// src/components/Canvas/resolveDrop.test.ts
import { describe, it, expect } from "vitest";
import { resolveDrop } from "./resolveDrop";
it("routes a file onto the pool / starting / a slot", () => {
  expect(resolveDrop("file:/w/wt.prmtop", "pool")).toEqual({ type: "pool", path: "/w/wt.prmtop" });
  expect(resolveDrop("file:/w/wt.inpcrd", "starting")).toEqual({ type: "starting", path: "/w/wt.inpcrd" });
  expect(resolveDrop("file:/w/min.in", "slot:s0:mdin")).toEqual({ type: "step_slot", stepId: "s0", kind: "mdin", path: "/w/min.in" });
  expect(resolveDrop("file:/w/wt_hmr.prmtop", "step:s0")).toEqual({ type: "step_topology", stepId: "s0", path: "/w/wt_hmr.prmtop" });
  expect(resolveDrop("file:/w/wt_hmr.prmtop", "phase:p0")).toEqual({ type: "phase_topology", phaseId: "p0", path: "/w/wt_hmr.prmtop" });
});
it("routes step/phase reorder + move", () => {
  expect(resolveDrop("step:s1", "step:s2")).toEqual({ type: "reorder_or_move_step", activeStepId: "s1", overStepId: "s2" });
  expect(resolveDrop("step:s1", "phase:p2")).toEqual({ type: "move_step", stepId: "s1", phaseId: "p2" });
  expect(resolveDrop("phase:p1", "phase:p2")).toEqual({ type: "reorder_phases", activePhaseId: "p1", overPhaseId: "p2" });
});
it("returns null on unknown/self drops", () => {
  expect(resolveDrop("file:/w/x", null)).toBeNull();
  expect(resolveDrop("step:s1", "step:s1")).toBeNull();
});
```
(Note: a `step:->step:` drop can mean reorder-within-phase OR move-across-phase; `resolveDrop` returns `reorder_or_move_step` and `App.onDragEnd` resolves which by looking up whether the two steps share a phase in the current `doc`.)

- [ ] **Step 2: Run → RED** — `npx vitest run src/components/Canvas/resolveDrop.test.ts` → FAIL.

- [ ] **Step 3: Implement `resolveDrop.ts`** (string parsing + the union above) and wire `App.onDragEnd`:
```ts
// in App.tsx — replace the no-op onDragEnd
const assign = useAssign(); const reorderSteps = useReorderSteps();
const moveStep = useMoveStep(); const reorderPhases = useReorderPhases();
const onDragEnd = (e: DragEndEvent) => {
  const a = resolveDrop(String(e.active.id), e.over ? String(e.over.id) : null);
  if (!a || !doc) return;
  switch (a.type) {
    case "pool": return void assign.mutate({ path: a.path, target_type: "pool", kind: a.path.includes("hmr") ? "hmr" : "normal" });
    case "starting": return void assign.mutate({ path: a.path, target_type: "starting_structure" });
    case "step_slot": return void assign.mutate({ path: a.path, target_type: "step_slot", target_id: a.stepId, slot: a.kind });
    case "step_topology": return void assign.mutate({ path: a.path, target_type: "step_topology", target_id: a.stepId });
    case "phase_topology": return void assign.mutate({ path: a.path, target_type: "phase_topology", target_id: a.phaseId });
    case "move_step": return void moveStep.mutate({ id: a.stepId, body: { phase_id: a.phaseId, index: -1 } });
    case "reorder_phases": {
      const ids = doc.simulation.phases.map((p) => p.id);
      return void reorderPhases.mutate(reorderIds(ids, a.activePhaseId, a.overPhaseId));
    }
    case "reorder_or_move_step": {
      const src = doc.simulation.phases.find((p) => p.steps.some((s) => s.id === a.activeStepId));
      const dst = doc.simulation.phases.find((p) => p.steps.some((s) => s.id === a.overStepId));
      if (!src || !dst) return;
      if (src.id === dst.id) {
        const ids = src.steps.map((s) => s.id);
        return void reorderSteps.mutate({ phaseId: src.id, ids: reorderIds(ids, a.activeStepId, a.overStepId) });
      }
      const idx = dst.steps.findIndex((s) => s.id === a.overStepId);
      return void moveStep.mutate({ id: a.activeStepId, body: { phase_id: dst.id, index: idx } });
    }
  }
};
```
(Add a tiny `reorderIds(ids, active, over)` util — port from v1 `StageList/reorder.ts` — or inline: move `active` to `over`'s index.)

- [ ] **Step 4: Run → GREEN** — `npx vitest run && npx tsc --noEmit` → PASS.

- [ ] **Step 5: Commit** — `git add src/components/Canvas/resolveDrop.ts src/components/Canvas/resolveDrop.test.ts src/App.tsx && git commit -m "feat(gui): pure resolveDrop router + app drag wiring to endpoints"`

---

## Group D — Suggestions tray + TopBar workflows

### Task D1: Suggestions tray (Needs you / Applied)

**Files:** Create `src/components/Suggestions/SuggestionsTray.tsx`; Modify `Inspector.tsx` (render it in the sim/empty context); Test `SuggestionsTray.test.tsx`.

**Interfaces:** Consumes the current suggestions list (from the latest `discover`/`validate` result held in a `["validation"]`/`["discover-suggestions"]` query or lifted state). Splits by `severity`: `needs_you` (Accept/Adjust/Ignore) vs `applied`/`info` (dismiss/undo). Each card shows `title` + the `evidence` signal + `actions`. "Accept"/"Ignore" call the relevant mutation or dismiss locally; "Undo" calls `useUndo`.

- [ ] **Step 1: Failing test** — render with a `missing_run` (needs_you) + a `role_guess` (applied) suggestion; assert both groups, the evidence strings, and that the missing-run card shows an "Accept"/"Ignore" affordance.
- [ ] **Step 2: RED.** — [Step 3 implements; Step 4 GREEN; Step 5 commit `feat(gui): draft-first suggestions tray`.]

### Task D2: TopBar workflows + modals + final build

**Files:** Rewrite `src/components/TopBar/TopBar.tsx`, `DiscoverModal.tsx`, `ExportModal.tsx`, `ValidationPanel.tsx`; Modify `App.tsx` (mount modals, wire handlers); Test `src/components/TopBar/TopBar.test.tsx` + `src/App.workflows.test.tsx`.

**Interfaces:** TopBar buttons: Open, Save (direct if `manifest_path` else FilePicker), dirty dot, Discover (→ DiscoverModal → `useDiscover`, draft-first: the returned document replaces state and its suggestions feed the tray), Validate (→ ValidationPanel via `useValidate`, feeding suggestions), Export (→ ExportModal via `usePreview`, json/yaml only), Undo/Redo (`useUndo`/`useRedo`, disabled per `can_undo`/`can_redo`). Reuse `FilePicker`. `confirmIfDirty()` guards Open/Discover.

- [ ] **Step 1: Failing test** — TopBar renders all buttons; clicking Discover opens the modal and Run fires `POST /api/document/discover`; the returned `DiscoverResult.suggestions` appear in the tray; Undo disabled when `can_undo` is false. ExportModal offers only `yaml`/`json`.
- [ ] **Step 2: RED.**
- [ ] **Step 3: Implement** the TopBar + modals against the new hooks (port structure from v1 `TopBar`/`DiscoverModal`/`ExportModal`/`ValidationPanel`, swapping to the new hooks + the DiscoverResult/ValidationReport shapes; lift the suggestions list to App state so canvas + tray + validation share it).
- [ ] **Step 4: Run → GREEN + BUILD**

Run: `npx vitest run && npx tsc --noEmit && npm run build`
Expected: all tests pass, tsc clean, **`vite build` exits 0** (first full end-to-end build — no placeholders left; the static bundle is produced offline).

- [ ] **Step 5: Commit** — `git add -A src/components/TopBar src/App.tsx src/App.workflows.test.tsx && git commit -m "feat(gui): top-bar workflows (open/save/discover-draft/validate/export/undo-redo) + build"`

---

## Self-Review — UX pillars, endpoints, types

**UX pillar → task**
- Continuous-timeline canvas (phases, step nodes ▸topology ◂input, collapse) → C1; continuity arrows + gaps + missing-run ghosts → C2.
- Topology pool + starting structure on the sim header; per-step binding; phase cascade → C1 (render) + B3/C3 (assign/drag) + D2 (settings).
- File panel with data-driven rows + drag sources → B1; assign actions → B3.
- Inspector Peek + Full-details/Raw/Warnings → B2.
- Draft-first suggestions tray (Needs you / Applied, each with its signal) → D1; fed by discover/validate → C2/D2.
- Draft-first Discover, server-authoritative undo/redo, save/export → D2.
- Drag-drop at both levels routed to endpoints → C3.

**Endpoint → task (all of `routes.py`)**
- `GET /document` A3/A4 · `open` D2 · `save` D2 · `preview` D2(Export) · `discover`→DiscoverResult D2 · `validate` C2/D2 · `undo`/`redo` D2 · `GET/PUT /settings` D2 · `POST /topologies`,`PUT/DELETE /topologies/{id}` B3/C3/D2 · `PUT /simulation/starting-structure` B3/C3 · `POST /phases`,`/phases/reorder`,`PUT/DELETE /phases/{id}` C1/C3/D2 · `POST /phases/{id}/steps`,`/steps/reorder`,`PUT/DELETE /steps/{id}`,`/steps/{id}/move` B3/C1/C3 · `POST /assign` B3/C3 · `GET /files`,`/files/metadata`,`/files/raw`,`/files/related/{stem}` B1/B2.

**Type consistency (TS ↔ Python):** every `*Model`/`DocumentResponse`/`Suggestion`/`ValidationReport`/`DiscoverResult`/`FileInfo`/`FileMetadata`/`RawFile` field name + type in `src/types/index.ts` (A1) matches `ambermeta/gui/api/schemas.py` verbatim; `AssignTarget` values match the P2 store's `assign_file` (`pool|starting_structure|phase_topology|step_topology|step_slot`); `StageRole` values equal the API's canonical tokens; `ExportFormat` restricted to `yaml|json` (v2 save/preview support only those).

**Note on scope:** B2/B3/C1/C2/D1 steps 3 describe the component with its exact data wiring, hooks, endpoints, drag ids, and tokens but leave pixel-level markup to the implementer (the mockups in the design doc are the visual reference); the load-bearing logic (data mapping, mutations, drag routing, tab/collapse state) and every test are fully specified. If the executor prefers finer granularity, C1 may split into C1a (sim header + phases/steps) and C1b (collapse), but one task is fine.
