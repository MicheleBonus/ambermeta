import { afterEach, it, expect, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { buildStepIndex } from "@/lib/chain";
import { makeStep } from "@/test/factories";
import { _resetToasts } from "@/lib/toast";
import { Toaster } from "@/components/common";
import { StepNode } from "./StepNode";
import type { FileInfo, StepModel, TopologyModel } from "@/types";

const topology: TopologyModel = { id: "t0", path: "/w/setup/wt_hmr.prmtop", kind: "hmr" };

const step: StepModel = makeStep({
  id: "s0", name: "prod_0001", topology: "t0",
  mdin: "/w/equil/01_min.mdin", mdout: "/w/runs/01_min.mdout",
});

/** One file per slot type, so a filtered picker is visibly narrower than the tree. */
const PICKABLE: FileInfo[] = [
  { path: "/w/runs/prod_0001.mdcrd", name: "prod_0001.mdcrd", file_type: "mdcrd",
    is_directory: false, size: 1, extension: ".mdcrd", parent: "/w/runs", children: null },
  { path: "/w/equil/02_heat.mdin", name: "02_heat.mdin", file_type: "mdin",
    is_directory: false, size: 1, extension: ".mdin", parent: "/w/equil", children: null },
];

interface Captured {
  body: unknown;
  calls: number;
}

/** Records every call to `path`, answering with a document so the mutation settles. */
function capture(method: "put" | "delete", path: string): Captured {
  const seen: Captured = { body: undefined, calls: 0 };
  server.use(
    http[method](path, async ({ request }) => {
      seen.calls += 1;
      if (method === "put") seen.body = await request.json();
      return HttpResponse.json(emptyDocument);
    }),
  );
  return seen;
}

function renderStep(s: StepModel = step, others: StepModel[] = []) {
  queryClient.clear();
  const stepIndex = buildStepIndex({
    version: 2, topologies: [], starting_structure: null,
    phases: [{ id: "p0", name: "Production", role: "production", steps: [...others, s] }],
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <DndContext>
          <StepNode step={s} topology={topology} base="/w" stepIndex={stepIndex} />
          <Toaster />
        </DndContext>
      </SelectionProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  _resetToasts();
});

it("renders each filled slot as a folder-qualified label that keeps its extension", () => {
  renderStep();

  expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
  expect(screen.getByText("equil/")).toBeInTheDocument();
  expect(screen.getByText("01_min.mdout")).toBeInTheDocument();
  expect(screen.getByText("runs/")).toBeInTheDocument();
  // The bare basename split this replaces would have shown both as "01_min".
  expect(screen.queryByText("01_min")).not.toBeInTheDocument();
  // The full path survives as a tooltip rather than as visible text.
  expect(screen.getByTitle("/w/equil/01_min.mdin")).toBeInTheDocument();
  expect(screen.queryByText("/w/equil/01_min.mdin")).not.toBeInTheDocument();
});

it("renders the topology line as a file label instead of a raw absolute path", () => {
  renderStep();

  expect(screen.getByText("wt_hmr.prmtop")).toBeInTheDocument();
  expect(screen.getByText("setup/")).toBeInTheDocument();
  expect(screen.queryByText(/\/w\/setup\/wt_hmr\.prmtop/)).not.toBeInTheDocument();
  expect(screen.getByTitle("/w/setup/wt_hmr.prmtop")).toBeInTheDocument();
});

it("keeps its slot, step and drag registrations intact", () => {
  const { container } = renderStep();

  expect(container.querySelector('[data-droppable-id="step:s0"]')).not.toBeNull();
  for (const kind of ["mdin", "mdout", "mdcrd"]) {
    expect(container.querySelector(`[data-droppable-id="slot:s0:${kind}"]`)).not.toBeNull();
  }
  expect(screen.getByLabelText("drag step prod_0001")).toBeInTheDocument();
  // An empty slot still reads as empty.
  expect(container.querySelector('[data-droppable-id="slot:s0:mdcrd"]')?.textContent).toMatch(/—/);
});

it("names an empty slot chip after what activating it does, not after its em dash", () => {
  renderStep();
  // The visible text of an empty chip is "mdcrd: —", which conveys nothing to a screen reader.
  expect(screen.getByRole("button", { name: "choose a mdcrd file" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "change mdin: /w/equil/01_min.mdin" })).toBeInTheDocument();
});

it("opens a picker limited to the slot's own file type when a chip is clicked", async () => {
  server.use(http.get("/api/files", () => HttpResponse.json(PICKABLE)));
  renderStep();

  await userEvent.click(screen.getByRole("button", { name: "choose a mdcrd file" }));

  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("prod_0001.mdcrd")).toBeInTheDocument();
  // The picker names mdcrd, so it must not offer the .mdin sitting next to it.
  expect(within(dialog).queryByText("02_heat.mdin")).not.toBeInTheDocument();
});

it("patches only the picked slot when a file is chosen in the chip's picker", async () => {
  server.use(http.get("/api/files", () => HttpResponse.json(PICKABLE)));
  const patch = capture("put", "/api/steps/:stepId");
  renderStep();

  await userEvent.click(screen.getByRole("button", { name: "choose a mdcrd file" }));
  await userEvent.click(await screen.findByText("prod_0001.mdcrd"));

  await waitFor(() => expect(patch.calls).toBe(1));
  expect(patch.body).toEqual({ files: { mdcrd: "/w/runs/prod_0001.mdcrd" } });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("clears a filled slot with the empty string the backend expects, and opens no picker", async () => {
  const patch = capture("put", "/api/steps/:stepId");
  renderStep();

  // Only filled slots offer the affordance.
  expect(screen.queryByRole("button", { name: "clear mdcrd" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "clear mdin" }));

  await waitFor(() => expect(patch.calls).toBe(1));
  expect(patch.body).toEqual({ files: { mdin: "" } });
  // The × sits inside the chip; it must not fall through to the chip's picker.
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("renders dropped input coordinates as a file label rather than a raw absolute path", () => {
  // The step_input_coords drop route is what puts a path here, and a path has no break
  // opportunities: rendered plainly it overflows the step card and the phase around it.
  renderStep({
    ...step,
    input_coords: { source: "path", ref: null, path: "/w/equil/wt_restart.rst" },
  });

  expect(screen.getByText("wt_restart.rst")).toBeInTheDocument();
  expect(screen.getByTitle("/w/equil/wt_restart.rst")).toBeInTheDocument();
  expect(screen.queryByText(/◂ \/w\/equil\/wt_restart\.rst/)).not.toBeInTheDocument();
});

it("still shows the two non-path coordinate sources as plain text", () => {
  renderStep();
  expect(screen.getByText(/starting structure/)).toBeInTheDocument();
});

it("names the step it continues from, never the internal id", () => {
  // The id is a uuid4 hex slice, so printing `input_coords.ref` verbatim told the user
  // their run started from something called "s_prev".
  const producer = makeStep({
    id: "s_prev", name: "01_min", rst: "/w/equil/01_min.rst",
  });
  renderStep(
    {
      ...step,
      input_coords: { source: "step", ref: "s_prev", path: null },
      resolved_input_coords: "/w/equil/01_min.rst",
    },
    [producer],
  );

  expect(screen.getByText(/restart of 01_min/)).toBeInTheDocument();
  expect(screen.getByText("01_min.rst")).toBeInTheDocument();
  expect(screen.queryByText(/s_prev/)).not.toBeInTheDocument();
});

it("says so when the step it continues from names no restart", () => {
  renderStep(
    { ...step, input_coords: { source: "step", ref: "s_prev", path: null } },
    [makeStep({ id: "s_prev", name: "01_min" })],
  );
  expect(screen.getByText(/restart of 01_min/)).toBeInTheDocument();
  expect(screen.getByText(/no file yet/)).toBeInTheDocument();
});

it("does not pretend a deleted step is still there", () => {
  renderStep({ ...step, input_coords: { source: "step", ref: "gone", path: null } });
  expect(screen.getByText(/no longer here/)).toBeInTheDocument();
});

it("renames a step from the keyboard with F2, not only by double-click", async () => {
  // A double-click is unreachable without a mouse, and Enter/Space on the name only selects.
  const patch = capture("put", "/api/steps/:stepId");
  renderStep();

  const name = screen.getByRole("button", { name: "prod_0001" });
  expect(name).toHaveAttribute("aria-keyshortcuts", "F2");
  name.focus();
  await userEvent.keyboard("{F2}");

  const input = screen.getByLabelText("rename step prod_0001");
  await userEvent.clear(input);
  await userEvent.type(input, "prod_0009{Enter}");

  await waitFor(() => expect(patch.calls).toBe(1));
  expect(patch.body).toEqual({ name: "prod_0009" });
});

it("renames the step in place: double-click, type, Enter", async () => {
  const patch = capture("put", "/api/steps/:stepId");
  renderStep();

  await userEvent.dblClick(screen.getByRole("button", { name: "prod_0001" }));
  const input = screen.getByLabelText("rename step prod_0001");
  await userEvent.clear(input);
  await userEvent.type(input, "prod_0009{Enter}");

  await waitFor(() => expect(patch.calls).toBe(1));
  expect(patch.body).toEqual({ name: "prod_0009" });
});

it("commits an in-place rename on blur too", async () => {
  const patch = capture("put", "/api/steps/:stepId");
  renderStep();

  await userEvent.dblClick(screen.getByRole("button", { name: "prod_0001" }));
  const input = screen.getByLabelText("rename step prod_0001");
  await userEvent.clear(input);
  await userEvent.type(input, "prod_0042");
  await userEvent.tab();

  await waitFor(() => expect(patch.calls).toBe(1));
  expect(patch.body).toEqual({ name: "prod_0042" });
});

it("abandons an in-place rename on Escape without touching the document", async () => {
  const patch = capture("put", "/api/steps/:stepId");
  renderStep();

  await userEvent.dblClick(screen.getByRole("button", { name: "prod_0001" }));
  const input = screen.getByLabelText("rename step prod_0001");
  await userEvent.clear(input);
  await userEvent.type(input, "discard me{Escape}");

  expect(screen.queryByLabelText("rename step prod_0001")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "prod_0001" })).toBeInTheDocument();
  expect(patch.calls).toBe(0);
});

it("deletes the step on one click and offers to undo it, without a confirm dialog", async () => {
  // A confirm taxes every correct click to guard the rare wrong one, and stops guarding
  // anything once the habit of dismissing it forms. The Undo offer is the trade.
  const del = capture("delete", "/api/steps/:stepId");
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  renderStep();

  await userEvent.click(screen.getByRole("button", { name: "delete step prod_0001" }));

  await waitFor(() => expect(del.calls).toBe(1));
  expect(confirm).not.toHaveBeenCalled();
  expect(await screen.findByRole("button", { name: "Undo" })).toBeInTheDocument();
});

it("retires the Undo offer as soon as another change lands on the document", async () => {
  // Undo pops the newest snapshot, so an offer that outlived its edit would reverse
  // somebody else's.
  capture("delete", "/api/steps/:stepId");
  const patch = capture("put", "/api/steps/:stepId");
  renderStep();

  await userEvent.click(screen.getByRole("button", { name: "delete step prod_0001" }));
  expect(await screen.findByRole("button", { name: "Undo" })).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "clear topology" }));
  await waitFor(() => expect(patch.calls).toBe(1));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument());
});

it("clears a step's topology from the card, not only from the inspector", async () => {
  const patch = capture("put", "/api/steps/:stepId");
  renderStep();

  await userEvent.click(screen.getByRole("button", { name: "clear topology" }));

  await waitFor(() => expect(patch.calls).toBe(1));
  expect(patch.body).toEqual({ topology: null });
});

it("carries a slot for the restart the run writes", async () => {
  const patch = capture("put", "/api/steps/:stepId");
  renderStep({ ...step, rst: "/w/equil/02_nvt.rst" });

  expect(screen.getByText("02_nvt.rst")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "clear rst" }));

  await waitFor(() => expect(patch.calls).toBe(1));
  expect(patch.body).toEqual({ files: { rst: "" } });
});

it("does not claim a step vanished when none was ever chosen", () => {
  // Switching the source to "the restart of another step" leaves ref null until a step is
  // picked; reporting that as a deleted step announces data loss that never happened.
  renderStep({ ...step, input_coords: { source: "step", ref: null, path: null } });
  expect(screen.getByText(/no step chosen yet/)).toBeInTheDocument();
  expect(screen.queryByText(/no longer here/)).not.toBeInTheDocument();
});
