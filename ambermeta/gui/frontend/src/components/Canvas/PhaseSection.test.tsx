import { afterEach, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { SuggestionsContext } from "@/components/Suggestions/suggestionsContext";
import { PhaseSection } from "./PhaseSection";
import type { PhaseModel, StepModel, TopologyModel } from "@/types";

const topologies: TopologyModel[] = [{ id: "t0", path: "/w/wt.prmtop", kind: "normal" }];

const step: StepModel = {
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
};

const phase: PhaseModel = { id: "p0", name: "Production", role: "production", steps: [step] };

interface Captured {
  body: unknown;
  params: Record<string, string | readonly string[] | undefined>;
  calls: number;
}

/** Records every call to `path`, answering with a document so the mutation settles. */
function capture(method: "post" | "put" | "delete", path: string): Captured {
  const seen: Captured = { body: undefined, params: {}, calls: 0 };
  server.use(
    http[method](path, async ({ request, params }) => {
      seen.calls += 1;
      seen.params = params;
      if (method !== "delete") seen.body = await request.json();
      return HttpResponse.json(emptyDocument);
    }),
  );
  return seen;
}

function renderPhase(p: PhaseModel = phase) {
  queryClient.clear();
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <DndContext>
          <SuggestionsContext.Provider value={[]}>
            <PhaseSection phase={p} topologies={topologies} base="/w" />
          </SuggestionsContext.Provider>
        </DndContext>
      </SelectionProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

it("shows the phase's current role in the select rather than a blank chooser", () => {
  const withRole = renderPhase();
  expect(screen.getByLabelText("set role for Production")).toHaveValue("production");
  withRole.unmount();

  renderPhase({ ...phase, role: "" });
  expect(screen.getByLabelText("set role for Production")).toHaveValue("");
});

it("commits a role change from the canvas", async () => {
  const patch = capture("put", "/api/phases/:phaseId");
  renderPhase();

  await userEvent.selectOptions(screen.getByLabelText("set role for Production"), "heating");

  await waitFor(() => expect(patch.calls).toBe(1));
  expect(patch.params.phaseId).toBe("p0");
  expect(patch.body).toEqual({ role: "heating" });
  // Controlled off the prop: the select shows the document's role until it comes back.
  expect(screen.getByLabelText("set role for Production")).toHaveValue("production");
});

it("renames the phase in place: double-click, type, Enter", async () => {
  const patch = capture("put", "/api/phases/:phaseId");
  renderPhase();

  await userEvent.dblClick(screen.getByRole("button", { name: "Production" }));
  const input = screen.getByLabelText("rename phase Production");
  await userEvent.clear(input);
  await userEvent.type(input, "Long production{Enter}");

  await waitFor(() => expect(patch.calls).toBe(1));
  expect(patch.body).toEqual({ name: "Long production" });
});

it("abandons an in-place phase rename on Escape without touching the document", async () => {
  const patch = capture("put", "/api/phases/:phaseId");
  renderPhase();

  await userEvent.dblClick(screen.getByRole("button", { name: "Production" }));
  const input = screen.getByLabelText("rename phase Production");
  await userEvent.clear(input);
  await userEvent.type(input, "discard me{Escape}");

  expect(screen.queryByLabelText("rename phase Production")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Production" })).toBeInTheDocument();
  expect(patch.calls).toBe(0);
});

it("adds a step to the phase without a drag, numbered so two clicks are tellable apart", async () => {
  const created = capture("post", "/api/phases/:phaseId/steps");
  renderPhase();

  await userEvent.click(screen.getByRole("button", { name: "add step to Production" }));

  await waitFor(() => expect(created.calls).toBe(1));
  expect(created.params.phaseId).toBe("p0");
  // A fixed "step" also collided with the group key, so two of them logged duplicate React keys.
  expect(created.body).toEqual({ name: "step 2" });
});

it("keeps two same-named groups apart instead of collapsing them onto one key", async () => {
  // groupSteps keys by the first step's id: "step", "min", "step" is three groups, and keying
  // by the base would give two children the key "step".
  const warn = vi.spyOn(console, "error").mockImplementation(() => {});
  const named = (id: string, name: string): StepModel => ({ ...step, id, name });
  renderPhase({
    ...phase,
    steps: [named("a", "step"), named("b", "min"), named("c", "step")],
  });

  expect(screen.getAllByText("step")).toHaveLength(2);
  expect(warn.mock.calls.flat().join(" ")).not.toMatch(/same key/i);
});

it("renames a phase from the keyboard with F2, not only by double-click", async () => {
  const patch = capture("put", "/api/phases/:phaseId");
  renderPhase();

  const name = screen.getByRole("button", { name: "Production" });
  name.focus();
  await userEvent.keyboard("{F2}");
  const input = screen.getByLabelText("rename phase Production");
  await userEvent.clear(input);
  await userEvent.type(input, "Long production{Enter}");

  await waitFor(() => expect(patch.calls).toBe(1));
  expect(patch.body).toEqual({ name: "Long production" });
});

it("deletes the phase only once the confirm is accepted", async () => {
  const del = capture("delete", "/api/phases/:phaseId");
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  renderPhase();

  await userEvent.click(screen.getByRole("button", { name: "delete phase Production" }));
  expect(confirm).toHaveBeenCalled();
  expect(del.calls).toBe(0);

  confirm.mockReturnValue(true);
  await userEvent.click(screen.getByRole("button", { name: "delete phase Production" }));
  await waitFor(() => expect(del.calls).toBe(1));
});
