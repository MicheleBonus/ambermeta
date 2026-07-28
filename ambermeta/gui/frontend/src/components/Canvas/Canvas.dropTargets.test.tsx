import { beforeEach, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { SuggestionsContext } from "@/components/Suggestions/suggestionsContext";
import { Canvas } from "./Canvas";
import type { DocumentResponse } from "@/types";

// jsdom has no layout, so dnd-kit can never compute a real collision. Drive `isOver`
// directly instead: every droppable still registers with the real DndContext, but the
// ids in `hoisted.over` report themselves as hovered.
const hoisted = vi.hoisted(() => ({ over: new Set<string>() }));

vi.mock("@dnd-kit/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@dnd-kit/core")>();
  return {
    ...actual,
    useDroppable: (args: import("@dnd-kit/core").UseDroppableArguments) => ({
      ...actual.useDroppable(args),
      isOver: hoisted.over.has(String(args.id)),
    }),
  };
});

function wrap(ui: React.ReactNode) {
  return (
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <DndContext>
          <SuggestionsContext.Provider value={[]}>{ui}</SuggestionsContext.Provider>
        </DndContext>
      </SelectionProvider>
    </QueryClientProvider>
  );
}

const doc: DocumentResponse = {
  base_directory: "/w",
  manifest_path: null,
  dirty: false,
  can_undo: false,
  can_redo: false,
  settings: { auto_link_restarts: true, strict_validation: true, allow_gaps: false, use_relative_paths: true },
  simulation: {
    version: 2,
    topologies: [{ id: "t0", path: "/w/wt.prmtop", kind: "normal" }],
    starting_structure: "/w/wt.inpcrd",
    phases: [
      {
        id: "p0",
        name: "Production",
        role: "production",
        steps: [
          {
            id: "s0",
            name: "prod_0001",
            topology: "t0",
            input_coords: { source: "starting_structure", ref: null, path: null },
            mdin: "/w/prod1.in",
            mdout: null,
            mdcrd: null,
            rst: null,
            resolved_input_coords: null,
            expected_gap_ps: null,
            gap_tolerance_ps: null,
            notes: [],
          },
        ],
      },
    ],
  },
};

const HIGHLIGHT = /bg-accent-subtle|border-accent/;

async function renderCanvas() {
  server.use(http.get("/api/document", () => HttpResponse.json(doc)));
  const utils = render(wrap(<Canvas />));
  // By role: "Production" is also one of the options in the phase header's role select.
  await screen.findByRole("button", { name: "Production" });
  return utils;
}

function target(container: HTMLElement, id: string): HTMLElement {
  const el = container.querySelector<HTMLElement>(`[data-droppable-id="${id}"]`);
  if (!el) throw new Error(`no droppable registered for "${id}"`);
  return el;
}

beforeEach(() => hoisted.over.clear());

it("highlights the canvas while a drag hovers empty space", async () => {
  const plain = await renderCanvas();
  expect(target(plain.container, "canvas").className).not.toMatch(HIGHLIGHT);
  plain.unmount();

  hoisted.over.add("canvas");
  const hovered = await renderCanvas();
  expect(target(hovered.container, "canvas").className).toMatch(HIGHLIGHT);
});

it("highlights the entire phase section -- header and step list -- while hovered", async () => {
  hoisted.over.add("phase:p0");
  const { container } = await renderCanvas();

  const section = target(container, "phase:p0");
  expect(section.className).toMatch(HIGHLIGHT);
  expect(section.contains(screen.getByText("prod_0001"))).toBe(true);
});

it("highlights the precise step slot chip that is hovered, and only that one", async () => {
  hoisted.over.add("slot:s0:mdout");
  const { container } = await renderCanvas();

  expect(target(container, "slot:s0:mdout").className).toMatch(HIGHLIGHT);
  expect(target(container, "slot:s0:mdin").className).not.toMatch(HIGHLIGHT);
  expect(target(container, "slot:s0:mdcrd").className).not.toMatch(HIGHLIGHT);
});
