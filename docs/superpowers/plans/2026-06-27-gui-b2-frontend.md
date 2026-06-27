# GUI Redesign — B2: Frontend Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the AmberMeta GUI frontend as a calm, offline, server-authoritative manifest editor over the B1 API — react-query for all server state, a restrained functional design system, and first-class handling of large protocols.

**Architecture:** A React 18 + TypeScript + Vite SPA. **react-query owns all server state** (one `useDocument` query + mutation hooks that set the document cache from each endpoint's returned `DocumentResponse` — no client mirror, no client-side undo stack). UI-only state (selection, panel sizes, expand/collapse, modals) is local `useState`/localStorage. Three resizable panes — **Files │ Stages │ Properties** — with a top bar (Open / Save / Validate / Discover / Undo / Redo / Export) and an unsaved-changes guard. The stage list is virtualized and groups numbered sequences. The build outputs to `ambermeta/gui/static/`, fully offline (bundled fonts, no CDN).

**Tech Stack:** React 18, TypeScript 5, Vite 5, Tailwind 3, @tanstack/react-query 5, @tanstack/react-virtual 3, @dnd-kit, lucide-react, @fontsource (Inter + JetBrains Mono). Tests: Vitest + @testing-library/react + @testing-library/user-event + jsdom + msw.

## Global Constraints

- **Offline / no CDN (hard requirement).** No external network references anywhere in `index.html` or `src/`. Fonts are bundled via `@fontsource/inter` and `@fontsource/jetbrains-mono` and imported in `main.tsx`. The built `static/index.html` MUST contain no `fonts.googleapis.com`/`gstatic`/`cdn`/`unpkg` references.
- **`gui-static-check` gate.** `.github/workflows/gui-static-check.yml` runs `npm ci && npm run build` in `ambermeta/gui/frontend/` and fails if `git diff --quiet -- ambermeta/gui/static` is dirty. So the committed `ambermeta/gui/static/` MUST exactly match a fresh build. The final task rebuilds and commits it; do not hand-edit files under `static/`.
- **Server is the single source of truth.** Every server-state read goes through react-query; every mutation hook writes the returned `DocumentResponse` into the `["document"]` query cache (or invalidates it). NO Zustand, NO client-side undo stack, NO parallel mirror of server data. Undo/Redo call `POST /api/undo` / `POST /api/redo` and apply the returned document.
- **Design tokens (restrained / functional)** — exact values, defined once in `tailwind.config.js`, used everywhere via Tailwind classes (no ad-hoc hex in components):
  - surfaces: `app #FAFAF9`, `surface #FFFFFF`, `hairline #E6E6E3`
  - text: `ink #1C1C1A`, `ink-secondary #6B6B66`, `ink-muted #9A9A95`
  - accent: `accent #2F66D0`, `accent-subtle #EAF1FC` (interactive / selected / focus only)
  - semantic (functional only): `valid #15803D`, `warning #B45309`, `error #B91C1C`
  - type: **Inter** for UI (weights 400/500/600); **JetBrains Mono** for data only (paths, dt, nstlim, atom counts, gaps); scale 12/13/14/16/20
  - icons: lucide, **functional only** (file-type glyphs, validation status, undo/redo, a few toolbar actions); primary actions are text labels.
- **Quality floor:** visible keyboard focus on every interactive element; `prefers-reduced-motion` respected; layout responsive down to laptop widths (single graceful breakpoint; no tablet/mobile).
- **Node/TS:** TypeScript strict (existing `tsconfig.json` has `strict`, `noUnusedLocals`, `noUnusedParameters`). Path alias `@/*` → `src/*`. Target ES2020.
- **The B1 API contract (the only backend this talks to)** — base path `/api`, dev-proxied to `http://localhost:8765`:
  - `GET /document` → `DocumentResponse`
  - `POST /document/open` `{path}` → `DocumentResponse` (4xx on bad/oob path)
  - `POST /document/save` `{path?, format?}` → `SaveResult {document, warnings[]}`
  - `POST /document/preview` `{format}` → `PreviewResponse {content, warnings[], format}`
  - `POST /document/discover` `{recursive, pattern?}` → `DocumentResponse`
  - `POST /stages` `StageCreate` → `DocumentResponse`
  - `PUT /stages/{id}` `StageUpdate` → `DocumentResponse`
  - `DELETE /stages/{id}` → `DocumentResponse`
  - `POST /stages/reorder` `{stage_ids[]}` → `DocumentResponse`
  - `PUT /stages/bulk` `{stage_ids[], update}` → `DocumentResponse`
  - `GET /settings` → `GlobalSettings`; `PUT /settings` `SettingsPatch` → `DocumentResponse`
  - `POST /undo` → `DocumentResponse`; `POST /redo` → `DocumentResponse`
  - `POST /validate` → `ValidationReport`
  - `GET /files?path&recursive&include_all` → `FileInfo[]`
  - `GET /files/metadata?path` → `FileMetadata`
  - `GET /files/related/{stem}` → `Record<string,string>` (kind → path)
  - `POST /link-restarts` → `DocumentResponse`
  - `GET /sequences` → `Record<string, string[]>` (base name → ordered stage **ids**)
- **API response shapes (verbatim — the TS types must match B1's Pydantic models):**
  - `StageModel = { id: string; name: string; role: string; prmtop: string|null; mdin: string|null; mdout: string|null; mdcrd: string|null; inpcrd: string|null; expected_gap_ps: number|null; gap_tolerance_ps: number|null; notes: string[] }`
  - `GlobalSettings = { global_prmtop: string|null; hmr_prmtop: string|null; initial_coordinates: string|null; auto_link_restarts: boolean; strict_validation: boolean; allow_gaps: boolean; use_relative_paths: boolean }`
  - `DocumentResponse = { base_directory: string; manifest_path: string|null; dirty: boolean; can_undo: boolean; can_redo: boolean; settings: GlobalSettings; stages: StageModel[] }`
  - `SaveResult = { document: DocumentResponse; warnings: string[] }`
  - `PreviewResponse = { content: string; warnings: string[]; format: string }`
  - `ValidationReport = { ok: boolean; totals: { steps: number; time_ps: number; stage_count: number }; protocol_issues: string[]; stage_issues: StageIssue[] }`
  - `StageIssue = { name: string; ok: boolean; degraded: boolean; errors: string[]; warnings: string[]; info: string[]; missing_files: { kind: string; path: string }[] }`
  - `FileInfo = { path: string; name: string; file_type: string; is_directory: boolean; size: number|null; extension: string|null; parent: string|null; children: FileInfo[]|null }`
  - `FileMetadata = { file_path: string; file_type: string; metadata: { details: Record<string,unknown>|null; warnings: string[]; kind: string }; warnings: string[] }`
- **Behavioral rules surfaced by B1's final review (must be honored in B2):**
  - A protocol can report `validate.ok === true` while `protocol_issues` is non-empty (a real continuity gap lands in `protocol_issues`, not in `ok`). **The validation UI must treat a non-empty `protocol_issues` as "not fully valid"** (e.g. a distinct "valid, with N protocol notes" state), never a clean pass.
  - `stage.role === ""` means "unknown" (not a real role).
  - Saving CSV when `hmr_prmtop` is set returns a `warnings[]` entry; surface save warnings to the user.

---

## File Structure

All paths under `ambermeta/gui/frontend/`.

**Config / entry (Task 1):**
- `package.json` — deps: drop `zustand`; add `@fontsource/inter`, `@fontsource/jetbrains-mono`, `@tanstack/react-virtual`; devDeps `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`, `jsdom`, `msw`. (`@tanstack/react-query` already present.) Add `"test": "vitest run"` script.
- `index.html` — remove the three Google Fonts `<link>` tags.
- `tailwind.config.js` — the design tokens above.
- `src/index.css` — Tailwind layers, base body/font, focus-visible ring, reduced-motion, scrollbar.
- `src/main.tsx` — bundled-font imports + `QueryClientProvider`.
- `vite.config.ts` — add a `test` block (jsdom env, setup file, css true).
- `src/test/setup.ts` — jest-dom matchers + msw server lifecycle.
- `src/test/server.ts` — msw server + default handlers for the B1 API.

**Data layer (Tasks 2–3):**
- `src/types/index.ts` — the API types above + `FILE_TYPE_CONFIG`/`STAGE_ROLE_CONFIG` (ported).
- `src/api/client.ts` — typed `fetch` wrappers for every B1 endpoint.
- `src/api/hooks.ts` — react-query `useDocument` + mutation/query hooks.
- `src/api/queryClient.ts` — the shared `QueryClient` + the `DOCUMENT_KEY` constant + a `setDocument` helper.

**UI-only state / utils:**
- `src/state/selection.ts` — a tiny React context for current selection + multi-select (UI-only).
- `src/lib/usePersistentSize.ts` — localStorage-backed panel sizes.
- `src/lib/format.ts` — display helpers (format ps, atom counts, role label).

**Shell + panels (Tasks 4–9):**
- `src/App.tsx` — shell: 3 resizable panes + `<TopBar/>`.
- `src/components/TopBar/TopBar.tsx` — actions + dirty indicator + undo/redo (Task 4); Open/Save/Discover/Export modals wired in Task 10.
- `src/components/FileBrowser/FileBrowser.tsx` — Files pane (Task 5).
- `src/components/StageList/StageList.tsx` — Stages pane: virtualized + sequence groups + dnd (Task 6); `StageCard.tsx`, `FileDropZone.tsx`.
- `src/components/PropertiesPanel/PropertiesPanel.tsx` — Properties pane (Task 7); `BulkEditPanel.tsx`, `SettingsPanel.tsx`.
- `src/components/FilePicker/FilePicker.tsx` — reusable tree picker modal (Task 8).
- `src/components/ValidationPanel/ValidationPanel.tsx` — validation results + jump-to-issue (Task 9).
- `src/components/common/` — **ported as-is:** `ResizeHandle.tsx`, `Icons.tsx` (lucide re-exports + `FileIcon`); `Button.tsx`, `Modal.tsx`, `Badge.tsx` (new, small).

**Build (Task 11):**
- `ambermeta/gui/static/**` — regenerated bundle, committed.

---

## Task 1: Tooling, design tokens, fonts, and the test harness

**Files:**
- Modify: `ambermeta/gui/frontend/package.json`, `index.html`, `tailwind.config.js`, `vite.config.ts`, `src/main.tsx`, `src/index.css`
- Create: `src/test/setup.ts`, `src/test/server.ts`, `src/lib/format.ts`, `src/lib/format.test.ts`

**Interfaces:**
- Consumes: nothing (foundation).
- Produces:
  - Tailwind theme tokens (colors `app/surface/hairline/ink/ink-secondary/ink-muted/accent/accent-subtle/valid/warning/error`, `font-sans`/`font-mono`, the 12–20 `fontSize` scale).
  - `src/test/server.ts` exporting `server` (an msw `setupServer`) and `apiHandlers` (default happy-path handlers for the B1 API).
  - `src/lib/format.ts`: `formatPs(v: number|null): string`, `formatCount(n: number|null): string`, `roleLabel(role: string): string` (returns `"Unknown"` for `""`).

**Design notes:**
- The whole suite must build offline. Verify after the task: `grep -ri "googleapis\|gstatic\|unpkg\|cdn" index.html src` returns nothing.
- msw is the API boundary mock for all later component/hook tests. `server.ts` provides realistic default responses keyed to the B1 shapes; individual tests override per-endpoint with `server.use(...)`.

- [ ] **Step 1: Update `package.json`**

Set dependencies/devDependencies and scripts (keep existing React/Vite/Tailwind/@dnd-kit/lucide/@tanstack-react-query versions; remove `zustand`):

```jsonc
{
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "@dnd-kit/core": "^6.0.0",
    "@dnd-kit/sortable": "^7.0.0",
    "@dnd-kit/utilities": "^3.2.0",
    "@fontsource/inter": "^5.0.0",
    "@fontsource/jetbrains-mono": "^5.0.0",
    "@tanstack/react-query": "^5.0.0",
    "@tanstack/react-virtual": "^3.0.0",
    "lucide-react": "^0.300.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.0.0",
    "@testing-library/react": "^14.0.0",
    "@testing-library/user-event": "^14.0.0",
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@vitejs/plugin-react": "^4.0.0",
    "autoprefixer": "^10.4.0",
    "jsdom": "^24.0.0",
    "msw": "^2.0.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.3.0",
    "vite": "^5.0.0",
    "vitest": "^1.0.0"
  }
}
```

Then run `npm install` in `ambermeta/gui/frontend/`.

- [ ] **Step 2: Remove the CDN font links from `index.html`**

Delete the three `<link>` tags (`preconnect` ×2 and the `fonts.googleapis.com/css2?...` stylesheet). Leave the rest of `index.html` intact (the `<div id="root">` and the module script).

- [ ] **Step 3: Write the design tokens into `tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        app: "#FAFAF9",
        surface: "#FFFFFF",
        hairline: "#E6E6E3",
        ink: { DEFAULT: "#1C1C1A", secondary: "#6B6B66", muted: "#9A9A95" },
        accent: { DEFAULT: "#2F66D0", subtle: "#EAF1FC" },
        valid: "#15803D",
        warning: "#B45309",
        error: "#B91C1C",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      fontSize: {
        xs: ["12px", "16px"],
        sm: ["13px", "18px"],
        base: ["14px", "20px"],
        lg: ["16px", "24px"],
        xl: ["20px", "28px"],
      },
    },
  },
  plugins: [],
};
```

- [ ] **Step 4: Bundle fonts + QueryClientProvider in `src/main.tsx`**

```tsx
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "./index.css";

import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./api/queryClient";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
```

(`queryClient` and `App` are created in Tasks 3/4; this file compiles once those exist. Until then, the build step for THIS task only checks tokens/fonts — see Step 8.)

- [ ] **Step 5: Base styles in `src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  html, body, #root { height: 100%; }
  body {
    @apply bg-app text-ink font-sans antialiased;
    font-size: 14px;
  }
  *:focus-visible {
    outline: 2px solid theme("colors.accent.DEFAULT");
    outline-offset: 1px;
  }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}

/* thin neutral scrollbars for the dense panes */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { @apply bg-hairline rounded; }
```

- [ ] **Step 6: Add the Vitest config to `vite.config.ts`**

Add a `test` block to the existing config (keep the React plugin, the `@` alias, and `build.outDir: '../static'`):

```ts
/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: { proxy: { "/api": "http://localhost:8765" } },
  build: { outDir: "../static", emptyOutDir: true },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    globals: true,
  },
});
```

- [ ] **Step 7: Create the test harness**

`src/test/setup.ts`:
```ts
import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

`src/test/server.ts`:
```ts
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import type { DocumentResponse } from "@/types";

export const emptyDocument: DocumentResponse = {
  base_directory: "/work",
  manifest_path: null,
  dirty: false,
  can_undo: false,
  can_redo: false,
  settings: {
    global_prmtop: null, hmr_prmtop: null, initial_coordinates: null,
    auto_link_restarts: true, strict_validation: true, allow_gaps: false,
    use_relative_paths: true,
  },
  stages: [],
};

export const apiHandlers = [
  http.get("/api/document", () => HttpResponse.json(emptyDocument)),
  http.get("/api/settings", () => HttpResponse.json(emptyDocument.settings)),
  http.get("/api/files", () => HttpResponse.json([])),
  http.get("/api/sequences", () => HttpResponse.json({})),
];

export const server = setupServer(...apiHandlers);
```

- [ ] **Step 8: Write the failing test for `src/lib/format.ts`**

`src/lib/format.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { formatPs, formatCount, roleLabel } from "./format";

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
  it("labels empty role as Unknown", () => {
    expect(roleLabel("")).toBe("Unknown");
    expect(roleLabel("production")).toBe("production");
  });
});
```

- [ ] **Step 9: Run the test to verify it fails**

Run: `cd ambermeta/gui/frontend && npx vitest run src/lib/format.test.ts`
Expected: FAIL — cannot find module `./format`.

- [ ] **Step 10: Implement `src/lib/format.ts`**

```ts
export function formatPs(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `${v} ps`;
}

export function formatCount(n: number | null): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US");
}

export function roleLabel(role: string): string {
  return role ? role : "Unknown";
}
```

- [ ] **Step 11: Run the test to verify it passes**

Run: `cd ambermeta/gui/frontend && npx vitest run src/lib/format.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 12: Verify offline + commit**

Run (expect no output): `cd ambermeta/gui/frontend && grep -ri "googleapis\|gstatic\|unpkg" index.html src; echo "clean=$?"` (the grep finding nothing = clean).
Then:
```bash
git add ambermeta/gui/frontend/package.json ambermeta/gui/frontend/package-lock.json ambermeta/gui/frontend/index.html ambermeta/gui/frontend/tailwind.config.js ambermeta/gui/frontend/vite.config.ts ambermeta/gui/frontend/src/main.tsx ambermeta/gui/frontend/src/index.css ambermeta/gui/frontend/src/test ambermeta/gui/frontend/src/lib
git commit -m "feat(gui): B2 tooling — design tokens, bundled fonts, vitest+msw harness (Task 1)"
```

---

## Task 2: TS types + typed API client

**Files:**
- Create: `src/types/index.ts`, `src/api/client.ts`, `src/api/client.test.ts`

**Interfaces:**
- Consumes: Task 1 (test harness, msw `server`).
- Produces:
  - `src/types/index.ts` exporting all the API types from Global Constraints (`StageModel`, `GlobalSettings`, `DocumentResponse`, `SaveResult`, `PreviewResponse`, `ValidationReport`, `StageIssue`, `FileInfo`, `FileMetadata`) plus `FileType`/`StageRole` string-literal unions, `FILE_TYPE_CONFIG`, `STAGE_ROLE_CONFIG`, and request types `StageCreate`, `StageUpdate`, `SettingsPatch`, `ExportFormat`.
  - `src/api/client.ts` exporting an `api` object with one method per B1 endpoint (exact signatures in Step 3).

**Design notes:**
- `FILE_TYPE_CONFIG`/`STAGE_ROLE_CONFIG` carry only **functional** display data (label, lucide icon name, semantic color token) — no decorative colors. Port the structure from the old `types/index.ts` but map colors to the new token names.
- The client throws a typed `ApiError` (with `status` + server `detail`) on non-2xx so hooks can surface clean messages.

- [ ] **Step 1: Write the failing test** (`src/api/client.test.ts`)

```ts
import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { api, ApiError } from "./client";

describe("api client", () => {
  it("GET /document returns the document", async () => {
    const doc = await api.getDocument();
    expect(doc.base_directory).toBe("/work");
    expect(doc.stages).toEqual([]);
  });

  it("POST /document/open posts the path and returns a document", async () => {
    server.use(
      http.post("/api/document/open", async ({ request }) => {
        const body = (await request.json()) as { path: string };
        expect(body.path).toBe("/work/p.yaml");
        return HttpResponse.json({ ...emptyDocument, manifest_path: "/work/p.yaml" });
      })
    );
    const doc = await api.openDocument("/work/p.yaml");
    expect(doc.manifest_path).toBe("/work/p.yaml");
  });

  it("throws ApiError with status + detail on 4xx", async () => {
    server.use(
      http.post("/api/document/open", () =>
        HttpResponse.json({ detail: "Could not read manifest: bad" }, { status: 400 })
      )
    );
    await expect(api.openDocument("/work/bad.yaml")).rejects.toMatchObject({
      status: 400,
      detail: "Could not read manifest: bad",
    });
    await expect(api.openDocument("/work/bad.yaml")).rejects.toBeInstanceOf(ApiError);
  });

  it("save returns a SaveResult with warnings", async () => {
    server.use(
      http.post("/api/document/save", () =>
        HttpResponse.json({ document: emptyDocument, warnings: ["w"] })
      )
    );
    const res = await api.saveDocument({ path: "/work/p.csv", format: "csv" });
    expect(res.warnings).toEqual(["w"]);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ambermeta/gui/frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — cannot find `./client`.

- [ ] **Step 3: Implement `src/types/index.ts`**

```ts
export type FileType = "prmtop" | "mdin" | "mdout" | "mdcrd" | "inpcrd" | "folder" | "other";
export type StageRole = "minimization" | "heating" | "equilibration" | "production" | "";
export type ExportFormat = "yaml" | "json" | "toml" | "csv";

export interface StageModel {
  id: string;
  name: string;
  role: string;
  prmtop: string | null;
  mdin: string | null;
  mdout: string | null;
  mdcrd: string | null;
  inpcrd: string | null;
  expected_gap_ps: number | null;
  gap_tolerance_ps: number | null;
  notes: string[];
}

export interface GlobalSettings {
  global_prmtop: string | null;
  hmr_prmtop: string | null;
  initial_coordinates: string | null;
  auto_link_restarts: boolean;
  strict_validation: boolean;
  allow_gaps: boolean;
  use_relative_paths: boolean;
}

export interface DocumentResponse {
  base_directory: string;
  manifest_path: string | null;
  dirty: boolean;
  can_undo: boolean;
  can_redo: boolean;
  settings: GlobalSettings;
  stages: StageModel[];
}

export interface SaveResult { document: DocumentResponse; warnings: string[]; }
export interface PreviewResponse { content: string; warnings: string[]; format: string; }

export interface MissingFile { kind: string; path: string; }
export interface StageIssue {
  name: string; ok: boolean; degraded: boolean;
  errors: string[]; warnings: string[]; info: string[]; missing_files: MissingFile[];
}
export interface ValidationReport {
  ok: boolean;
  totals: { steps: number; time_ps: number; stage_count: number };
  protocol_issues: string[];
  stage_issues: StageIssue[];
}

export interface FileInfo {
  path: string; name: string; file_type: FileType; is_directory: boolean;
  size: number | null; extension: string | null; parent: string | null;
  children: FileInfo[] | null;
}
export interface FileMetadata {
  file_path: string; file_type: FileType;
  metadata: { details: Record<string, unknown> | null; warnings: string[]; kind: string };
  warnings: string[];
}

export interface StageFilesPatch {
  prmtop?: string | null; mdin?: string | null; mdout?: string | null;
  mdcrd?: string | null; inpcrd?: string | null;
}
export interface StageCreate {
  name: string; role?: StageRole; files?: StageFilesPatch;
  expected_gap_ps?: number | null; gap_tolerance_ps?: number | null; notes?: string[];
}
export interface StageUpdate {
  name?: string; role?: StageRole; files?: StageFilesPatch;
  expected_gap_ps?: number | null; gap_tolerance_ps?: number | null; notes?: string[];
}
export interface SettingsPatch {
  global_prmtop?: string | null; hmr_prmtop?: string | null; initial_coordinates?: string | null;
  auto_link_restarts?: boolean; strict_validation?: boolean; allow_gaps?: boolean;
  use_relative_paths?: boolean;
}

// Functional display config only (icon name = lucide; color = token name).
export const FILE_TYPE_CONFIG: Record<FileType, { label: string; icon: string; color: string }> = {
  prmtop: { label: "Topology", icon: "Atom", color: "ink" },
  mdin:   { label: "Input",    icon: "FileInput", color: "ink" },
  mdout:  { label: "Output",   icon: "FileOutput", color: "ink" },
  mdcrd:  { label: "Trajectory", icon: "Film", color: "ink" },
  inpcrd: { label: "Coordinates", icon: "Move3d", color: "ink" },
  folder: { label: "Folder",   icon: "Folder", color: "ink-muted" },
  other:  { label: "File",     icon: "File", color: "ink-muted" },
};

export const STAGE_ROLE_CONFIG: Record<string, { label: string }> = {
  minimization: { label: "Minimization" },
  heating: { label: "Heating" },
  equilibration: { label: "Equilibration" },
  production: { label: "Production" },
  "": { label: "Unknown" },
};
```

- [ ] **Step 4: Implement `src/api/client.ts`**

```ts
import type {
  DocumentResponse, SaveResult, PreviewResponse, ValidationReport,
  GlobalSettings, FileInfo, FileMetadata, StageCreate, StageUpdate,
  SettingsPatch, ExportFormat,
} from "@/types";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const api = {
  getDocument: () => request<DocumentResponse>("/document"),
  openDocument: (path: string) => post<DocumentResponse>("/document/open", { path }),
  saveDocument: (args: { path?: string; format?: ExportFormat }) =>
    post<SaveResult>("/document/save", args),
  previewDocument: (format: ExportFormat) =>
    post<PreviewResponse>("/document/preview", { format }),
  discover: (args: { recursive: boolean; pattern?: string }) =>
    post<DocumentResponse>("/document/discover", args),

  createStage: (stage: StageCreate) => post<DocumentResponse>("/stages", stage),
  updateStage: (id: string, update: StageUpdate) =>
    put<DocumentResponse>(`/stages/${id}`, update),
  deleteStage: (id: string) =>
    request<DocumentResponse>(`/stages/${id}`, { method: "DELETE" }),
  reorderStages: (stage_ids: string[]) =>
    post<DocumentResponse>("/stages/reorder", { stage_ids }),
  bulkUpdateStages: (stage_ids: string[], update: StageUpdate) =>
    put<DocumentResponse>("/stages/bulk", { stage_ids, update }),

  getSettings: () => request<GlobalSettings>("/settings"),
  updateSettings: (patch: SettingsPatch) => put<DocumentResponse>("/settings", patch),

  undo: () => post<DocumentResponse>("/undo"),
  redo: () => post<DocumentResponse>("/redo"),

  validate: () => post<ValidationReport>("/validate"),
  linkRestarts: () => post<DocumentResponse>("/link-restarts"),

  listFiles: (args: { path?: string; recursive?: boolean; include_all?: boolean }) => {
    const q = new URLSearchParams();
    if (args.path) q.set("path", args.path);
    if (args.recursive !== undefined) q.set("recursive", String(args.recursive));
    if (args.include_all !== undefined) q.set("include_all", String(args.include_all));
    return request<FileInfo[]>(`/files?${q.toString()}`);
  },
  fileMetadata: (path: string) =>
    request<FileMetadata>(`/files/metadata?path=${encodeURIComponent(path)}`),
  relatedFiles: (stem: string) =>
    request<Record<string, string>>(`/files/related/${encodeURIComponent(stem)}`),
  sequences: () => request<Record<string, string[]>>("/sequences"),
};
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd ambermeta/gui/frontend && npx vitest run src/api/client.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add ambermeta/gui/frontend/src/types ambermeta/gui/frontend/src/api/client.ts ambermeta/gui/frontend/src/api/client.test.ts
git commit -m "feat(gui): B2 typed API client + B1-matching TS types (Task 2)"
```

---

## Task 3: react-query hooks (server-authoritative state)

**Files:**
- Create: `src/api/queryClient.ts`, `src/api/hooks.ts`, `src/api/hooks.test.tsx`

**Interfaces:**
- Consumes: Task 2 (`api`, types), Task 1 (msw harness).
- Produces:
  - `src/api/queryClient.ts`: `queryClient` (a `QueryClient`), `DOCUMENT_KEY = ["document"] as const`, `setDocument(doc: DocumentResponse): void` (writes the cache).
  - `src/api/hooks.ts`:
    - `useDocument()` → `UseQueryResult<DocumentResponse>`
    - mutation hooks, each calling the matching `api.*` and on success writing the returned `DocumentResponse` into the cache via `setDocument` (those returning `SaveResult` write `result.document`): `useOpen()`, `useSave()`, `useDiscover()`, `useCreateStage()`, `useUpdateStage()`, `useDeleteStage()`, `useReorder()`, `useBulkUpdate()`, `useUpdateSettings()`, `useUndo()`, `useRedo()`, `useLinkRestarts()`
    - non-document queries: `useFiles(args)`, `useFileMetadata(path | null)`, `useSequences()`
    - `useValidate()` (mutation returning `ValidationReport`; does NOT touch the document cache)
    - `usePreview()` (mutation returning `PreviewResponse`)

**Design notes:**
- Every document-mutating hook funnels through a shared `onSuccess: (doc) => setDocument(doc)` so the UI re-renders from one authoritative cache entry. This is the mechanism that keeps undo/redo and dirty correct without a client mirror.
- `useFileMetadata(path)` is `enabled: !!path` so it only fetches when a file is selected.
- Mutations expose `mutate`/`mutateAsync`, `isPending`, `error` (an `ApiError`) for the UI to show inline messages.

- [ ] **Step 1: Write the failing test** (`src/api/hooks.test.tsx`)

```tsx
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "./queryClient";
import { useDocument, useCreateStage } from "./hooks";
import type { ReactNode } from "react";

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("react-query hooks", () => {
  beforeEach(() => queryClient.clear()); // singleton cache — clear between tests to avoid leakage

  it("useDocument loads the document", async () => {
    const { result } = renderHook(() => useDocument(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.base_directory).toBe("/work");
  });

  it("createStage writes the returned document into the cache", async () => {
    const withStage = {
      ...emptyDocument, dirty: true,
      stages: [{ ...stageFixture, id: "abc", name: "min" }],
    };
    server.use(http.post("/api/stages", () => HttpResponse.json(withStage)));

    // Render BOTH hooks in ONE tree so the mutation and the query share the same
    // React reconciliation — the cache update propagates within act(). (Two separate
    // renderHook trees race the cross-tree cache notification and waitFor flakes.)
    const { result } = renderHook(
      () => ({ doc: useDocument(), create: useCreateStage() }),
      { wrapper }
    );
    await waitFor(() => expect(result.current.doc.isSuccess).toBe(true));
    await act(async () => { await result.current.create.mutateAsync({ name: "min" }); });

    await waitFor(() =>
      expect(result.current.doc.data?.stages.map((s) => s.name)).toEqual(["min"])
    );
    expect(result.current.doc.data?.dirty).toBe(true);
  });
});

const stageFixture = {
  id: "", name: "", role: "", prmtop: null, mdin: null, mdout: null,
  mdcrd: null, inpcrd: null, expected_gap_ps: null, gap_tolerance_ps: null, notes: [],
};
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ambermeta/gui/frontend && npx vitest run src/api/hooks.test.tsx`
Expected: FAIL — cannot find `./queryClient` / `./hooks`.

- [ ] **Step 3: Implement `src/api/queryClient.ts`**

```ts
import { QueryClient } from "@tanstack/react-query";
import type { DocumentResponse } from "@/types";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

export const DOCUMENT_KEY = ["document"] as const;

export function setDocument(doc: DocumentResponse): void {
  queryClient.setQueryData(DOCUMENT_KEY, doc);
}
```

- [ ] **Step 4: Implement `src/api/hooks.ts`**

```ts
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "./client";
import { DOCUMENT_KEY, queryClient, setDocument } from "./queryClient";
import type {
  DocumentResponse, SaveResult, StageCreate, StageUpdate, SettingsPatch,
  ExportFormat,
} from "@/types";

export function useDocument() {
  return useQuery({ queryKey: DOCUMENT_KEY, queryFn: api.getDocument });
}

function docMutation<V>(fn: (v: V) => Promise<DocumentResponse>) {
  return useMutation({ mutationFn: fn, onSuccess: (doc) => setDocument(doc) });
}

export const useOpen = () => docMutation((path: string) => api.openDocument(path));
export const useDiscover = () =>
  docMutation((a: { recursive: boolean; pattern?: string }) => api.discover(a));
export const useCreateStage = () => docMutation((s: StageCreate) => api.createStage(s));
export const useUpdateStage = () =>
  docMutation((a: { id: string; update: StageUpdate }) => api.updateStage(a.id, a.update));
export const useDeleteStage = () => docMutation((id: string) => api.deleteStage(id));
export const useReorder = () => docMutation((ids: string[]) => api.reorderStages(ids));
export const useBulkUpdate = () =>
  docMutation((a: { ids: string[]; update: StageUpdate }) =>
    api.bulkUpdateStages(a.ids, a.update));
export const useUpdateSettings = () => docMutation((p: SettingsPatch) => api.updateSettings(p));
export const useUndo = () => docMutation((_: void) => api.undo());
export const useRedo = () => docMutation((_: void) => api.redo());
export const useLinkRestarts = () => docMutation((_: void) => api.linkRestarts());

export const useSave = () =>
  useMutation({
    mutationFn: (a: { path?: string; format?: ExportFormat }) => api.saveDocument(a),
    onSuccess: (res: SaveResult) => setDocument(res.document),
  });

export const useValidate = () => useMutation({ mutationFn: () => api.validate() });
export const usePreview = () =>
  useMutation({ mutationFn: (format: ExportFormat) => api.previewDocument(format) });

export function useFiles(args: { path?: string; recursive?: boolean; include_all?: boolean }) {
  // Spread the args into the key (not the object) so identical values hit the cache
  // regardless of object identity.
  return useQuery({
    queryKey: ["files", args.path ?? null, args.recursive ?? null, args.include_all ?? null],
    queryFn: () => api.listFiles(args),
  });
}

export function useFileMetadata(path: string | null) {
  return useQuery({
    queryKey: ["file-metadata", path],
    queryFn: () => {
      if (!path) return Promise.reject(new Error("file path required"));
      return api.fileMetadata(path);
    },
    enabled: !!path,
  });
}

export function useSequences() {
  return useQuery({ queryKey: ["sequences"], queryFn: api.sequences });
}

// Re-export for tests/consumers that need to reset between renders.
export { queryClient, DOCUMENT_KEY };
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd ambermeta/gui/frontend && npx vitest run src/api/hooks.test.tsx`
Expected: PASS (2 tests). (If the cache leaks between the two tests, add `queryClient.clear()` in a `beforeEach` in the test file.)

- [ ] **Step 6: Commit**

```bash
git add ambermeta/gui/frontend/src/api/queryClient.ts ambermeta/gui/frontend/src/api/hooks.ts ambermeta/gui/frontend/src/api/hooks.test.tsx
git commit -m "feat(gui): B2 react-query hooks — single document cache, mutation funnel (Task 3)"
```

---

## Task 4: App shell, top bar (actions/dirty/undo-redo), common components

**Files:**
- Create: `src/App.tsx`, `src/components/TopBar/TopBar.tsx`, `src/components/common/Button.tsx`, `src/components/common/Modal.tsx`, `src/components/common/Badge.tsx`, `src/components/common/index.ts`, `src/state/selection.tsx`, `src/lib/usePersistentSize.ts`, `src/App.test.tsx`
- Port verbatim from the OLD frontend (copy file, no logic change): `src/components/common/ResizeHandle.tsx`, `src/components/common/Icons.tsx`

**Interfaces:**
- Consumes: Task 3 hooks (`useDocument`, `useUndo`, `useRedo`).
- Produces:
  - `state/selection.tsx`: `SelectionProvider`, `useSelection()` → `{ selectedId: string|null; selectedIds: string[]; select(id, opts?): void; clear(): void; selectedFile: string|null; selectFile(path: string|null): void }` (UI-only).
  - `lib/usePersistentSize.ts`: `usePersistentSize(key: string, initial: number): [number, (n: number) => void]` (localStorage-backed).
  - `common/Button.tsx`: `<Button variant="primary"|"ghost"|"danger" disabled? onClick?>` (text-label buttons; primary = accent).
  - `common/Modal.tsx`: `<Modal open title onClose>children</Modal>` (focus-trapped, Esc closes, backdrop).
  - `common/Badge.tsx`: `<Badge tone="neutral"|"valid"|"warning"|"error">` (small status pill).
  - `TopBar.tsx`: `<TopBar onOpen onSave onDiscover onExport onValidate />` — action buttons + dirty dot + Undo/Redo (wired here); the modal-bearing handlers are passed in (Task 10 supplies them; Task 4 passes no-op stubs so the shell renders).
  - `App.tsx`: the 3-pane shell.

**Design notes:**
- Undo/Redo live in the top bar and call `useUndo()`/`useRedo()`; disabled per `doc.can_undo`/`doc.can_redo`. Dirty indicator = a small `accent` dot when `doc.dirty`.
- Panel widths via `usePersistentSize("files-w", 280)` and `usePersistentSize("props-w", 340)`; the center pane flexes.
- Wrap the panes in `SelectionProvider`.

- [ ] **Step 1: Port the two reusable components**

Copy `ResizeHandle.tsx` and `Icons.tsx` from the old tree into `src/components/common/` unchanged (no store/API coupling). Confirm `Icons.tsx`'s `FileIcon` maps `FileType` → lucide icon; if it referenced old color names, map them to token classes (`text-ink`, `text-ink-muted`). `FileIcon` must accept a `type: FileType` prop (used by FileBrowser in Task 5).

- [ ] **Step 2: Write the failing shell test** (`src/App.test.tsx`)

```tsx
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import App from "./App";

function renderApp() {
  queryClient.clear();
  return render(
    <QueryClientProvider client={queryClient}><App /></QueryClientProvider>
  );
}

describe("App shell", () => {
  it("renders three panes and the top bar actions", async () => {
    renderApp();
    await waitFor(() => expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Validate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discover" })).toBeInTheDocument();
    expect(screen.getByTestId("pane-files")).toBeInTheDocument();
    expect(screen.getByTestId("pane-stages")).toBeInTheDocument();
    expect(screen.getByTestId("pane-properties")).toBeInTheDocument();
  });

  it("disables undo/redo per the document flags and shows dirty", async () => {
    server.use(
      http.get("/api/document", () =>
        HttpResponse.json({ ...emptyDocument, dirty: true, can_undo: true, can_redo: false })
      )
    );
    renderApp();
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "Redo" })).toBeDisabled();
    expect(screen.getByTestId("dirty-indicator")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd ambermeta/gui/frontend && npx vitest run src/App.test.tsx`
Expected: FAIL — cannot find `./App`.

- [ ] **Step 4: Implement the common components**

`src/components/common/Button.tsx`:
```tsx
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost" | "danger";
const styles: Record<Variant, string> = {
  primary: "bg-accent text-white hover:brightness-110",
  ghost: "bg-transparent text-ink hover:bg-app border border-hairline",
  danger: "bg-transparent text-error hover:bg-app border border-hairline",
};

export function Button(
  { variant = "ghost", className = "", ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }
) {
  return (
    <button
      {...props}
      className={`px-3 py-1.5 rounded text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed ${styles[variant]} ${className}`}
    />
  );
}
```

`src/components/common/Badge.tsx`:
```tsx
import type { ReactNode } from "react";

type Tone = "neutral" | "valid" | "warning" | "error";
const tones: Record<Tone, string> = {
  neutral: "bg-app text-ink-secondary border-hairline",
  valid: "bg-app text-valid border-valid/30",
  warning: "bg-app text-warning border-warning/30",
  error: "bg-app text-error border-error/30",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded border text-xs ${tones[tone]}`}>
      {children}
    </span>
  );
}
```

`src/components/common/Modal.tsx`:
```tsx
import { useEffect, useRef, type ReactNode } from "react";

export function Modal(
  { open, title, onClose, children }:
  { open: boolean; title: string; onClose: () => void; children: ReactNode }
) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key !== "Tab" || !ref.current) return;
      // Trap Tab focus within the dialog (a11y for modal dialogs).
      const f = ref.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (f.length === 0) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/20"
         onMouseDown={onClose}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-label={title}
           onMouseDown={(e) => e.stopPropagation()}
           className="bg-surface border border-hairline rounded-lg shadow-lg w-[min(560px,92vw)] max-h-[85vh] overflow-auto outline-none">
        <header className="px-4 py-3 border-b border-hairline font-semibold">{title}</header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}
```

`src/components/common/index.ts`:
```ts
export { Button } from "./Button";
export { Badge } from "./Badge";
export { Modal } from "./Modal";
export { ResizeHandle } from "./ResizeHandle";
export * from "./Icons";
```

- [ ] **Step 5: Implement selection context + persistent size**

`src/state/selection.tsx`:
```tsx
import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

interface SelectionCtx {
  selectedId: string | null;
  selectedIds: string[];
  select: (id: string, opts?: { additive?: boolean }) => void;
  clear: () => void;
  selectedFile: string | null;
  selectFile: (path: string | null) => void;
}
const Ctx = createContext<SelectionCtx | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [selectedIds, setIds] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const select = useCallback((id: string, opts?: { additive?: boolean }) => {
    setIds((prev) =>
      opts?.additive
        ? prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
        : [id]
    );
  }, []);
  const clear = useCallback(() => setIds([]), []);
  const value: SelectionCtx = {
    selectedId: selectedIds.length ? selectedIds[selectedIds.length - 1] : null,
    selectedIds, select, clear,
    selectedFile, selectFile: setSelectedFile,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSelection(): SelectionCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSelection must be used within SelectionProvider");
  return v;
}
```

`src/lib/usePersistentSize.ts`:
```ts
import { useCallback, useState } from "react";

export function usePersistentSize(key: string, initial: number): [number, (n: number) => void] {
  const [size, setSize] = useState<number>(() => {
    const raw = localStorage.getItem(key);
    const n = raw ? Number(raw) : NaN;
    return Number.isFinite(n) ? n : initial;
  });
  const set = useCallback((n: number) => {
    setSize(n);
    localStorage.setItem(key, String(n));
  }, [key]);
  return [size, set];
}
```

- [ ] **Step 6: Implement the TopBar** (`src/components/TopBar/TopBar.tsx`)

```tsx
import { Button } from "@/components/common";
import { Undo2, Redo2 } from "lucide-react";
import { useDocument, useUndo, useRedo } from "@/api/hooks";

interface Props {
  onOpen: () => void;
  onSave: () => void;
  onDiscover: () => void;
  onRelink: () => void;
  onExport: () => void;
  onValidate: () => void;
}

export function TopBar({ onOpen, onSave, onDiscover, onRelink, onExport, onValidate }: Props) {
  const { data: doc } = useDocument();
  const undo = useUndo();
  const redo = useRedo();
  const dirty = !!doc?.dirty;
  return (
    <header className="flex items-center gap-2 px-3 h-12 border-b border-hairline bg-surface">
      <span className="font-semibold mr-2">AmberMeta</span>
      <Button onClick={onOpen}>Open</Button>
      <Button variant="primary" onClick={onSave}>Save</Button>
      {dirty && <span data-testid="dirty-indicator" title="Unsaved changes"
                      className="w-2 h-2 rounded-full bg-accent" />}
      <span className="flex-1" />
      <Button onClick={onDiscover}>Discover</Button>
      <Button onClick={onRelink}>Re-link restarts</Button>
      <Button onClick={onValidate}>Validate</Button>
      <Button onClick={onExport}>Export</Button>
      <Button aria-label="Undo" disabled={!doc?.can_undo} onClick={() => undo.mutate()}>
        <Undo2 size={16} />
      </Button>
      <Button aria-label="Redo" disabled={!doc?.can_redo} onClick={() => redo.mutate()}>
        <Redo2 size={16} />
      </Button>
    </header>
  );
}
```

- [ ] **Step 7: Implement the App shell** (`src/App.tsx`)

```tsx
import { SelectionProvider } from "@/state/selection";
import { ResizeHandle } from "@/components/common";
import { usePersistentSize } from "@/lib/usePersistentSize";
import { TopBar } from "@/components/TopBar/TopBar";
import { FileBrowser } from "@/components/FileBrowser/FileBrowser";
import { StageList } from "@/components/StageList/StageList";
import { PropertiesPanel } from "@/components/PropertiesPanel/PropertiesPanel";

export default function App() {
  const [filesW, setFilesW] = usePersistentSize("files-w", 280);
  const [propsW, setPropsW] = usePersistentSize("props-w", 340);
  const noop = () => {};
  return (
    <SelectionProvider>
      <div className="flex flex-col h-full">
        <TopBar onOpen={noop} onSave={noop} onDiscover={noop} onRelink={noop} onExport={noop} onValidate={noop} />
        <div className="flex flex-1 min-h-0">
          <div data-testid="pane-files" style={{ width: filesW }}
               className="shrink-0 border-r border-hairline overflow-auto bg-surface">
            <FileBrowser />
          </div>
          <ResizeHandle direction="left" currentWidth={filesW} onResize={setFilesW} min={200} max={480} />
          <div data-testid="pane-stages" className="flex-1 min-w-0 overflow-hidden">
            <StageList />
          </div>
          <ResizeHandle direction="right" currentWidth={propsW} onResize={setPropsW} min={260} max={520} />
          <div data-testid="pane-properties" style={{ width: propsW }}
               className="shrink-0 border-l border-hairline overflow-auto bg-surface">
            <PropertiesPanel />
          </div>
        </div>
      </div>
    </SelectionProvider>
  );
}
```

NOTE: `FileBrowser`/`StageList`/`PropertiesPanel` are built in Tasks 5–7. To make THIS task's test pass before those exist, create minimal placeholder components in this task that render a labelled empty `<div>` (e.g. `export function FileBrowser(){return <div>Files</div>;}` in `src/components/FileBrowser/FileBrowser.tsx`, same for `StageList`/`PropertiesPanel`), and their `index.ts` barrels. Tasks 5–7 overwrite them. Verify `ResizeHandle`'s prop names (`direction`/`currentWidth`/`onResize`/`min`/`max`) match the ported component; adjust the call sites if the ported signature differs.

- [ ] **Step 8: Run the shell test to verify it passes**

Run: `cd ambermeta/gui/frontend && npx vitest run src/App.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 9: Commit**

```bash
git add ambermeta/gui/frontend/src/App.tsx ambermeta/gui/frontend/src/App.test.tsx ambermeta/gui/frontend/src/components/TopBar ambermeta/gui/frontend/src/components/common ambermeta/gui/frontend/src/state ambermeta/gui/frontend/src/lib/usePersistentSize.ts ambermeta/gui/frontend/src/components/FileBrowser ambermeta/gui/frontend/src/components/StageList ambermeta/gui/frontend/src/components/PropertiesPanel
git commit -m "feat(gui): B2 app shell, top bar (undo/redo/dirty), common components (Task 4)"
```

---

## Task 5: Files panel (tree + drag + search + metadata preview)

**Files:**
- Create/replace: `src/components/FileBrowser/FileBrowser.tsx`, `src/components/FileBrowser/index.ts`, `src/components/FileBrowser/FileBrowser.test.tsx`

**Interfaces:**
- Consumes: `useFiles`, `useFileMetadata` (Task 3); `useSelection` (Task 4); `FileIcon` (common).
- Produces: `<FileBrowser/>` — the Files pane.

**Design notes:**
- Tree from `useFiles({ recursive: true })`; a search box filters by name (case-insensitive, flattening the tree to matching files). Each file is `@dnd-kit` `useDraggable` (id = `file:${path}`) so it can be dropped onto stage slots in Task 6.
- Selecting a file calls `selectFile(path)`; a **metadata preview** strip at the bottom shows `useFileMetadata(selectedFile)` details (read from `metadata.details`), so files are assigned with confidence. Show a "Reading…" state while pending and parser warnings if present.
- Icons functional only (file-type glyph via `FileIcon`). No decorative icons.

- [ ] **Step 1: Write the failing test** (`src/components/FileBrowser/FileBrowser.test.tsx`)

```tsx
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { FileBrowser } from "./FileBrowser";

function renderFB() {
  queryClient.clear();
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider><DndContext><FileBrowser /></DndContext></SelectionProvider>
    </QueryClientProvider>
  );
}

const files = [
  { path: "/work/system.prmtop", name: "system.prmtop", file_type: "prmtop",
    is_directory: false, size: 100, extension: ".prmtop", parent: "/work", children: null },
  { path: "/work/prod.mdin", name: "prod.mdin", file_type: "mdin",
    is_directory: false, size: 50, extension: ".mdin", parent: "/work", children: null },
];

describe("FileBrowser", () => {
  it("lists files and filters by search", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(files)));
    renderFB();
    await waitFor(() => expect(screen.getByText("system.prmtop")).toBeInTheDocument());
    expect(screen.getByText("prod.mdin")).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText(/search/i), "prod");
    expect(screen.queryByText("system.prmtop")).not.toBeInTheDocument();
    expect(screen.getByText("prod.mdin")).toBeInTheDocument();
  });

  it("shows metadata on selecting a file", async () => {
    server.use(
      http.get("/api/files", () => HttpResponse.json(files)),
      http.get("/api/files/metadata", () =>
        HttpResponse.json({
          file_path: "/work/prod.mdin", file_type: "mdin",
          metadata: { details: { dt: 0.002, length_steps: 1000 }, warnings: [], kind: "mdin" },
          warnings: [],
        })
      )
    );
    renderFB();
    await waitFor(() => expect(screen.getByText("prod.mdin")).toBeInTheDocument());
    await userEvent.click(screen.getByText("prod.mdin"));
    await waitFor(() => expect(screen.getByTestId("file-metadata")).toHaveTextContent("0.002"));
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/FileBrowser/FileBrowser.test.tsx`
Expected: FAIL — the Task-4 placeholder renders only "Files".

- [ ] **Step 3: Implement `FileBrowser.tsx`**

```tsx
import { useMemo, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { useFiles, useFileMetadata } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { FileIcon } from "@/components/common";
import type { FileInfo } from "@/types";

function flatten(nodes: FileInfo[], q: string): FileInfo[] {
  const out: FileInfo[] = [];
  const walk = (n: FileInfo) => {
    if (!n.is_directory && n.name.toLowerCase().includes(q)) out.push(n);
    n.children?.forEach(walk);
  };
  nodes.forEach(walk);
  return out;
}

function DraggableFile({ file, onSelect, selected }:
  { file: FileInfo; onSelect: () => void; selected: boolean }) {
  const { attributes, listeners, setNodeRef } = useDraggable({ id: `file:${file.path}` });
  return (
    <button
      ref={setNodeRef} {...listeners} {...attributes}
      onClick={onSelect}
      className={`flex items-center gap-2 w-full px-2 py-1 text-left text-sm rounded
        ${selected ? "bg-accent-subtle" : "hover:bg-app"}`}
    >
      <FileIcon type={file.file_type} />
      <span className="truncate">{file.name}</span>
    </button>
  );
}

export function FileBrowser() {
  const [q, setQ] = useState("");
  const { data: tree = [] } = useFiles({ recursive: true });
  const { selectedFile, selectFile } = useSelection();
  const { data: meta, isPending: metaPending } = useFileMetadata(selectedFile);

  const files = useMemo(() => flatten(tree, q.toLowerCase()), [tree, q]);

  return (
    <div className="flex flex-col h-full">
      <div className="p-2 border-b border-hairline">
        <input
          value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Search files"
          className="w-full px-2 py-1 text-sm border border-hairline rounded bg-app"
        />
      </div>
      <div className="flex-1 overflow-auto p-1">
        {files.map((f) => (
          <DraggableFile key={f.path} file={f}
            selected={selectedFile === f.path}
            onSelect={() => selectFile(f.path)} />
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

`src/components/FileBrowser/index.ts`: `export { FileBrowser } from "./FileBrowser";`

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/FileBrowser/FileBrowser.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/FileBrowser
git commit -m "feat(gui): B2 Files panel — tree, drag, search, metadata preview (Task 5)"
```

---

## Task 6: Stages panel (virtualized list + sequence grouping + sortable + drop zones)

**Files:**
- Create/replace: `src/components/StageList/StageList.tsx`, `src/components/StageList/StageCard.tsx`, `src/components/StageList/FileDropZone.tsx`, `src/components/StageList/reorder.ts`, `src/components/StageList/index.ts`, `src/components/StageList/StageList.test.tsx`, `src/components/StageList/reorder.test.ts`

**Interfaces:**
- Consumes: `useDocument`, `useReorder`, `useUpdateStage`, `useBulkUpdate`, `useSequences`, `useCreateStage` (Task 3); `useSelection` (Task 4); `FileIcon`, `Badge` (common); `formatPs`, `roleLabel` (Task 1).
- Produces:
  - `reorder.ts`: `reorderIds(ids: string[], activeId: string, overId: string): string[]` (pure — moves `activeId` to `overId`'s position).
  - `<StageList/>`, `<StageCard stage isSelected onSelect/>`, `<FileDropZone stageId kind current onDrop/>`.

**Design notes:**
- **Sequence grouping:** `useSequences()` returns `base → ordered ids`. Build a render model: stages belonging to a sequence with ≥2 members render under a collapsible group header (`base · N runs`, with a group-level role selector that bulk-sets the role for the whole sequence); ungrouped stages render flat. Collapsed groups render a single summary row (so 50 prod runs collapse to one line).
- **Virtualization:** when the number of *rendered rows* exceeds `VIRTUALIZE_THRESHOLD = 50`, window the flat row list with `@tanstack/react-virtual` (`useVirtualizer`, `estimateSize: () => 64`, the pane's scroll element as `getScrollElement`). Below the threshold, render all rows directly (keeps small-protocol tests simple and avoids jsdom measurement issues).
- **Drag-to-reorder:** wrap rows in a `@dnd-kit` `SortableContext`; `onDragEnd` computes the new order with `reorderIds(...)` and calls `useReorder().mutate(newIds)`. (Reorder *logic* is unit-tested via `reorderIds`; dnd pointer simulation is not attempted in jsdom.)
- **Drop-to-assign:** each `StageCard` file slot is a `FileDropZone` (`useDroppable` id `slot:${stageId}:${kind}`) that accepts a `file:${path}` draggable from the Files pane and calls `useUpdateStage` to set that kind. (Reuse the dnd ids defined in Task 5.)
- **Continuity shown quietly:** a stage whose `expected_gap_ps`/`gap_tolerance_ps` is set, or that follows another stage, shows the gap inline as plain text — `+{n} ps gap` in `text-warning` when a positive gap exists, nothing when continuous. (Observed-gap detail comes from validation in Task 9; here show the *configured* expected gap.)
- Selection: clicking a card calls `select(id)` (additive with ctrl/meta). The selected card gets `bg-accent-subtle`.

- [ ] **Step 1: Write the failing pure-helper test** (`src/components/StageList/reorder.test.ts`)

```ts
import { describe, it, expect } from "vitest";
import { reorderIds } from "./reorder";

describe("reorderIds", () => {
  it("moves active before/after over preserving the rest", () => {
    expect(reorderIds(["a", "b", "c", "d"], "d", "b")).toEqual(["a", "d", "b", "c"]);
    expect(reorderIds(["a", "b", "c"], "a", "c")).toEqual(["b", "c", "a"]);
  });
  it("is a no-op when active === over", () => {
    expect(reorderIds(["a", "b"], "a", "a")).toEqual(["a", "b"]);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/StageList/reorder.test.ts`
Expected: FAIL — cannot find `./reorder`.

- [ ] **Step 3: Implement `reorder.ts`**

```ts
export function reorderIds(ids: string[], activeId: string, overId: string): string[] {
  if (activeId === overId) return ids;
  const from = ids.indexOf(activeId);
  const to = ids.indexOf(overId);
  if (from === -1 || to === -1) return ids;
  const next = ids.slice();
  next.splice(from, 1);
  next.splice(to, 0, activeId);
  return next;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/StageList/reorder.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Implement `FileDropZone.tsx`**

```tsx
import { useDroppable } from "@dnd-kit/core";
import { FileIcon } from "@/components/common";
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
  return (
    <div ref={setNodeRef}
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-xs font-mono
        ${isOver ? "border-accent bg-accent-subtle" : "border-hairline"}`}>
      <FileIcon type={KIND_TYPE[kind]} />
      <span className="text-ink-muted">{kind}</span>
      <span className="truncate text-ink">{current ?? "—"}</span>
    </div>
  );
}
```

- [ ] **Step 6: Implement `StageCard.tsx`**

```tsx
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Badge } from "@/components/common";
import { FileDropZone } from "./FileDropZone";
import { roleLabel, formatPs } from "@/lib/format";
import type { StageModel } from "@/types";

const KINDS = ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"] as const;

export function StageCard(
  { stage, index, isSelected, onSelect }:
  { stage: StageModel; index: number; isSelected: boolean; onSelect: (e: React.MouseEvent) => void }
) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: stage.id });
  const style = { transform: CSS.Transform.toString(transform), transition };
  const hasGap = stage.expected_gap_ps != null && stage.expected_gap_ps > 0;
  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}
      onClick={onSelect}
      className={`border-b border-hairline px-3 py-2 cursor-pointer
        ${isSelected ? "bg-accent-subtle" : "hover:bg-app"}`}>
      <div className="flex items-center gap-2">
        <span className="text-xs text-ink-muted w-6 tabular-nums">{index + 1}</span>
        <span className="font-medium truncate flex-1">{stage.name}</span>
        <Badge>{roleLabel(stage.role)}</Badge>
        {hasGap && (
          <span className="text-warning text-xs">+{formatPs(stage.expected_gap_ps)} gap</span>
        )}
      </div>
      <div className="flex flex-wrap gap-1 mt-1 pl-8">
        {KINDS.map((k) => (
          <FileDropZone key={k} stageId={stage.id} kind={k} current={stage[k]} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Write the failing StageList test** (`src/components/StageList/StageList.test.tsx`)

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
import { StageList } from "./StageList";
import type { StageModel } from "@/types";

function mkStage(p: Partial<StageModel>): StageModel {
  return { id: "", name: "", role: "", prmtop: null, mdin: null, mdout: null, mdcrd: null,
    inpcrd: null, expected_gap_ps: null, gap_tolerance_ps: null, notes: [], ...p };
}

function renderList() {
  queryClient.clear();
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider><DndContext><StageList /></DndContext></SelectionProvider>
    </QueryClientProvider>
  );
}

describe("StageList", () => {
  it("renders stages and shows a configured gap inline", async () => {
    server.use(
      http.get("/api/document", () =>
        HttpResponse.json({ ...emptyDocument, stages: [
          mkStage({ id: "1", name: "min", role: "minimization" }),
          mkStage({ id: "2", name: "prod", role: "production", expected_gap_ps: 5 }),
        ] })),
      http.get("/api/sequences", () => HttpResponse.json({})),
    );
    renderList();
    await waitFor(() => expect(screen.getByText("min")).toBeInTheDocument());
    expect(screen.getByText("prod")).toBeInTheDocument();
    expect(screen.getByText(/\+5 ps gap/)).toBeInTheDocument();
  });

  it("collapses a numbered sequence into one summary row", async () => {
    const stages = [1, 2, 3].map((i) =>
      mkStage({ id: String(i), name: `prod_00${i}`, role: "production" }));
    server.use(
      http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, stages })),
      http.get("/api/sequences", () => HttpResponse.json({ prod_: ["1", "2", "3"] })),
    );
    renderList();
    await waitFor(() => expect(screen.getByText(/prod_ · 3 runs/)).toBeInTheDocument());
    // collapsed by default: individual members hidden until expanded
    expect(screen.queryByText("prod_001")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText(/prod_ · 3 runs/));
    await waitFor(() => expect(screen.getByText("prod_001")).toBeInTheDocument());
  });
});
```

- [ ] **Step 8: Run to verify it fails**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/StageList/StageList.test.tsx`
Expected: FAIL — Task-4 placeholder renders only "Stages".

- [ ] **Step 9: Implement `StageList.tsx`**

```tsx
import { useMemo, useRef, useState } from "react";
import {
  DndContext, useSensor, useSensors, PointerSensor, type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { ChevronRight, ChevronDown } from "lucide-react";
import { useDocument, useReorder, useSequences, useBulkUpdate } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { StageCard } from "./StageCard";
import { reorderIds } from "./reorder";
import type { StageModel } from "@/types";

const VIRTUALIZE_THRESHOLD = 50;

interface Group { base: string; ids: string[]; }

export function StageList() {
  const { data: doc } = useDocument();
  const { data: sequences = {} } = useSequences();
  const reorder = useReorder();
  const bulk = useBulkUpdate();
  const { selectedIds, select } = useSelection();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const parentRef = useRef<HTMLDivElement>(null);

  const stages = doc?.stages ?? [];
  const byId = useMemo(() => new Map(stages.map((s) => [s.id, s])), [stages]);

  // Build groups (base → ids with >=2 members) and the set of grouped ids.
  const groups: Group[] = useMemo(
    () => Object.entries(sequences)
      .filter(([, ids]) => ids.length >= 2)
      .map(([base, ids]) => ({ base, ids })),
    [sequences]
  );
  const groupedIds = useMemo(
    () => new Set(groups.flatMap((g) => g.ids)),
    [groups]
  );

  const sensors = useSensors(useSensor(PointerSensor));
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const next = reorderIds(stages.map((s) => s.id), String(e.active.id), String(e.over.id));
    reorder.mutate(next);
  };

  // Flatten the render order: each stage in document order, but a collapsed group
  // renders a single summary row at its first member's position.
  const rows = useMemo(() => {
    const out: ({ type: "stage"; stage: StageModel } | { type: "group"; group: Group })[] = [];
    const emittedGroup = new Set<string>();
    for (const s of stages) {
      const g = groups.find((gr) => gr.ids.includes(s.id));
      if (g) {
        if (!emittedGroup.has(g.base)) {
          out.push({ type: "group", group: g });
          emittedGroup.add(g.base);
        }
        if (!collapsed[g.base]) out.push({ type: "stage", stage: s });
      } else {
        out.push({ type: "stage", stage: s });
      }
    }
    return out;
  }, [stages, groups, collapsed]);

  const toggle = (base: string) => setCollapsed((c) => ({ ...c, [base]: !c[base] }));

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <SortableContext items={stages.map((s) => s.id)} strategy={verticalListSortingStrategy}>
        <div ref={parentRef} className="h-full overflow-auto">
          {rows.length === 0 && (
            <p className="p-4 text-sm text-ink-muted">No stages. Use Discover or drag files in.</p>
          )}
          {rows.map((row, i) =>
            row.type === "group" ? (
              <div key={`g:${row.group.base}`}
                className="flex items-center gap-2 px-3 py-1.5 bg-app border-b border-hairline text-sm">
                <button aria-label="toggle group" onClick={() => toggle(row.group.base)}
                  className="flex items-center gap-1 font-medium">
                  {collapsed[row.group.base] ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                  {row.group.base} · {row.group.ids.length} runs
                </button>
                <span className="flex-1" />
                <select aria-label="group role"
                  className="text-xs border border-hairline rounded bg-surface px-1 py-0.5"
                  defaultValue=""
                  onChange={(e) =>
                    bulk.mutate({ ids: row.group.ids, update: { role: e.target.value as StageModel["role"] } })
                  }>
                  <option value="">set role…</option>
                  <option value="equilibration">equilibration</option>
                  <option value="production">production</option>
                </select>
              </div>
            ) : (
              <StageCard key={row.stage.id} stage={row.stage}
                index={stages.indexOf(row.stage)}
                isSelected={selectedIds.includes(row.stage.id)}
                onSelect={(e) => select(row.stage.id, { additive: e.ctrlKey || e.metaKey })} />
            )
          )}
        </div>
      </SortableContext>
    </DndContext>
  );
  // NOTE: when rows.length > VIRTUALIZE_THRESHOLD, wrap the row map in a
  // @tanstack/react-virtual useVirtualizer over `rows` (estimateSize 64,
  // getScrollElement: () => parentRef.current) and render only virtual items.
  // The grouping/collapse model above is unchanged; only the inner render windows.
}
```

NOTE for the implementer: implement the virtualization branch (the NOTE comment) using `useVirtualizer` from `@tanstack/react-virtual` keyed on `rows.length`; keep the non-virtual branch for `rows.length <= VIRTUALIZE_THRESHOLD` so the component tests above (small lists) exercise the plain path. The `byId`/`groupedIds` memos are available if you refactor; remove any that end up unused to satisfy `noUnusedLocals`.

`src/components/StageList/index.ts`: `export { StageList } from "./StageList";`

- [ ] **Step 10: Run the StageList test to verify it passes**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/StageList/StageList.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 11: Commit**

```bash
git add ambermeta/gui/frontend/src/components/StageList
git commit -m "feat(gui): B2 Stages panel — sequence grouping, sortable, drop zones, gap display (Task 6)"
```

---

## Task 7: Properties panel (draft-edit form + bulk edit + global settings)

**Files:**
- Create/replace: `src/components/PropertiesPanel/PropertiesPanel.tsx`, `src/components/PropertiesPanel/SettingsPanel.tsx`, `src/components/PropertiesPanel/index.ts`, `src/components/PropertiesPanel/PropertiesPanel.test.tsx`

**Interfaces:**
- Consumes: `useDocument`, `useUpdateStage`, `useBulkUpdate`, `useUpdateSettings` (Task 3); `useSelection` (Task 4); `Button` (common).
- Produces: `<PropertiesPanel/>`, `<SettingsPanel settings/>`.

**Design notes:**
- Three modes by selection: **0 selected** → `SettingsPanel` (global/HMR prmtop text fields, the three booleans `strict_validation`/`allow_gaps`/`auto_link_restarts`) committing via `useUpdateSettings`. **1 selected** → the stage form. **≥2 selected** → a bulk-edit form (role + notes applied via `useBulkUpdate`).
- The stage form is **draft local state**, committed on blur / Enter (NOT per keystroke), and **re-synced when `selectedId` changes** (a `useEffect` keyed on `selectedId` resets the draft from the current stage). This is the "commit on blur, re-sync on selection change" rule from the spec.
- Fields: name (text), role (select incl. "" → "Unknown"), expected_gap_ps / gap_tolerance_ps (number), notes (textarea, newline-split). File slots are shown read-only here (assignment happens via drag in the Stages pane / the file picker in Task 8) with a "Pick…" button that Task 8 wires to the FilePicker.

- [ ] **Step 1: Write the failing test** (`src/components/PropertiesPanel/PropertiesPanel.test.tsx`)

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider, useSelection } from "@/state/selection";
import { PropertiesPanel } from "./PropertiesPanel";
import type { StageModel } from "@/types";
import { useEffect } from "react";

function mkStage(p: Partial<StageModel>): StageModel {
  return { id: "", name: "", role: "", prmtop: null, mdin: null, mdout: null, mdcrd: null,
    inpcrd: null, expected_gap_ps: null, gap_tolerance_ps: null, notes: [], ...p };
}

function Select({ id }: { id: string }) {
  const { select } = useSelection();
  useEffect(() => { select(id); }, [id, select]);
  return null;
}

function renderPanel(stageId: string, stages: StageModel[]) {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, stages })));
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <Select id={stageId} />
        <PropertiesPanel />
      </SelectionProvider>
    </QueryClientProvider>
  );
}

describe("PropertiesPanel", () => {
  it("commits a name edit on blur via updateStage", async () => {
    const calls: unknown[] = [];
    server.use(
      http.put("/api/stages/1", async ({ request }) => {
        calls.push(await request.json());
        return HttpResponse.json(emptyDocument);
      })
    );
    renderPanel("1", [mkStage({ id: "1", name: "min" })]);
    const name = await screen.findByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "minim");
    await userEvent.tab(); // blur
    await waitFor(() => expect(calls).toEqual([{ name: "minim" }]));
  });

  it("edits global settings when nothing is selected", async () => {
    const calls: unknown[] = [];
    server.use(
      http.get("/api/document", () => HttpResponse.json(emptyDocument)),
      http.put("/api/settings", async ({ request }) => {
        calls.push(await request.json());
        return HttpResponse.json(emptyDocument);
      })
    );
    queryClient.clear();
    render(
      <QueryClientProvider client={queryClient}>
        <SelectionProvider><PropertiesPanel /></SelectionProvider>
      </QueryClientProvider>
    );
    const strict = await screen.findByLabelText(/strict validation/i);
    await userEvent.click(strict);
    await waitFor(() => expect(calls.length).toBe(1));
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/PropertiesPanel/PropertiesPanel.test.tsx`
Expected: FAIL — Task-4 placeholder renders only "Properties".

- [ ] **Step 3: Implement `SettingsPanel.tsx`**

```tsx
import { useUpdateSettings } from "@/api/hooks";
import type { GlobalSettings } from "@/types";

export function SettingsPanel({ settings }: { settings: GlobalSettings }) {
  const update = useUpdateSettings();
  const toggle = (key: keyof GlobalSettings) => (e: React.ChangeEvent<HTMLInputElement>) =>
    update.mutate({ [key]: e.target.checked });
  const text = (key: keyof GlobalSettings) => (e: React.FocusEvent<HTMLInputElement>) =>
    update.mutate({ [key]: e.target.value || null });
  return (
    <div className="p-3 space-y-3 text-sm">
      <h2 className="font-semibold">Protocol settings</h2>
      <p className="text-xs text-ink-muted">Topologies are auto-detected on Discover; override here.</p>
      <label className="block">
        <span className="text-ink-secondary">Global topology (prmtop)</span>
        <input defaultValue={settings.global_prmtop ?? ""} onBlur={text("global_prmtop")}
          className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
      </label>
      <label className="block">
        <span className="text-ink-secondary">HMR topology (prmtop)</span>
        <input defaultValue={settings.hmr_prmtop ?? ""} onBlur={text("hmr_prmtop")}
          placeholder="auto-detected from H-mass repartitioning"
          className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
      </label>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={settings.strict_validation} onChange={toggle("strict_validation")} />
        <span>Strict validation</span>
      </label>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={settings.allow_gaps} onChange={toggle("allow_gaps")} />
        <span>Allow gaps between stages</span>
      </label>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={settings.auto_link_restarts} onChange={toggle("auto_link_restarts")} />
        <span>Auto-link restarts</span>
      </label>
    </div>
  );
}
```

- [ ] **Step 4: Implement `PropertiesPanel.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useDocument, useUpdateStage, useBulkUpdate } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { SettingsPanel } from "./SettingsPanel";
import type { StageModel, StageUpdate } from "@/types";

const ROLES = ["", "minimization", "heating", "equilibration", "production"];

export function PropertiesPanel() {
  const { data: doc } = useDocument();
  const { selectedId, selectedIds } = useSelection();
  const update = useUpdateStage();
  const bulk = useBulkUpdate();

  if (!doc) return null;

  if (selectedIds.length >= 2) {
    return (
      <div className="p-3 space-y-3 text-sm">
        <h2 className="font-semibold">{selectedIds.length} stages selected</h2>
        <label className="block">
          <span className="text-ink-secondary">Set role for all</span>
          <select className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app"
            defaultValue=""
            onChange={(e) =>
              bulk.mutate({ ids: selectedIds, update: { role: e.target.value as StageModel["role"] } })}>
            {ROLES.map((r) => <option key={r} value={r}>{r || "Unknown"}</option>)}
          </select>
        </label>
      </div>
    );
  }

  const stage = selectedId ? doc.stages.find((s) => s.id === selectedId) ?? null : null;
  if (!stage) return <SettingsPanel settings={doc.settings} />;
  return <StageForm key={stage.id} stage={stage} onCommit={(patch) => update.mutate({ id: stage.id, update: patch })} />;
}

const FILE_KINDS = ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"] as const;
type FileKind = (typeof FILE_KINDS)[number];

function StageForm(
  { stage, onCommit, onPickFile }:
  { stage: StageModel; onCommit: (p: StageUpdate) => void; onPickFile?: (slot: FileKind) => void }
) {
  const [name, setName] = useState(stage.name);
  const [role, setRole] = useState(stage.role);
  const [gap, setGap] = useState(stage.expected_gap_ps?.toString() ?? "");
  const [tol, setTol] = useState(stage.gap_tolerance_ps?.toString() ?? "");
  const [notes, setNotes] = useState(stage.notes.join("\n"));

  // Re-sync the draft whenever the selected stage changes.
  useEffect(() => {
    setName(stage.name); setRole(stage.role);
    setGap(stage.expected_gap_ps?.toString() ?? "");
    setTol(stage.gap_tolerance_ps?.toString() ?? "");
    setNotes(stage.notes.join("\n"));
  }, [stage.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  return (
    <div className="p-3 space-y-3 text-sm">
      <label className="block">
        <span className="text-ink-secondary">Name</span>
        <input aria-label="Name" value={name} onChange={(e) => setName(e.target.value)}
          onBlur={() => name !== stage.name && onCommit({ name })}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app" />
      </label>
      <label className="block">
        <span className="text-ink-secondary">Role</span>
        <select aria-label="Role" value={role}
          onChange={(e) => { setRole(e.target.value); onCommit({ role: e.target.value as StageModel["role"] }); }}
          className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app">
          {ROLES.map((r) => <option key={r} value={r}>{r || "Unknown"}</option>)}
        </select>
      </label>
      <div className="space-y-1">
        <span className="text-ink-secondary">Files</span>
        {FILE_KINDS.map((k) => (
          <div key={k} className="flex items-center gap-2">
            <span className="w-14 text-ink-muted text-xs">{k}</span>
            <span className="flex-1 truncate font-mono text-xs">{stage[k] ?? "—"}</span>
            {onPickFile && (
              <button type="button" className="text-accent text-xs" onClick={() => onPickFile(k)}>Pick…</button>
            )}
            {stage[k] && (
              <button type="button" aria-label={`clear ${k}`} className="text-ink-muted text-xs"
                onClick={() => onCommit({ files: { [k]: "" } })}>×</button>
            )}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="text-ink-secondary">Expected gap (ps)</span>
          <input aria-label="Expected gap" value={gap} onChange={(e) => setGap(e.target.value)}
            onBlur={() => onCommit({ expected_gap_ps: num(gap) })}
            className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
        </label>
        <label className="block">
          <span className="text-ink-secondary">Tolerance (ps)</span>
          <input aria-label="Gap tolerance" value={tol} onChange={(e) => setTol(e.target.value)}
            onBlur={() => onCommit({ gap_tolerance_ps: num(tol) })}
            className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
        </label>
      </div>
      <label className="block">
        <span className="text-ink-secondary">Notes</span>
        <textarea aria-label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)}
          onBlur={() => onCommit({ notes: notes.split("\n").filter(Boolean) })}
          rows={3}
          className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app" />
      </label>
    </div>
  );
}
```

`src/components/PropertiesPanel/index.ts`: `export { PropertiesPanel } from "./PropertiesPanel";`

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/PropertiesPanel/PropertiesPanel.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add ambermeta/gui/frontend/src/components/PropertiesPanel
git commit -m "feat(gui): B2 Properties panel — draft-edit form, bulk edit, settings (Task 7)"
```

---

## Task 8: Reusable file picker (tree modal)

**Files:**
- Create: `src/components/FilePicker/FilePicker.tsx`, `src/components/FilePicker/index.ts`, `src/components/FilePicker/FilePicker.test.tsx`

**Interfaces:**
- Consumes: `useFiles` (with `include_all: true` so any path is pickable); `Modal`, `Button` (common); `FileIcon`.
- Produces: `<FilePicker open mode title onPick onClose />` where `mode: "open" | "save"`; `onPick(result: { path: string; format?: ExportFormat })`.

**Design notes:**
- A modal containing a flat, searchable list from `useFiles({ recursive: true, include_all: true })` (so non-simulation files and any directory target are pickable). Clicking a file calls `onPick({ path })` and closes.
- In `mode === "save"`: also render a filename text input + a format `<select>` (yaml/json/toml/csv); the "Save" button calls `onPick({ path: <dir>/<filename>, format })`. Keep it simple: a single path text field prefilled, plus the format select — the user can type/edit the full path; the file list populates the field on click.
- This replaces every raw-text path input across the app (global/HMR prmtop, per-stage files via the Properties "Pick…" buttons, and Open/Save in Task 10).

- [ ] **Step 1: Write the failing test** (`src/components/FilePicker/FilePicker.test.tsx`)

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { FilePicker } from "./FilePicker";

const files = [
  { path: "/work/system.prmtop", name: "system.prmtop", file_type: "prmtop",
    is_directory: false, size: 1, extension: ".prmtop", parent: "/work", children: null },
];

function setup(mode: "open" | "save", onPick = vi.fn()) {
  queryClient.clear();
  server.use(http.get("/api/files", () => HttpResponse.json(files)));
  render(
    <QueryClientProvider client={queryClient}>
      <FilePicker open mode={mode} title="Pick a file" onPick={onPick} onClose={vi.fn()} />
    </QueryClientProvider>
  );
  return onPick;
}

describe("FilePicker", () => {
  it("open mode: clicking a file picks its path", async () => {
    const onPick = setup("open");
    await waitFor(() => expect(screen.getByText("system.prmtop")).toBeInTheDocument());
    await userEvent.click(screen.getByText("system.prmtop"));
    expect(onPick).toHaveBeenCalledWith({ path: "/work/system.prmtop" });
  });

  it("save mode: picks path + chosen format", async () => {
    const onPick = setup("save");
    const pathInput = await screen.findByLabelText(/path/i);
    await userEvent.clear(pathInput);
    await userEvent.type(pathInput, "/work/protocol.toml");
    await userEvent.selectOptions(screen.getByLabelText(/format/i), "toml");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onPick).toHaveBeenCalledWith({ path: "/work/protocol.toml", format: "toml" });
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/FilePicker/FilePicker.test.tsx`
Expected: FAIL — cannot find `./FilePicker`.

- [ ] **Step 3: Implement `FilePicker.tsx`**

```tsx
import { useMemo, useState } from "react";
import { Modal, Button, FileIcon } from "@/components/common";
import { useFiles } from "@/api/hooks";
import type { FileInfo, ExportFormat } from "@/types";

interface Props {
  open: boolean;
  mode: "open" | "save";
  title: string;
  onPick: (result: { path: string; format?: ExportFormat }) => void;
  onClose: () => void;
}

function flatten(nodes: FileInfo[], q: string): FileInfo[] {
  const out: FileInfo[] = [];
  const walk = (n: FileInfo) => {
    if (!n.is_directory && n.name.toLowerCase().includes(q)) out.push(n);
    n.children?.forEach(walk);
  };
  nodes.forEach(walk);
  return out;
}

export function FilePicker({ open, mode, title, onPick, onClose }: Props) {
  const { data: tree = [] } = useFiles({ recursive: true, include_all: true });
  const [q, setQ] = useState("");
  const [path, setPath] = useState("");
  const [format, setFormat] = useState<ExportFormat>("yaml");
  const files = useMemo(() => flatten(tree, q.toLowerCase()), [tree, q]);

  return (
    <Modal open={open} title={title} onClose={onClose}>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search files"
        className="w-full px-2 py-1 mb-2 text-sm border border-hairline rounded bg-app" />
      <div className="max-h-64 overflow-auto border border-hairline rounded">
        {files.map((f) => (
          <button key={f.path}
            onClick={() => (mode === "open" ? onPick({ path: f.path }) : setPath(f.path))}
            className="flex items-center gap-2 w-full px-2 py-1 text-left text-sm hover:bg-app">
            <FileIcon type={f.file_type} />
            <span className="truncate font-mono">{f.path}</span>
          </button>
        ))}
      </div>
      {mode === "save" && (
        <div className="mt-3 space-y-2">
          <label className="block text-sm">
            <span className="text-ink-secondary">Path</span>
            <input aria-label="Path" value={path} onChange={(e) => setPath(e.target.value)}
              className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
          </label>
          <label className="block text-sm">
            <span className="text-ink-secondary">Format</span>
            <select aria-label="Format" value={format}
              onChange={(e) => setFormat(e.target.value as ExportFormat)}
              className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app">
              <option value="yaml">yaml</option>
              <option value="json">json</option>
              <option value="toml">toml</option>
              <option value="csv">csv</option>
            </select>
          </label>
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!path}
              onClick={() => onPick({ path, format })}>Save</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
```

`src/components/FilePicker/index.ts`: `export { FilePicker } from "./FilePicker";`

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/FilePicker/FilePicker.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Wire the picker into the Properties panel for per-stage files**

Task 7 left `StageForm` with an optional `onPickFile` prop and "Pick…" buttons that only render when it's supplied. Now supply it: in `PropertiesPanel.tsx`, give the single-stage branch a picker slot state + a `<FilePicker>` (mode "open") and pass `onPickFile` to `StageForm`. Replace the single-stage return (`const stage = ...; if (!stage) return <SettingsPanel .../>; return <StageForm .../>;`) with a small wrapper component so the hooks stay unconditional:

```tsx
import { useState } from "react";          // add to the existing react import
import { FilePicker } from "@/components/FilePicker";   // add import

// ...inside PropertiesPanel, replace the single-stage tail with:
  const stage = selectedId ? doc.stages.find((s) => s.id === selectedId) ?? null : null;
  if (!stage) return <SettingsPanel settings={doc.settings} />;
  return <StageEditor key={stage.id} stage={stage}
    onCommit={(patch) => update.mutate({ id: stage.id, update: patch })} />;
}

function StageEditor(
  { stage, onCommit }:
  { stage: StageModel; onCommit: (p: StageUpdate) => void }
) {
  const [pickSlot, setPickSlot] = useState<FileKind | null>(null);
  return (
    <>
      <StageForm stage={stage} onCommit={onCommit} onPickFile={(slot) => setPickSlot(slot)} />
      <FilePicker open={pickSlot !== null} mode="open" title={`Pick ${pickSlot ?? ""} file`}
        onClose={() => setPickSlot(null)}
        onPick={({ path }) => {
          if (pickSlot) onCommit({ files: { [pickSlot]: path } });
          setPickSlot(null);
        }} />
    </>
  );
}
```

(Keep `StageForm` as defined in Task 7. `StageEditor` owns the picker so `StageForm` stays presentational. Remove the now-unused `key={stage.id}` from the old `StageForm` call — it moves to `StageEditor`.)

- [ ] **Step 6: Add a test for per-stage Pick…** (append to `PropertiesPanel.test.tsx`)

```tsx
it("Pick… assigns a file to a stage slot", async () => {
  const calls: unknown[] = [];
  server.use(
    http.get("/api/files", () => HttpResponse.json([
      { path: "/work/min.in", name: "min.in", file_type: "mdin", is_directory: false,
        size: 1, extension: ".mdin", parent: "/work", children: null },
    ])),
    http.put("/api/stages/1", async ({ request }) => { calls.push(await request.json()); return HttpResponse.json(emptyDocument); }),
  );
  renderPanel("1", [mkStage({ id: "1", name: "min" })]);
  // open the picker for the mdin slot
  const pickButtons = await screen.findAllByRole("button", { name: "Pick…" });
  await userEvent.click(pickButtons[1]); // prmtop, mdin, mdout, mdcrd, inpcrd order -> [1] = mdin
  await userEvent.click(await screen.findByText("/work/min.in"));
  await waitFor(() => expect(calls).toEqual([{ files: { mdin: "/work/min.in" } }]));
});
```

(The test wraps `PropertiesPanel` in `QueryClientProvider`+`SelectionProvider` exactly as `renderPanel` already does.)

- [ ] **Step 7: Run the picker tests + the Properties tests**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/FilePicker src/components/PropertiesPanel`
Expected: PASS (FilePicker 2 + PropertiesPanel 3).

- [ ] **Step 8: Commit**

```bash
git add ambermeta/gui/frontend/src/components/FilePicker ambermeta/gui/frontend/src/components/PropertiesPanel
git commit -m "feat(gui): B2 reusable file picker + per-stage Pick… wiring (Task 8)"
```

---

## Task 9: Validation panel (run + protocol/per-stage + jump-to-issue)

**Files:**
- Create: `src/components/ValidationPanel/ValidationPanel.tsx`, `src/components/ValidationPanel/index.ts`, `src/components/ValidationPanel/ValidationPanel.test.tsx`

**Interfaces:**
- Consumes: `useValidate` (Task 3); `useDocument` (to map stage name → id for jump-to-issue); `useSelection` (Task 4); `Modal`, `Button`, `Badge` (common).
- Produces: `<ValidationPanel open onClose />` — a modal showing the latest validation result, run on open.

**Design notes:**
- On open, call `useValidate().mutate()` once; show a running state, then the report.
- **Overall status (honor the B1 rule):** show three distinct states — `error` ("N stages with errors") when any `stage_issue.ok === false`; `warning` ("Valid, with N protocol notes") when all stages ok BUT `protocol_issues.length > 0`; `valid` ("All checks passed") only when ok AND no protocol_issues. Never present a non-empty `protocol_issues` as a clean pass.
- Per-stage issues: list each stage with errors (error tone), warnings (warning tone), missing_files; "INFO:" lines shown muted. Each stage row is a **jump-to-issue** button: clicking it resolves the stage id by name from the current document and calls `select(id)`, then closes the modal.
- Show totals (stage_count, total time_ps) as a quiet footer.

- [ ] **Step 1: Write the failing test** (`src/components/ValidationPanel/ValidationPanel.test.tsx`)

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider, useSelection } from "@/state/selection";
import { ValidationPanel } from "./ValidationPanel";
import type { StageModel } from "@/types";

function mkStage(p: Partial<StageModel>): StageModel {
  return { id: "", name: "", role: "", prmtop: null, mdin: null, mdout: null, mdcrd: null,
    inpcrd: null, expected_gap_ps: null, gap_tolerance_ps: null, notes: [], ...p };
}

let lastSelected = "";
function Probe() { lastSelected = useSelection().selectedId ?? ""; return null; }

function renderVP(report: unknown, stages: StageModel[]) {
  queryClient.clear();
  server.use(
    http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, stages })),
    http.post("/api/validate", () => HttpResponse.json(report)),
  );
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <Probe />
        <ValidationPanel open onClose={vi.fn()} />
      </SelectionProvider>
    </QueryClientProvider>
  );
}

describe("ValidationPanel", () => {
  it("treats non-empty protocol_issues as not-fully-valid", async () => {
    renderVP(
      { ok: true, totals: { steps: 0, time_ps: 0, stage_count: 1 },
        protocol_issues: ["Stage starts 5 ps after previous ended."],
        stage_issues: [{ name: "prod", ok: true, degraded: false, errors: [], warnings: [], info: [], missing_files: [] }] },
      [mkStage({ id: "9", name: "prod" })]
    );
    await waitFor(() => expect(screen.getByText(/with 1 protocol note/i)).toBeInTheDocument());
    expect(screen.queryByText(/all checks passed/i)).not.toBeInTheDocument();
  });

  it("jump-to-issue selects the stage by name", async () => {
    renderVP(
      { ok: false, totals: { steps: 0, time_ps: 0, stage_count: 1 }, protocol_issues: [],
        stage_issues: [{ name: "prod", ok: false, degraded: false,
          errors: ["missing mdin: prod.in"], warnings: [], info: [], missing_files: [{ kind: "mdin", path: "prod.in" }] }] },
      [mkStage({ id: "9", name: "prod" })]
    );
    await waitFor(() => expect(screen.getByText(/missing mdin: prod.in/)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /prod/ }));
    expect(lastSelected).toBe("9");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/ValidationPanel/ValidationPanel.test.tsx`
Expected: FAIL — cannot find `./ValidationPanel`.

- [ ] **Step 3: Implement `ValidationPanel.tsx`**

```tsx
import { useEffect } from "react";
import { Modal, Badge } from "@/components/common";
import { useValidate, useDocument } from "@/api/hooks";
import { useSelection } from "@/state/selection";

export function ValidationPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const validate = useValidate();
  const { data: doc } = useDocument();
  const { select } = useSelection();
  const run = validate.mutate;

  useEffect(() => { if (open) run(); }, [open, run]);

  const report = validate.data;
  const errorCount = report?.stage_issues.filter((s) => !s.ok).length ?? 0;
  const noteCount = report?.protocol_issues.length ?? 0;

  let status: { tone: "valid" | "warning" | "error"; label: string } | null = null;
  if (report) {
    if (errorCount > 0) status = { tone: "error", label: `${errorCount} stage(s) with errors` };
    else if (noteCount > 0) status = { tone: "warning", label: `Valid, with ${noteCount} protocol note(s)` };
    else status = { tone: "valid", label: "All checks passed" };
  }

  const jump = (name: string) => {
    const s = doc?.stages.find((st) => st.name === name);
    if (s) { select(s.id); onClose(); }
  };

  return (
    <Modal open={open} title="Validation" onClose={onClose}>
      {validate.isPending && <p className="text-ink-muted text-sm">Validating…</p>}
      {status && (
        <div className="mb-3"><Badge tone={status.tone}>{status.label}</Badge></div>
      )}
      {report?.protocol_issues.length ? (
        <section className="mb-3">
          <h3 className="text-sm font-semibold mb-1">Protocol notes</h3>
          <ul className="text-sm text-warning space-y-0.5">
            {report.protocol_issues.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </section>
      ) : null}
      <section className="space-y-2">
        {report?.stage_issues.map((s) => (
          <div key={s.name} className="border border-hairline rounded p-2">
            <button onClick={() => jump(s.name)}
              className="flex items-center gap-2 font-medium text-left">
              <Badge tone={s.ok ? "valid" : "error"}>{s.ok ? "ok" : "error"}</Badge>
              <span>{s.name}</span>
            </button>
            {s.errors.map((e, i) => <p key={`e${i}`} className="text-error text-sm">{e}</p>)}
            {s.warnings.map((w, i) => <p key={`w${i}`} className="text-warning text-sm">{w}</p>)}
            {s.info.map((n, i) => <p key={`i${i}`} className="text-ink-muted text-sm">{n}</p>)}
          </div>
        ))}
      </section>
      {report && (
        <footer className="mt-3 text-xs text-ink-muted font-mono">
          {report.totals.stage_count} stages · {report.totals.time_ps} ps total
        </footer>
      )}
    </Modal>
  );
}
```

`src/components/ValidationPanel/index.ts`: `export { ValidationPanel } from "./ValidationPanel";`

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/ValidationPanel/ValidationPanel.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/frontend/src/components/ValidationPanel
git commit -m "feat(gui): B2 validation panel — protocol/per-stage, jump-to-issue (Task 9)"
```

---

## Task 10: Top-bar workflows (Open/Save/Discover/Export) + unsaved-changes guard

**Files:**
- Modify: `src/App.tsx` (replace the Task-4 no-op stubs with real modal-bearing handlers)
- Create: `src/components/TopBar/DiscoverModal.tsx`, `src/components/TopBar/ExportModal.tsx`, `src/lib/useUnsavedGuard.ts`, `src/App.workflows.test.tsx`

**Interfaces:**
- Consumes: `useOpen`, `useSave`, `useDiscover`, `usePreview`, `useDocument` (Task 3); `FilePicker` (Task 8); `ValidationPanel` (Task 9); `Modal`, `Button` (common).
- Produces: a fully wired top bar; `useUnsavedGuard(dirty: boolean)` (adds/removes a `beforeunload` handler).

**Design notes:**
- App owns modal open-state: `openPicker` ("open" | "save" | null), `discoverOpen`, `exportOpen`, `validateOpen`.
- **Open:** FilePicker (mode "open") → `useOpen().mutate(path)`. If `doc.dirty`, confirm first (`window.confirm("Discard unsaved changes?")`).
- **Save:** if `doc.manifest_path` exists, `useSave().mutate({})` (saves to the bound path); else open FilePicker (mode "save") → `useSave().mutate({ path, format })`. Surface `result.warnings` (e.g. CSV+HMR) via a transient message.
- **Discover:** DiscoverModal (recursive checkbox + optional pattern) → `useDiscover().mutate(...)`. Confirm if dirty (discover replaces the protocol).
- **Export:** ExportModal (format select) → `usePreview().mutate(format)` → show the rendered manifest text in a `<pre>` with a Copy button.
- **Validate:** opens `ValidationPanel`.
- **Unsaved guard:** `useUnsavedGuard(doc.dirty)` registers a `beforeunload` listener while dirty.

- [ ] **Step 1: Write the failing integration test** (`src/App.workflows.test.tsx`)

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import App from "./App";

function renderApp() {
  queryClient.clear();
  return render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);
}

describe("top-bar workflows", () => {
  it("Discover calls the discover endpoint and updates the document", async () => {
    let discovered = false;
    server.use(
      http.post("/api/document/discover", () => {
        discovered = true;
        return HttpResponse.json({ ...emptyDocument, dirty: true,
          stages: [{ id: "1", name: "prod_001", role: "production", prmtop: null, mdin: "prod_001.in",
            mdout: null, mdcrd: null, inpcrd: null, expected_gap_ps: null, gap_tolerance_ps: null, notes: [] }] });
      })
    );
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Discover" }));
    await userEvent.click(await screen.findByRole("button", { name: /^discover$/i, hidden: false }).catch(() => screen.getByRole("button", { name: /run discover/i })));
    await waitFor(() => expect(discovered).toBe(true));
    await waitFor(() => expect(screen.getByText("prod_001")).toBeInTheDocument());
  });

  it("Save to a bound manifest path posts save", async () => {
    let saved = false;
    server.use(
      http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, manifest_path: "/work/p.yaml", dirty: true })),
      http.post("/api/document/save", () => { saved = true; return HttpResponse.json({ document: { ...emptyDocument, manifest_path: "/work/p.yaml" }, warnings: [] }); })
    );
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    await waitFor(() => expect(saved).toBe(true));
  });
});
```

NOTE: the Discover test's button-resolution is intentionally tolerant; name the modal's run button "Run discover" so `getByRole("button", { name: /run discover/i })` is stable, and simplify the test to click that.

- [ ] **Step 2: Run to verify it fails**

Run: `cd ambermeta/gui/frontend && npx vitest run src/App.workflows.test.tsx`
Expected: FAIL — Discover/Save are no-ops in the Task-4 shell.

- [ ] **Step 3: Implement `useUnsavedGuard.ts`**

```ts
import { useEffect } from "react";

export function useUnsavedGuard(dirty: boolean): void {
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
}
```

- [ ] **Step 4: Implement `DiscoverModal.tsx` and `ExportModal.tsx`**

`src/components/TopBar/DiscoverModal.tsx`:
```tsx
import { useState } from "react";
import { Modal, Button } from "@/components/common";

export function DiscoverModal(
  { open, onClose, onRun }:
  { open: boolean; onClose: () => void; onRun: (a: { recursive: boolean; pattern?: string }) => void }
) {
  const [recursive, setRecursive] = useState(true);
  const [pattern, setPattern] = useState("");
  return (
    <Modal open={open} title="Discover stages" onClose={onClose}>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={recursive} onChange={(e) => setRecursive(e.target.checked)} />
        <span>Search subdirectories</span>
      </label>
      <label className="block text-sm mt-3">
        <span className="text-ink-secondary">Filename pattern (optional)</span>
        <input value={pattern} onChange={(e) => setPattern(e.target.value)}
          className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
      </label>
      <div className="flex justify-end gap-2 mt-4">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary"
          onClick={() => { onRun({ recursive, pattern: pattern || undefined }); onClose(); }}>
          Run discover
        </Button>
      </div>
    </Modal>
  );
}
```

`src/components/TopBar/ExportModal.tsx`:
```tsx
import { useState } from "react";
import { Modal, Button } from "@/components/common";
import { usePreview } from "@/api/hooks";
import type { ExportFormat } from "@/types";

export function ExportModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [format, setFormat] = useState<ExportFormat>("yaml");
  const preview = usePreview();
  return (
    <Modal open={open} title="Export manifest" onClose={onClose}>
      <div className="flex items-center gap-2">
        <select aria-label="Format" value={format}
          onChange={(e) => setFormat(e.target.value as ExportFormat)}
          className="px-2 py-1 border border-hairline rounded bg-app text-sm">
          <option value="yaml">yaml</option><option value="json">json</option>
          <option value="toml">toml</option><option value="csv">csv</option>
        </select>
        <Button variant="primary" onClick={() => preview.mutate(format)}>Render</Button>
        {preview.data && (
          <Button onClick={() => navigator.clipboard?.writeText(preview.data!.content)}>Copy</Button>
        )}
      </div>
      {preview.data && (
        <pre className="mt-3 p-2 bg-app border border-hairline rounded text-xs font-mono overflow-auto max-h-72">
          {preview.data.content}
        </pre>
      )}
    </Modal>
  );
}
```

- [ ] **Step 5: Rewrite `App.tsx` to own modal state and wire the handlers**

```tsx
import { useState } from "react";
import { SelectionProvider } from "@/state/selection";
import { ResizeHandle } from "@/components/common";
import { usePersistentSize } from "@/lib/usePersistentSize";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { TopBar } from "@/components/TopBar/TopBar";
import { DiscoverModal } from "@/components/TopBar/DiscoverModal";
import { ExportModal } from "@/components/TopBar/ExportModal";
import { FileBrowser } from "@/components/FileBrowser/FileBrowser";
import { StageList } from "@/components/StageList/StageList";
import { PropertiesPanel } from "@/components/PropertiesPanel/PropertiesPanel";
import { FilePicker } from "@/components/FilePicker/FilePicker";
import { ValidationPanel } from "@/components/ValidationPanel/ValidationPanel";
import { useDocument, useOpen, useSave, useDiscover, useLinkRestarts } from "@/api/hooks";

export default function App() {
  const [filesW, setFilesW] = usePersistentSize("files-w", 280);
  const [propsW, setPropsW] = usePersistentSize("props-w", 340);
  const { data: doc } = useDocument();
  const open = useOpen(); const save = useSave(); const discover = useDiscover();
  const relink = useLinkRestarts();
  const [picker, setPicker] = useState<"open" | "save" | null>(null);
  const [discoverOpen, setDiscoverOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [validateOpen, setValidateOpen] = useState(false);

  useUnsavedGuard(!!doc?.dirty);
  const confirmIfDirty = () => !doc?.dirty || window.confirm("Discard unsaved changes?");

  const onOpen = () => { if (confirmIfDirty()) setPicker("open"); };
  const onSave = () => {
    if (doc?.manifest_path) save.mutate({});
    else setPicker("save");
  };
  const onDiscover = () => { if (confirmIfDirty()) setDiscoverOpen(true); };

  return (
    <SelectionProvider>
      <div className="flex flex-col h-full">
        <TopBar onOpen={onOpen} onSave={onSave} onDiscover={onDiscover}
          onRelink={() => relink.mutate()}
          onExport={() => setExportOpen(true)} onValidate={() => setValidateOpen(true)} />
        <div className="flex flex-1 min-h-0">
          <div data-testid="pane-files" style={{ width: filesW }}
            className="shrink-0 border-r border-hairline overflow-auto bg-surface"><FileBrowser /></div>
          <ResizeHandle direction="left" currentWidth={filesW} onResize={setFilesW} min={200} max={480} />
          <div data-testid="pane-stages" className="flex-1 min-w-0 overflow-hidden"><StageList /></div>
          <ResizeHandle direction="right" currentWidth={propsW} onResize={setPropsW} min={260} max={520} />
          <div data-testid="pane-properties" style={{ width: propsW }}
            className="shrink-0 border-l border-hairline overflow-auto bg-surface"><PropertiesPanel /></div>
        </div>
      </div>

      <FilePicker open={picker === "open"} mode="open" title="Open manifest"
        onClose={() => setPicker(null)}
        onPick={({ path }) => { setPicker(null); open.mutate(path); }} />
      <FilePicker open={picker === "save"} mode="save" title="Save manifest as"
        onClose={() => setPicker(null)}
        onPick={({ path, format }) => { setPicker(null); save.mutate({ path, format }); }} />
      <DiscoverModal open={discoverOpen} onClose={() => setDiscoverOpen(false)}
        onRun={(a) => discover.mutate(a)} />
      <ExportModal open={exportOpen} onClose={() => setExportOpen(false)} />
      <ValidationPanel open={validateOpen} onClose={() => setValidateOpen(false)} />
    </SelectionProvider>
  );
}
```

- [ ] **Step 6: Simplify the Discover workflow test**

Update `src/App.workflows.test.tsx`'s first test to click `Discover` (top bar) then the modal's `Run discover` button:
```tsx
await userEvent.click(await screen.findByRole("button", { name: "Discover" }));
await userEvent.click(await screen.findByRole("button", { name: "Run discover" }));
await waitFor(() => expect(discovered).toBe(true));
await waitFor(() => expect(screen.getByText("prod_001")).toBeInTheDocument());
```

Also add a Re-link restarts test (the top-bar button POSTs `/api/link-restarts`):
```tsx
it("Re-link restarts posts link-restarts", async () => {
  let linked = false;
  server.use(
    http.post("/api/link-restarts", () => { linked = true; return HttpResponse.json(emptyDocument); })
  );
  renderApp();
  await userEvent.click(await screen.findByRole("button", { name: "Re-link restarts" }));
  await waitFor(() => expect(linked).toBe(true));
});
```

- [ ] **Step 7: Run the workflow tests + the whole frontend suite**

Run: `cd ambermeta/gui/frontend && npx vitest run`
Expected: PASS — all suites (format, client, hooks, App, FileBrowser, StageList, reorder, PropertiesPanel, FilePicker, ValidationPanel, App.workflows).

- [ ] **Step 8: Commit**

```bash
git add ambermeta/gui/frontend/src/App.tsx ambermeta/gui/frontend/src/App.workflows.test.tsx ambermeta/gui/frontend/src/components/TopBar ambermeta/gui/frontend/src/lib/useUnsavedGuard.ts
git commit -m "feat(gui): B2 top-bar workflows (open/save/discover/export) + unsaved guard (Task 10)"
```

---

## Task 11: Build the offline bundle, replace `static/`, and verify all gates

**Files:**
- Modify (generated): `ambermeta/gui/static/**`
- Test: the full frontend (`vitest`) + the Python GUI suite + the `gui-static-check` invariant

**Interfaces:**
- Consumes: everything (Tasks 1–10).
- Produces: a committed, offline production bundle in `ambermeta/gui/static/` that exactly matches `npm run build`.

**Design notes:**
- `vite.config.ts` already targets `outDir: ../static` with `emptyOutDir: true`, so the build replaces the stale `index-*.js`/`index-*.css` and the old `index.html` (with the CDN links). Confirm the built `static/index.html` has no `fonts.googleapis.com`/`gstatic` references (fonts are now bundled into the JS/CSS via `@fontsource`).
- `gui-static-check` passes iff `git diff --quiet -- ambermeta/gui/static` after a clean build. So: build, then commit the new `static/`.

- [ ] **Step 1: Typecheck + full unit suite**

Run: `cd ambermeta/gui/frontend && npm run build` is below; first the tests:
`cd ambermeta/gui/frontend && npx vitest run`
Expected: PASS (all suites green). Fix any TypeScript `noUnusedLocals`/`noUnusedParameters` errors surfaced by `tsc` in the build step.

- [ ] **Step 2: Build the production bundle**

Run: `cd ambermeta/gui/frontend && npm run build`
Expected: `tsc` clean, Vite writes `../static/index.html` + `../static/assets/index-*.{js,css}`. No build errors.

- [ ] **Step 3: Verify offline (no CDN in the built output)**

Run (expect no matches): `cd ambermeta/gui/frontend && grep -ri "googleapis\|gstatic\|unpkg\|//cdn" ../static`
Expected: no output. If anything matches, a CDN reference leaked — fix the source and rebuild.

- [ ] **Step 4: Confirm the static dir is the committed artifact (the CI invariant)**

Run: `cd "C:/Users/Miche/Documents/GitHub/ambermeta" && git add ambermeta/gui/static && git status --porcelain ambermeta/gui/static`
Expected: shows the new/updated `static/` files staged. (After committing in Step 6, a fresh `npm run build` must leave `git diff --quiet -- ambermeta/gui/static` clean — that is exactly what `gui-static-check` runs.)

- [ ] **Step 5: Run the backend (Python) GUI suite to confirm nothing regressed**

Run: `cd "C:/Users/Miche/Documents/GitHub/ambermeta" && python -m pytest -q`
Expected: PASS (the B1 backend suite — 150 — still green; the frontend rebuild doesn't touch Python).

- [ ] **Step 6: Commit the bundle**

```bash
git add ambermeta/gui/frontend ambermeta/gui/static
git commit -m "build(gui): B2 offline production bundle — replace stale static assets (Task 11)"
```

- [ ] **Step 7: Final re-build determinism check**

Run: `cd ambermeta/gui/frontend && npm run build && cd "C:/Users/Miche/Documents/GitHub/ambermeta" && git diff --quiet -- ambermeta/gui/static && echo "STATIC CLEAN (gui-static-check would pass)"`
Expected: prints `STATIC CLEAN ...`. If the diff is dirty, the build is non-deterministic for committed output — investigate (usually an uncommitted source change) and re-commit.

---

## Self-Review (completed by plan author)

**Spec coverage (B2 section of `2026-06-23-gui-redesign-design.md`):**
- Layout & shell (3-pane resizable, persisted sizes, top bar Open/Save/Validate/Discover/Undo-Redo/Export, unsaved guard) → Tasks 4, 10.
- State (react-query for all server state; mutation hooks; no Zustand mirror; UI-only state local; undo/redo via server) → Tasks 3, 4, 7.
- Feature surface 1 file-metadata preview → Task 5. 2 validation panel (protocol + per-stage + jump-to-issue) → Task 9. 3 sequence grouping + virtualization → Task 6. 4 file picker everywhere → Tasks 7 (Pick…), 8, 10. 5 HMR auto-detect (surfaced via discover/settings) → Tasks 6/7 (settings show hmr_prmtop; discovery sets it server-side). 6 visible restart-linking → "Re-link restarts" action (see note below). 7 open/save real manifests → Tasks 8, 10.
- Design system (bundled fonts/no CDN; deliberate palette/density; consistent components) → Tasks 1, 4 + tokens used throughout.
- Testing (Vitest + RTL for document model/validation/grouping/picker/undo; built bundle passes gui-static-check) → every task + Task 11.
- Acceptance #1 byte-identical export → backend-guaranteed (B1) + surfaced via Export/Save (Tasks 8/10). #2 validation parity surfaced with jump-to-issue → Task 9. #3 open→edit→save → Tasks 8/10. #4 undo/redo server-authoritative → Tasks 3/4. #5 metadata preview → Task 5. #6 large protocols responsive (grouping + virtualization) → Task 6. #7 offline/no CDN → Tasks 1/11. #8 one engine → backend (B1); the frontend calls only the API. #9 suite green + fresh bundle → Task 11.

**Adversarial verification (4-lens workflow) — findings folded in.** The api-contract lens confirmed all 20 endpoints + request/response shapes match the real B1 backend (only doc-only minors). Fixes applied to this plan: (1) **Re-link restarts** is now a concrete TopBar button + `onRelink` handler (Task 4 Props/Task 10 wiring) with a test (Feature Surface 6 — previously only acknowledged, now implemented). (2) **Per-stage "Pick…"** file assignment is now real — `StageForm` renders file slots + Pick…/clear (Task 7) and Task 8 wires the `FilePicker` into a `StageEditor` with a test (Feature Surface 4). (3) **react-query bugs:** the hooks test now clears the singleton `queryClient` per test; `useFiles` uses a spread (stable) query key; `useFileMetadata` guards null in `queryFn`. (4) **Modal** now traps Tab focus (a11y). (5) **HMR** topology fields in `SettingsPanel` are labeled auto-detected/overridable (Feature Surface 5). The "tooling-build" lens's 10 "criticals" were all pre-execution repo state (Task 1 adds exactly those) — not plan defects.

**Placeholder scan:** No TBD/"add X"/"similar to Task N". Hard-to-simulate interactions (dnd reorder) are covered by a pure helper (`reorderIds`) with its own test; virtualization uses a documented threshold so small-list tests exercise the plain path. The one explicitly deferred implementation detail — the `useVirtualizer` branch in Task 6 — is described with exact API (`estimateSize`, `getScrollElement`) and is bounded (only the inner render windows; the tested grouping model is unchanged).

**Type consistency:** `DocumentResponse`/`StageModel`/`GlobalSettings`/`ValidationReport`/`FileInfo`/`FileMetadata` are defined once (Task 2) and consumed unchanged. Hook names (`useDocument`, `useOpen`, `useSave`, `useDiscover`, `useCreateStage`, `useUpdateStage`, `useDeleteStage`, `useReorder`, `useBulkUpdate`, `useUpdateSettings`, `useUndo`, `useRedo`, `useValidate`, `usePreview`, `useLinkRestarts`, `useFiles`, `useFileMetadata`, `useSequences`) match between Task 3 and every consumer. `useSelection` shape matches between Task 4 and Tasks 5/6/7/9. Token names match `tailwind.config.js` (Task 1) and all components.

**Known deviations (intentional):** (1) conditional virtualization (threshold 50) rather than always-on, to keep small-list tests simple and avoid jsdom measurement fights — large protocols still window. (2) Export is a preview/copy modal (the file IS the document; Save/Save-As writes to disk) — matches the B1 contract (no separate export-to-disk endpoint). (3) dnd reorder verified via the pure `reorderIds` helper, not pointer simulation.
