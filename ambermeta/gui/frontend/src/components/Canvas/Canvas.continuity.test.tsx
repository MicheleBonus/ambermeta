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

// Three real steps -> two arrows (before s3, before s5). The gap suggestion is
// scoped (via step_id) to the arrow immediately before "prod_0003" only.
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
            id: "s1",
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
            id: "s3",
            name: "prod_0003",
            topology: "t0",
            input_coords: { source: "step", ref: "s1", path: null },
            mdin: "/w/prod3.in",
            mdout: null,
            mdcrd: null,
            expected_gap_ps: null,
            gap_tolerance_ps: null,
            notes: [],
          },
          {
            id: "s5",
            name: "prod_0005",
            topology: "t0",
            input_coords: { source: "step", ref: "s3", path: null },
            mdin: "/w/prod5.in",
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
  protocol_issues: ["Stage starts 20 ps after previous ended."],
  stage_issues: [],
  suggestions: [
    {
      id: "sug_1",
      kind: "continuity_gap",
      severity: "needs_you",
      title: "Continuity note",
      evidence: "Stage starts 20 ps after previous ended.",
      actions: ["Set as expected", "Investigate"],
      step_id: "s3",
      phase_id: "p0",
    },
    {
      id: "sug_2",
      kind: "missing_run",
      severity: "needs_you",
      title: "prod sequence is missing member(s), run appears missing",
      evidence: "present members of 'prod' skip index(es) 2",
      actions: ["Mark as expected gap", "Locate file", "Ignore"],
      base: "prod",
      missing: [2],
    },
  ],
};

it("renders an amber continuity-gap marker scoped to the right arrow and a dashed missing-run ghost", async () => {
  server.use(
    http.get("/api/document", () => HttpResponse.json(docWithGap)),
    http.post("/api/validate", () => HttpResponse.json(reportWithGapAndGhost)),
  );
  render(wrap(<Canvas />));

  await waitFor(() => expect(screen.getByText("prod_0001")).toBeInTheDocument());
  expect(screen.getByText("prod_0003")).toBeInTheDocument();
  expect(screen.getByText("prod_0005")).toBeInTheDocument();

  // Exactly one gap marker rendered (scoped to the arrow before prod_0003, the
  // suggestion's step_id), not one per arrow.
  await waitFor(() => expect(screen.getAllByText("20 ps").length).toBe(1));
  const gapEl = screen.getByText("20 ps").closest("div");
  expect(gapEl?.className).toMatch(/text-warning/);

  // The gap marker must appear in DOM order before "prod_0003" and after
  // "prod_0001" -- i.e. on the arrow immediately preceding the step whose id
  // matches the suggestion's step_id -- and not before/after prod_0005.
  const gapNode = screen.getByText("20 ps");
  const prod0001 = screen.getByText("prod_0001");
  const prod0003 = screen.getByText("prod_0003");
  const prod0005 = screen.getByText("prod_0005");

  // gap comes after prod_0001 and before prod_0003 in the DOM
  expect(prod0001.compareDocumentPosition(gapNode) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(gapNode.compareDocumentPosition(prod0003) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  // and it is not between prod_0003 and prod_0005 (no gap marker there at all,
  // already covered by the count === 1 assertion above, but double check ordering)
  expect(prod0005.compareDocumentPosition(gapNode) & Node.DOCUMENT_POSITION_FOLLOWING).toBeFalsy();

  // Missing-run ghost: base "prod", missing index 2 -> a dashed ghost labeled
  // from base+missing (e.g. containing "prod_0002" or "2"), positioned within
  // the "prod" group, numerically between prod_0001 and prod_0003.
  await waitFor(() => expect(screen.getByText(/prod_0002|(?<![\d])2(?![\d])/)).toBeInTheDocument());
  const ghostEl = screen.getByText(/prod_0002/).closest("div");
  expect(ghostEl?.className).toMatch(/border-dashed/);

  const ghostNode = screen.getByText(/prod_0002/);
  expect(prod0001.compareDocumentPosition(ghostNode) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(ghostNode.compareDocumentPosition(prod0003) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});
