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
import { buildStepIndex } from "@/lib/chain";
import { makeStep } from "@/test/factories";
import { _resetToasts } from "@/lib/toast";
import { Toaster } from "@/components/common";
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
  rst: null,
  resolved_input_coords: null,
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

function renderPhase(p: PhaseModel = phase, tops: TopologyModel[] = topologies) {
  queryClient.clear();
  const stepIndex = buildStepIndex({
    version: 2, topologies: tops, starting_structure: null, phases: [p],
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <DndContext>
          <SuggestionsContext.Provider value={[]}>
            <PhaseSection phase={p} topologies={tops} base="/w" stepIndex={stepIndex} />
            <Toaster />
          </SuggestionsContext.Provider>
        </DndContext>
      </SelectionProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  _resetToasts();
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

// --- the topology control reports state instead of resetting itself -----------

const TOPS: TopologyModel[] = [
  { id: "t0", path: "/w/wt.prmtop", kind: "normal" },
  { id: "t1", path: "/w/wt_hmr.prmtop", kind: "hmr" },
];

function phaseWith(...topologies: (string | null)[]): PhaseModel {
  return {
    id: "p0", name: "Production", role: "production",
    steps: topologies.map((t, i) => makeStep({ id: `s${i}`, name: `prod_000${i + 1}`, topology: t })),
  };
}

it("shows the topology its steps actually hold, instead of snapping back to a placeholder", () => {
  renderPhase(phaseWith("t1", "t1"), TOPS);
  const select = screen.getByLabelText("set topology for Production") as HTMLSelectElement;
  expect(select.value).toBe("t1");
});

it("reports a phase whose steps disagree as mixed, without pretending one of them won", () => {
  renderPhase(phaseWith("t0", "t1"), TOPS);
  const select = screen.getByLabelText("set topology for Production") as HTMLSelectElement;
  expect(select.value).not.toBe("t0");
  expect(screen.getByRole("option", { name: "Mixed" })).toBeInTheDocument();
});

it("keeps showing the chosen topology after applying it, rather than flickering back", async () => {
  const put = capture("put", "/api/phases/:phaseId");
  renderPhase(phaseWith(null, null), TOPS);
  const select = screen.getByLabelText("set topology for Production") as HTMLSelectElement;
  expect(select.value).toBe("");

  await userEvent.selectOptions(select, "t1");
  await waitFor(() => expect(put.calls).toBe(1));
  expect(put.body).toEqual({ topology: "t1" });
  // One request, not one per step: the fan-out is a single undoable operation.
  expect(put.params.phaseId).toBe("p0");
});

it("clears the topology off every step in the phase from the same control", async () => {
  const put = capture("put", "/api/phases/:phaseId");
  renderPhase(phaseWith("t1", "t1"), TOPS);

  await userEvent.selectOptions(screen.getByLabelText("set topology for Production"), "");
  await waitFor(() => expect(put.calls).toBe(1));
  expect(put.body).toEqual({ topology: null });
});

it("deletes an empty phase without a confirmation and offers to undo it", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const del = capture("delete", "/api/phases/:phaseId");
  renderPhase({ id: "p0", name: "Production", role: "production", steps: [] }, TOPS);

  await userEvent.click(screen.getByLabelText("delete phase Production"));
  await waitFor(() => expect(del.calls).toBe(1));
  expect(confirm).not.toHaveBeenCalled();
  expect(await screen.findByRole("button", { name: "Undo" })).toBeInTheDocument();
});

it("does not offer a topology on a phase with nothing to apply it to", () => {
  // The control writes through to the steps, so with none it would accept a choice,
  // change nothing, and snap back — the flicker again, in a new place.
  renderPhase({ id: "p0", name: "Production", role: "production", steps: [] }, TOPS);
  expect(screen.getByLabelText("set topology for Production")).toBeDisabled();
});
