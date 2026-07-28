import { it, expect } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient, setDocument } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { SuggestionsContext } from "@/components/Suggestions/suggestionsContext";
import { Canvas } from "./Canvas";
import type { DocumentResponse, Suggestion } from "@/types";

function wrap(ui: React.ReactNode, suggestions: Suggestion[] = []) {
  return (
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <DndContext>
          <SuggestionsContext.Provider value={suggestions}>{ui}</SuggestionsContext.Provider>
        </DndContext>
      </SelectionProvider>
    </QueryClientProvider>
  );
}

const docWithProductionPhase: DocumentResponse = {
  base_directory: "/w",
  manifest_path: null,
  dirty: false,
  can_undo: false,
  can_redo: false,
  settings: { auto_link_restarts: true, strict_validation: true, allow_gaps: false, use_relative_paths: true },
  simulation: {
    version: 2,
    topologies: [
      { id: "t0", path: "/w/wt.prmtop", kind: "normal" },
      { id: "t1", path: "/w/wt_hmr.prmtop", kind: "hmr" },
    ],
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
          {
            id: "s1",
            name: "prod_0002",
            topology: "t1",
            input_coords: { source: "step", ref: "s0", path: null },
            mdin: "/w/prod2.in",
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

it("renders the phase, its steps, and an HMR chip for the HMR-bound step", async () => {
  server.use(http.get("/api/document", () => HttpResponse.json(docWithProductionPhase)));
  render(wrap(<Canvas />));

  // By role, not by text: "Production" is also one of the role select's options.
  await waitFor(() => expect(screen.getByRole("button", { name: "Production" })).toBeInTheDocument());
  expect(screen.getByText("prod_0001")).toBeInTheDocument();
  expect(screen.getByText("prod_0002")).toBeInTheDocument();
  expect(screen.getAllByText(/hmr/i).length).toBeGreaterThan(0);
});

it("renders drag handles so steps and phases can be reordered/moved (drop sources exist)", async () => {
  server.use(http.get("/api/document", () => HttpResponse.json(docWithProductionPhase)));
  render(wrap(<Canvas />));

  // The phase and each step expose a draggable grip whose id (phase:/step:) is what
  // resolveDrop + onDragEnd already route to reorder_phases / reorder_or_move_step.
  await waitFor(() => expect(screen.getByLabelText("drag phase Production")).toBeInTheDocument());
  expect(screen.getByLabelText("drag step prod_0001")).toBeInTheDocument();
  expect(screen.getByLabelText("drag step prod_0002")).toBeInTheDocument();
});

it("shows a start hint naming what a drop actually does when the simulation is empty", async () => {
  render(wrap(<Canvas />));
  await waitFor(() => expect(screen.getByText(/drop an \.mdin here to start a phase/i)).toBeInTheDocument());
  expect(screen.getByText(/discover/i)).toBeInTheDocument();
});

it("registers a canvas droppable over the scroll area whether or not phases exist", async () => {
  const empty = render(wrap(<Canvas />));
  await waitFor(() => expect(screen.getByText(/drop an \.mdin here to start a phase/i)).toBeInTheDocument());
  const emptyTarget = empty.container.querySelector('[data-droppable-id="canvas"]');
  expect(emptyTarget).not.toBeNull();
  expect(emptyTarget?.className).toMatch(/overflow-auto/);
  empty.unmount();

  // It must stay registered once phases exist -- dropping below the last phase creates a new one.
  server.use(http.get("/api/document", () => HttpResponse.json(docWithProductionPhase)));
  const filled = render(wrap(<Canvas />));
  const phaseName = await screen.findByRole("button", { name: "Production" });
  const target = filled.container.querySelector('[data-droppable-id="canvas"]');
  expect(target).not.toBeNull();
  expect(target?.contains(phaseName)).toBe(true);
});

it("makes the whole phase section -- not just its header -- the phase drop target", async () => {
  server.use(http.get("/api/document", () => HttpResponse.json(docWithProductionPhase)));
  const { container } = render(wrap(<Canvas />));
  await screen.findByRole("button", { name: "Production" });

  const phaseTarget = container.querySelector('[data-droppable-id="phase:p0"]');
  expect(phaseTarget?.tagName).toBe("SECTION");
  // A file dropped on the step list (the body) must hit the phase, not fall through to the canvas.
  expect(phaseTarget?.contains(screen.getByText("prod_0001"))).toBe(true);
  expect(phaseTarget?.contains(screen.getByText("prod_0002"))).toBe(true);
  // The grip stays inside the section's header, so the phase is still reorderable.
  expect(phaseTarget?.contains(screen.getByLabelText("drag phase Production"))).toBe(true);
});

it("keeps a document applied by a mutation on screen -- steps must not refetch it away", async () => {
  let docFetches = 0;
  server.use(
    http.get("/api/document", () => {
      docFetches += 1;
      return HttpResponse.json(emptyDocument);
    }),
  );
  queryClient.clear();
  render(wrap(<Canvas />));
  await waitFor(() => expect(docFetches).toBe(1));

  // What Discover (and every assign) does: swap the cached document in place.
  act(() => setDocument(docWithProductionPhase));
  await waitFor(() => expect(screen.getByText("prod_0001")).toBeInTheDocument());

  // A step node holding its own /api/document observer would refetch on mount here and
  // put the stale (pre-discover) server document back, wiping the phase off the canvas.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  expect(docFetches).toBe(1);
  expect(screen.getByText("prod_0001")).toBeInTheDocument();
});

it("labels pooled topologies and the starting structure instead of printing absolute paths", async () => {
  // The header sits outside the canvas' scroll container, so an absolute path -- one unbreakable
  // token -- spills straight out of the middle pane instead of scrolling.
  server.use(http.get("/api/document", () => HttpResponse.json(docWithProductionPhase)));
  render(wrap(<Canvas />));
  await waitFor(() => expect(screen.getByRole("button", { name: "Production" })).toBeInTheDocument());

  expect(screen.getAllByText("wt.prmtop").length).toBeGreaterThan(0);
  expect(screen.getByText("wt.inpcrd")).toBeInTheDocument();
  expect(screen.getByTitle("/w/wt.inpcrd")).toBeInTheDocument();
  expect(screen.queryByText(/starting structure: \/w\/wt\.inpcrd/)).not.toBeInTheDocument();
});

it("ends each phase's step list with a discoverable add-a-step drop hint", async () => {
  server.use(http.get("/api/document", () => HttpResponse.json(docWithProductionPhase)));
  render(wrap(<Canvas />));
  await waitFor(() => expect(screen.getByText("prod_0002")).toBeInTheDocument());

  const hint = screen.getByText(/drop a file here to add a step/i);
  expect(hint.className).toMatch(/border-dashed/);
  const lastStep = screen.getByText("prod_0002");
  expect(lastStep.compareDocumentPosition(hint) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});
