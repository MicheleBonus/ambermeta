import { afterEach, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { SuggestionsContext } from "@/components/Suggestions/suggestionsContext";
import { makeStep } from "@/test/factories";
import { Canvas } from "./Canvas";
import type { DocumentResponse, StepModel } from "@/types";

/**
 * Bands are the outer grouping level; `groupSteps` stays as the inner one. What is asserted
 * here is what PR 2a did NOT do: the tag appeared nowhere in the UI, and an arrow was drawn
 * between the last run of one member and the first run of the next — an adjacency that
 * means nothing, in a document `discover` lays out phase-major precisely so that same-role
 * runs from every member sit together.
 */

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

function doc(steps: StepModel[]): DocumentResponse {
  return {
    ...emptyDocument,
    simulation: {
      ...emptyDocument.simulation,
      phases: [{ id: "p0", name: "Production", role: "production", steps }],
    },
  };
}

async function show(steps: StepModel[]) {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json(doc(steps))));
  render(wrap(<Canvas />));
  await waitFor(() => expect(screen.getByText(steps[0].name)).toBeInTheDocument());
}

/** Every rendered continuity arrow, labelled or bare. */
const arrows = () => document.querySelectorAll("[data-testid='continuity-arrow']");

const TWO_MEMBERS: StepModel[] = [
  makeStep({ id: "a1", name: "rep1/prod_0001", lineage: "rep1" }),
  makeStep({
    id: "a2", name: "rep1/prod_0002", lineage: "rep1",
    input_coords: { source: "step", ref: "a1", path: null },
  }),
  makeStep({ id: "b1", name: "rep2/prod_0001", lineage: "rep2" }),
  makeStep({
    id: "b2", name: "rep2/prod_0002", lineage: "rep2",
    input_coords: { source: "step", ref: "b1", path: null },
  }),
];

afterEach(() => queryClient.clear());

it("names each member and how many runs it holds", async () => {
  await show(TWO_MEMBERS);
  expect(screen.getByText("rep1")).toBeInTheDocument();
  expect(screen.getByText("rep2")).toBeInTheDocument();
  expect(screen.getAllByText("· 2 run(s)")).toHaveLength(2);
});

it("draws no arrow across a band boundary", async () => {
  // Four steps in one phase. Within rep1: one arrow. Within rep2: one arrow. Between
  // them: none — rep2's first run does not continue rep1's last, and saying it does is
  // the false claim the whole feature exists to stop.
  await show(TWO_MEMBERS);
  expect(arrows()).toHaveLength(2);
});

it("leaves an untagged phase exactly as it was", async () => {
  // The control. Three chained steps, no tags: three cards, two arrows, no band chrome.
  await show([
    makeStep({ id: "s1", name: "prod_0001" }),
    makeStep({ id: "s2", name: "prod_0002", input_coords: { source: "step", ref: "s1", path: null } }),
    makeStep({ id: "s3", name: "prod_0003", input_coords: { source: "step", ref: "s2", path: null } }),
  ]);
  expect(arrows()).toHaveLength(2);
  expect(screen.queryByText("no lineage")).not.toBeInTheDocument();
  expect(document.querySelector("[data-lineage]")).toBeNull();
});

it("keeps the arrow between steps that share no numeric base", async () => {
  // The equilibration case, and the reason band suppression keys on the LINEAGE changing
  // rather than on the group changing: 01_min / 02_nvt / 03_npt are three groups of one,
  // so a rule written against groups would delete every arrow in the folder.
  await show([
    makeStep({ id: "m", name: "01_min", lineage: "rep1" }),
    makeStep({ id: "n", name: "02_nvt", lineage: "rep1",
               input_coords: { source: "step", ref: "m", path: null } }),
    makeStep({ id: "p", name: "03_npt", lineage: "rep1",
               input_coords: { source: "step", ref: "n", path: null } }),
  ]);
  expect(arrows()).toHaveLength(2);
});

it("names the branch point the members share", async () => {
  await show([
    makeStep({ id: "e", name: "common/equil" }),
    makeStep({ id: "a", name: "rep1/prod", lineage: "rep1",
               input_coords: { source: "step", ref: "e", path: null } }),
    makeStep({ id: "b", name: "rep2/prod", lineage: "rep2",
               input_coords: { source: "step", ref: "e", path: null } }),
  ]);
  expect(screen.getByText("2 lineages branch from common/equil")).toBeInTheDocument();
});

it("says nothing about a branch point the members do not share", async () => {
  await show(TWO_MEMBERS);
  expect(screen.queryByText(/lineages branch from/)).not.toBeInTheDocument();
});

it("retags a whole band in one request", async () => {
  // Not a loop of per-step PUTs: each of those deep-copies the document onto the undo
  // stack, so annotating a 200-step campaign evicts the Discover result being annotated.
  let body: unknown;
  let calls = 0;
  server.use(http.patch("/api/steps/lineage", async ({ request }) => {
    calls += 1;
    body = await request.json();
    return HttpResponse.json(doc(TWO_MEMBERS));
  }));
  await show(TWO_MEMBERS);

  await userEvent.click(screen.getByText("rep1"));
  const input = await screen.findByLabelText("set lineage for rep1");
  await userEvent.clear(input);
  await userEvent.type(input, "wt_rep1{Enter}");

  await waitFor(() => expect(calls).toBe(1));
  expect(body).toEqual({ ids: ["a1", "a2"], lineage: "wt_rep1" });
});

it("clears a band's tag with null rather than an empty string", async () => {
  // "" would name a member nobody can refer to. The server reads presence, so null is how
  // a tag is removed — and `buckets` treats a falsy tag as untagged either way, which is
  // exactly why the wire value has to be unambiguous.
  let body: unknown;
  server.use(http.patch("/api/steps/lineage", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json(doc(TWO_MEMBERS));
  }));
  await show(TWO_MEMBERS);
  await userEvent.click(screen.getByLabelText("clear lineage rep2"));
  await waitFor(() => expect(body).toEqual({ ids: ["b1", "b2"], lineage: null }));
});
