import { it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { Canvas } from "./Canvas";
import type { DocumentResponse } from "@/types";

function wrap(ui: React.ReactNode) {
  return (
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <DndContext>{ui}</DndContext>
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

  await waitFor(() => expect(screen.getByText("Production")).toBeInTheDocument());
  expect(screen.getByText("prod_0001")).toBeInTheDocument();
  expect(screen.getByText("prod_0002")).toBeInTheDocument();
  expect(screen.getAllByText(/hmr/i).length).toBeGreaterThan(0);
});

it("shows a start hint when the simulation is empty", async () => {
  render(wrap(<Canvas />));
  await waitFor(() => expect(screen.getByText(/discover or drop files to start/i)).toBeInTheDocument());
});
