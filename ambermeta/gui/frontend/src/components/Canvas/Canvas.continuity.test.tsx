import { it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { SuggestionsContext } from "@/components/Suggestions/suggestionsContext";
import { makeStep } from "@/test/factories";
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

// Three real steps -> two arrows (before s3, before s5). The gap suggestion is
// scoped (via step_id) to the arrow immediately before "prod_0003" only.
const docWithGap: DocumentResponse = {
  base_directory: "/w",
  manifest_path: null,
  dirty: false,
  can_undo: false,
  can_redo: false,
  warnings: [],
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
          makeStep({ id: "s1", name: "prod_0001", topology: "t0", mdin: "/w/prod1.in" }),
          makeStep({
            id: "s3", name: "prod_0003", topology: "t0", mdin: "/w/prod3.in",
            input_coords: { source: "step", ref: "s1", path: null },
          }),
          makeStep({
            id: "s5", name: "prod_0005", topology: "t0", mdin: "/w/prod5.in",
            input_coords: { source: "step", ref: "s3", path: null },
          }),
        ],
      },
    ],
  },
};

const suggestionsWithGapAndGhost: Suggestion[] = [
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
];

it("renders an amber continuity-gap marker scoped to the right arrow and a dashed missing-run ghost", async () => {
  server.use(http.get("/api/document", () => HttpResponse.json(docWithGap)));
  render(wrap(<Canvas />, suggestionsWithGapAndGhost));

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

it("labels the arrow between two chained steps with the restart that passes between them", async () => {
  // The file a run hands to the next belongs to neither card alone — it is written by one
  // and read by the other — so the edge is where it becomes legible.
  const chained: DocumentResponse = {
    ...docWithGap,
    simulation: {
      ...docWithGap.simulation,
      phases: [{
        ...docWithGap.simulation.phases[0],
        steps: [
          { ...docWithGap.simulation.phases[0].steps[0], rst: "/w/prod/prod_0001.rst" },
          {
            ...docWithGap.simulation.phases[0].steps[1],
            resolved_input_coords: "/w/prod/prod_0001.rst",
          },
          docWithGap.simulation.phases[0].steps[2],
        ],
      }],
    },
  };
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json(chained)));
  render(wrap(<Canvas />));

  await waitFor(() => expect(screen.getByText("prod_0003")).toBeInTheDocument());

  // Once on the arrow, once in prod_0001's own rst slot — and never as a raw step id.
  const onArrow = screen.getByTitle(/continues from the restart written above/);
  expect(onArrow).toHaveTextContent("prod_0001.rst");
  expect(screen.queryByText("s1")).not.toBeInTheDocument();
});

it("draws a bare arrow between steps that are not chained to each other", async () => {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json(docWithGap)));
  render(wrap(<Canvas />));

  await waitFor(() => expect(screen.getByText("prod_0003")).toBeInTheDocument());
  // No step names an rst, so there is no file to put on any edge.
  expect(screen.queryByTitle(/continues from the restart written above/)).not.toBeInTheDocument();
});

it("draws the link between steps whose names share no numeric base", async () => {
  // 01_min / 02_nvt / 03_npt each form their own group (the base is the whole name), which
  // is exactly what an equilibration folder looks like. An arrow drawn only inside a group
  // would never appear here at all.
  const equil: DocumentResponse = {
    ...docWithGap,
    simulation: {
      ...docWithGap.simulation,
      phases: [{
        id: "p0", name: "Equilibration", role: "equilibration",
        steps: [
          makeStep({ id: "e0", name: "01_min", rst: "/w/equil/01_min.rst" }),
          makeStep({
            id: "e1", name: "02_nvt", rst: "/w/equil/02_nvt.rst",
            input_coords: { source: "step", ref: "e0", path: null },
            resolved_input_coords: "/w/equil/01_min.rst",
          }),
          makeStep({
            id: "e2", name: "03_npt",
            input_coords: { source: "step", ref: "e1", path: null },
            resolved_input_coords: "/w/equil/02_nvt.rst",
          }),
        ],
      }],
    },
  };
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json(equil)));
  render(wrap(<Canvas />));

  await waitFor(() => expect(screen.getByText("03_npt")).toBeInTheDocument());

  const links = screen.getAllByTitle(/continues from the restart written above/);
  expect(links).toHaveLength(2);
  expect(links[0]).toHaveTextContent("01_min.rst");
  expect(links[1]).toHaveTextContent("02_nvt.rst");
});

it("puts a missing-run ghost in the band of the member the finding names", async () => {
  // A multi-lineage phase, which is what discover now produces: same-role runs from every
  // member share one phase. The finding is scoped to rep2, so rep1 -- which is complete --
  // must gain nothing, and the ghost must read like the runs beside it.
  const replicas: DocumentResponse = {
    ...docWithGap,
    simulation: {
      ...docWithGap.simulation,
      phases: [{
        id: "p0", name: "Production", role: "production",
        steps: [
          makeStep({ id: "a1", name: "rep1/prod_0001", lineage: "rep1" }),
          makeStep({ id: "a2", name: "rep1/prod_0002", lineage: "rep1" }),
          makeStep({ id: "b1", name: "rep2/prod_0001", lineage: "rep2" }),
        ],
      }],
    },
  };
  const shortMember: Suggestion[] = [{
    id: "sug_1",
    kind: "missing_run",
    severity: "needs_you",
    title: "rep2/prod sequence is missing member(s) 2",
    evidence: "'rep2/prod' has no run at index(es) 2",
    actions: ["Mark as expected gap", "Locate file", "Ignore"],
    base: "prod",            // the server drops the directory; the group keeps it
    missing: [2],
    lineage: "rep2",
  }];

  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json(replicas)));
  render(wrap(<Canvas />, shortMember));

  await waitFor(() => expect(screen.getByText("rep2/prod_0001")).toBeInTheDocument());

  // Exactly one ghost, named for rep2, and drawn after rep2's own first run rather than
  // inside rep1's complete band.
  const ghost = screen.getByText("rep2/prod_0002");
  expect(ghost.closest("div")?.className).toMatch(/border-dashed/);
  expect(screen.queryByText("rep1/prod_0003")).not.toBeInTheDocument();
  expect(screen.queryAllByText(/^rep\d\/prod_0002$/)).toHaveLength(2); // rep1's real run + rep2's ghost

  const rep2First = screen.getByText("rep2/prod_0001");
  expect(rep2First.compareDocumentPosition(ghost) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("spells a ghost the way the band around it is spelled", async () => {
  // A ghost is a filename the user is being sent to look for, so `prod_0002` beside runs
  // called `prod.0001` and `prod.0003` is a wrong answer, not a cosmetic one. The
  // separator was hardcoded to "_", which stayed invisible while the server detected no
  // dot-numbered sequences at all and so produced no findings to draw ghosts from.
  const dotted: DocumentResponse = {
    ...docWithGap,
    simulation: {
      ...docWithGap.simulation,
      phases: [{
        id: "p0", name: "Production", role: "production",
        steps: [
          makeStep({ id: "a1", name: "prod.0001" }),
          makeStep({ id: "a3", name: "prod.0003" }),
        ],
      }],
    },
  };
  const hole: Suggestion[] = [{
    id: "sug_1",
    kind: "missing_run",
    severity: "needs_you",
    title: "prod sequence is missing member(s) 2",
    evidence: "present members of 'prod' skip index(es) 2",
    actions: ["Mark as expected gap", "Locate file", "Ignore"],
    base: "prod",
    missing: [2],
    lineage: null,
  }];

  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json(dotted)));
  render(wrap(<Canvas />, hole));

  await waitFor(() => expect(screen.getByText("prod.0001")).toBeInTheDocument());
  expect(screen.getByText("prod.0002")).toBeInTheDocument();
  expect(screen.queryByText("prod_0002")).not.toBeInTheDocument();
});
