import { it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { Canvas } from "./Canvas";
import type { DocumentResponse, ValidationReport } from "@/types";

function wrap(ui: React.ReactNode) {
  return (
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <DndContext>{ui}</DndContext>
      </SelectionProvider>
    </QueryClientProvider>
  );
}

const docWithGap: DocumentResponse = {
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
            expected_gap_ps: null,
            gap_tolerance_ps: null,
            notes: [],
          },
          {
            id: "s1",
            name: "prod_0003",
            topology: "t0",
            input_coords: { source: "step", ref: "s0", path: null },
            mdin: "/w/prod3.in",
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

const reportWithGapAndGhost: ValidationReport = {
  ok: false,
  totals: {},
  protocol_issues: ["Stage starts +20 ps after previous ended."],
  stage_issues: [],
  suggestions: [
    {
      id: "sug_1",
      kind: "continuity_gap",
      severity: "needs_you",
      title: "Continuity note",
      evidence: "Stage starts +20 ps after previous ended.",
      actions: ["Set as expected", "Investigate"],
    },
    {
      id: "sug_2",
      kind: "missing_run",
      severity: "needs_you",
      title: "prod_0002 sequence is missing member(s), run appears missing",
      evidence: "present members of 'prod' skip index(es) 2",
      actions: ["Mark as expected gap", "Locate file", "Ignore"],
    },
  ],
};

it("renders an amber continuity-gap marker and a dashed missing-run ghost", async () => {
  server.use(
    http.get("/api/document", () => HttpResponse.json(docWithGap)),
    http.post("/api/validate", () => HttpResponse.json(reportWithGapAndGhost)),
  );
  render(wrap(<Canvas />));

  await waitFor(() => expect(screen.getByText("prod_0001")).toBeInTheDocument());
  expect(screen.getByText("prod_0003")).toBeInTheDocument();

  await waitFor(() => expect(screen.getAllByText("20 ps").length).toBeGreaterThan(0));
  const gapEl = screen.getAllByText("20 ps")[0].closest("div");
  expect(gapEl?.className).toMatch(/text-warning/);

  await waitFor(() => expect(screen.getByText(/prod_0002/)).toBeInTheDocument());
  const ghostEl = screen.getByText(/prod_0002/).closest("div");
  expect(ghostEl?.className).toMatch(/border-dashed/);
});
