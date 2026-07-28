import { afterEach, describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { getToasts, _resetToasts } from "@/lib/toast";
import App from "@/App";
import { DragChip } from "@/components/Canvas/DragChip";
import type { DndContextProps, DragEndEvent } from "@dnd-kit/core";
import type { DocumentResponse, FileType, PhaseModel, StepModel } from "@/types";

// jsdom has no layout, so a real pointer drag can never produce a collision. Wrap the real
// DndContext (every droppable still registers) and keep hold of the props App passes it, so
// the drop-decision path can be driven directly with synthetic events.
const dnd = vi.hoisted(() => ({ props: null as DndContextProps | null }));

vi.mock("@dnd-kit/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@dnd-kit/core")>();
  const { createElement } = await import("react");
  return {
    ...actual,
    DndContext: (props: DndContextProps) => {
      dnd.props = props;
      return createElement(actual.DndContext, props);
    },
  };
});

function step(id: string, name: string): StepModel {
  return {
    id, name, topology: null,
    input_coords: { source: "starting_structure", ref: null, path: null },
    mdin: null, mdout: null, mdcrd: null,
    expected_gap_ps: null, gap_tolerance_ps: null, notes: [],
  };
}

function phase(id: string, name: string, steps: StepModel[] = []): PhaseModel {
  return { id, name, role: "production", steps };
}

function docWith(phases: PhaseModel[]): DocumentResponse {
  return { ...emptyDocument, simulation: { ...emptyDocument.simulation, phases } };
}

const ONE_PHASE = docWith([phase("p0", "Production", [step("s0", "prod_0001")])]);

async function renderApp(doc: DocumentResponse, ready: RegExp) {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json(doc)));
  render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);
  // findAll, not find: a phase named after its role ("Production") also appears as an
  // <option> in the phase header's role select, and this only waits for the canvas.
  await screen.findAllByText(ready);
}

type ActiveSpec = { id: string; fileType?: FileType; path?: string };

/** The shape dnd-kit hands `onDragEnd`, trimmed to the fields App actually reads. */
function dragEvent(active: ActiveSpec, overId: string | null): DragEndEvent {
  const data = active.fileType
    ? { fileType: active.fileType, path: active.path ?? active.id.slice("file:".length) }
    : undefined;
  return {
    active: { id: active.id, data: { current: data } },
    over: overId === null ? null : { id: overId },
  } as unknown as DragEndEvent;
}

async function drop(active: ActiveSpec, overId: string | null) {
  await act(async () => {
    dnd.props?.onDragEnd?.(dragEvent(active, overId));
  });
}

interface Captured {
  body: unknown;
  params: Record<string, string | readonly string[] | undefined>;
  calls: number;
}

/** Captures the body of every POST/PUT to `path`, answering with `doc`. */
function capture(method: "post" | "put", path: string, doc: DocumentResponse = emptyDocument): Captured {
  const seen: Captured = { body: undefined, params: {}, calls: 0 };
  server.use(
    http[method](path, async ({ request, params }) => {
      seen.body = await request.json();
      seen.params = params;
      seen.calls += 1;
      return HttpResponse.json(doc);
    })
  );
  return seen;
}

afterEach(() => _resetToasts());

/** The messages currently on screen, so a silently-dropped file can be told from a rejected one. */
const toastMessages = () => getToasts().map((t) => t.message);

describe("dropping a file onto a phase or the canvas", () => {
  it("creates a step in the phase an .mdin is dropped on", async () => {
    await renderApp(ONE_PHASE, /Production/);
    const steps = capture("post", "/api/phases/:phaseId/steps", ONE_PHASE);

    await drop({ id: "file:/work/heat_001.in", fileType: "mdin" }, "phase:p0");

    await waitFor(() => expect(steps.calls).toBe(1));
    expect(steps.params.phaseId).toBe("p0");
    expect(steps.body).toEqual({ name: "heat_001", mdin: "/work/heat_001.in" });
  });

  it("creates the phase first, then the step, when an .mdin lands on the empty canvas", async () => {
    await renderApp(emptyDocument, /Drop an \.mdin here/);
    const created = docWith([phase("p1", "Phase 1")]);
    const phases = capture("post", "/api/phases", created);
    const steps = capture("post", "/api/phases/:phaseId/steps", created);

    await drop({ id: "file:/work/equil/min.in", fileType: "mdin" }, "canvas");

    await waitFor(() => expect(steps.calls).toBe(1));
    expect(phases.body).toEqual({ name: "Phase 1", role: "" });
    expect(steps.params.phaseId).toBe("p1");
    expect(steps.body).toEqual({ name: "min", mdin: "/work/equil/min.in" });
  });

  it("names the new phase after the phases that already exist", async () => {
    await renderApp(ONE_PHASE, /Production/);
    const phases = capture("post", "/api/phases", docWith([phase("p0", "Production"), phase("p1", "Phase 2")]));
    capture("post", "/api/phases/:phaseId/steps", ONE_PHASE);

    await drop({ id: "file:/work/prod.nc", fileType: "mdcrd" }, "canvas");

    await waitFor(() => expect(phases.body).toEqual({ name: "Phase 2", role: "" }));
  });

  it("bails out without creating a step when the new phase comes back without an id", async () => {
    await renderApp(emptyDocument, /Drop an \.mdin here/);
    const phases = capture("post", "/api/phases", emptyDocument); // no phases in the response
    const steps = capture("post", "/api/phases/:phaseId/steps");

    await drop({ id: "file:/work/min.in", fileType: "mdin" }, "canvas");

    await waitFor(() => expect(phases.calls).toBe(1));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(steps.calls).toBe(0);
  });

  it("still sets the phase topology for a .prmtop", async () => {
    await renderApp(ONE_PHASE, /Production/);
    const assign = capture("post", "/api/assign", ONE_PHASE);

    await drop({ id: "file:/work/wt.prmtop", fileType: "prmtop" }, "phase:p0");

    await waitFor(() => expect(assign.calls).toBe(1));
    expect(assign.body).toEqual({ path: "/work/wt.prmtop", target_type: "phase_topology", target_id: "p0" });
  });

  it("creates a step continuing from a restart file dropped on the phase", async () => {
    // The whole section lights up as the pointer enters it, so the release owes the user
    // something: an .rst/.inpcrd is what a step continues *from*.
    await renderApp(ONE_PHASE, /Production/);
    const steps = capture("post", "/api/phases/:phaseId/steps", ONE_PHASE);

    await drop({ id: "file:/work/equil/heat.rst", fileType: "inpcrd" }, "phase:p0");

    await waitFor(() => expect(steps.calls).toBe(1));
    expect(steps.params.phaseId).toBe("p0");
    expect(steps.body).toEqual({
      name: "heat",
      input_coords: { source: "path", ref: null, path: "/work/equil/heat.rst" },
    });
  });

  it("refuses to make an unrecognised file the phase topology, and says so", async () => {
    // phase_topology rewrites `topology` on EVERY step in the phase; a README doing that
    // silently on one stray drag is the destructive version of doing nothing.
    await renderApp(ONE_PHASE, /Production/);
    const assign = capture("post", "/api/assign", ONE_PHASE);

    await drop({ id: "file:/work/README.md", fileType: "other" }, "phase:p0");

    await waitFor(() => expect(toastMessages()).toHaveLength(1));
    expect(toastMessages()[0]).toMatch(/README\.md/);
    expect(toastMessages()[0]).toMatch(/not a topology/i);
    expect(assign.calls).toBe(0);
  });

  it("refuses an unrecognised file dropped on empty canvas, and says so", async () => {
    await renderApp(ONE_PHASE, /Production/);
    const assign = capture("post", "/api/assign", ONE_PHASE);

    await drop({ id: "file:/work/run.sh", fileType: "other" }, "canvas");

    await waitFor(() => expect(toastMessages()).toHaveLength(1));
    expect(toastMessages()[0]).toMatch(/run\.sh/);
    expect(assign.calls).toBe(0);
  });
});

describe("dropping a file onto a step", () => {
  it("fills the mdout slot for an .mdout, rather than the step topology", async () => {
    await renderApp(ONE_PHASE, /Production/);
    const assign = capture("post", "/api/assign", ONE_PHASE);

    await drop({ id: "file:/work/prod_0001.out", fileType: "mdout" }, "step:s0");

    await waitFor(() => expect(assign.calls).toBe(1));
    expect(assign.body).toEqual({
      path: "/work/prod_0001.out", target_type: "step_slot", target_id: "s0", slot: "mdout",
    });
  });

  it("points the step's input coordinates at an .inpcrd", async () => {
    await renderApp(ONE_PHASE, /Production/);
    const patch = capture("put", "/api/steps/:stepId", ONE_PHASE);

    await drop({ id: "file:/work/wt.inpcrd", fileType: "inpcrd" }, "step:s0");

    await waitFor(() => expect(patch.calls).toBe(1));
    expect(patch.params.stepId).toBe("s0");
    expect(patch.body).toEqual({ input_coords: { source: "path", ref: null, path: "/work/wt.inpcrd" } });
  });

  it("still sets the step topology for a .prmtop", async () => {
    await renderApp(ONE_PHASE, /Production/);
    const assign = capture("post", "/api/assign", ONE_PHASE);

    await drop({ id: "file:/work/wt.prmtop", fileType: "prmtop" }, "step:s0");

    await waitFor(() => expect(assign.calls).toBe(1));
    expect(assign.body).toEqual({ path: "/work/wt.prmtop", target_type: "step_topology", target_id: "s0" });
  });

  it("refuses to make an unrecognised file the step topology, and says so", async () => {
    await renderApp(ONE_PHASE, /Production/);
    const assign = capture("post", "/api/assign", ONE_PHASE);

    await drop({ id: "file:/work/system.pdb", fileType: "other" }, "step:s0");

    await waitFor(() => expect(toastMessages()).toHaveLength(1));
    expect(toastMessages()[0]).toMatch(/system\.pdb/);
    expect(assign.calls).toBe(0);
  });

  it("still honours an explicitly targeted slot, whatever the file type", async () => {
    await renderApp(ONE_PHASE, /Production/);
    const assign = capture("post", "/api/assign", ONE_PHASE);

    await drop({ id: "file:/work/wt.prmtop", fileType: "prmtop" }, "slot:s0:mdin");

    await waitFor(() => expect(assign.calls).toBe(1));
    expect(assign.body).toEqual({
      path: "/work/wt.prmtop", target_type: "step_slot", target_id: "s0", slot: "mdin",
    });
  });
});

describe("the routes that already worked keep working", () => {
  it("pools a .prmtop and flags an HMR one", async () => {
    await renderApp(ONE_PHASE, /Production/);
    const assign = capture("post", "/api/assign", ONE_PHASE);

    await drop({ id: "file:/work/wt_hmr.prmtop", fileType: "prmtop" }, "pool");

    await waitFor(() => expect(assign.calls).toBe(1));
    expect(assign.body).toEqual({ path: "/work/wt_hmr.prmtop", target_type: "pool", kind: "hmr" });
  });

  it("sets the starting structure", async () => {
    await renderApp(ONE_PHASE, /Production/);
    const assign = capture("post", "/api/assign", ONE_PHASE);

    await drop({ id: "file:/work/wt.inpcrd", fileType: "inpcrd" }, "starting");

    await waitFor(() => expect(assign.calls).toBe(1));
    expect(assign.body).toEqual({ path: "/work/wt.inpcrd", target_type: "starting_structure" });
  });

  it("moves a step onto another phase", async () => {
    const two = docWith([phase("p0", "Production", [step("s0", "prod_0001")]), phase("p1", "Heating")]);
    await renderApp(two, /Production/);
    const move = capture("post", "/api/steps/:stepId/move", two);

    await drop({ id: "step:s0" }, "phase:p1");

    await waitFor(() => expect(move.calls).toBe(1));
    expect(move.params.stepId).toBe("s0");
    expect(move.body).toEqual({ phase_id: "p1", index: -1 });
  });

  it("reorders phases", async () => {
    const two = docWith([phase("p0", "Production"), phase("p1", "Heating")]);
    await renderApp(two, /Production/);
    const reorder = capture("post", "/api/phases/reorder", two);

    await drop({ id: "phase:p1" }, "phase:p0");

    await waitFor(() => expect(reorder.calls).toBe(1));
    expect(reorder.body).toEqual({ phase_ids: ["p1", "p0"] });
  });

  it("reorders steps inside one phase", async () => {
    const one = docWith([phase("p0", "Production", [step("s0", "prod_0001"), step("s1", "prod_0002")])]);
    await renderApp(one, /Production/);
    const reorder = capture("post", "/api/phases/:phaseId/steps/reorder", one);

    await drop({ id: "step:s1" }, "step:s0");

    await waitFor(() => expect(reorder.calls).toBe(1));
    expect(reorder.params.phaseId).toBe("p0");
    expect(reorder.body).toEqual({ step_ids: ["s1", "s0"] });
  });

  it("reorders steps when the drop lands on the target step's slot chips", async () => {
    // The chips are the bottom row of a four-row card and the widest one; a reorder released
    // there used to resolve to `slot:s0:mdin` and die with no request and no feedback.
    const one = docWith([phase("p0", "Production", [step("s0", "prod_0001"), step("s1", "prod_0002")])]);
    await renderApp(one, /Production/);
    const reorder = capture("post", "/api/phases/:phaseId/steps/reorder", one);

    await drop({ id: "step:s1" }, "slot:s0:mdin");

    await waitFor(() => expect(reorder.calls).toBe(1));
    expect(reorder.params.phaseId).toBe("p0");
    expect(reorder.body).toEqual({ step_ids: ["s1", "s0"] });
  });

  it("does not move a step into the phase it is already in", async () => {
    // Every gap between steps resolves to the enclosing phase, and move_step is remove+append:
    // a reorder aimed at a gap would silently send the step to the end of its own phase.
    const one = docWith([phase("p0", "Production", [step("s0", "prod_0001"), step("s1", "prod_0002")])]);
    await renderApp(one, /Production/);
    const move = capture("post", "/api/steps/:stepId/move", one);

    await drop({ id: "step:s0" }, "phase:p0");

    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(move.calls).toBe(0);
  });

  it("does nothing when the drop lands outside every target", async () => {
    await renderApp(ONE_PHASE, /Production/);
    const assign = capture("post", "/api/assign", ONE_PHASE);

    await drop({ id: "file:/work/wt.prmtop", fileType: "prmtop" }, null);

    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(assign.calls).toBe(0);
  });
});

describe("DragChip", () => {
  it("shows the dragged file with its icon and base-relative label", () => {
    const { container } = render(
      <DragChip drag={{ id: "file:/work/equil/min.in", fileType: "mdin", path: "/work/equil/min.in" }}
        sim={emptyDocument.simulation} base="/work" />
    );
    expect(screen.getByText("min.in")).toBeInTheDocument();
    expect(screen.getByText("equil/")).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("shows the node's name when a step or a phase is dragged", () => {
    const sim = docWith([phase("p0", "Production", [step("s0", "prod_0001")])]).simulation;
    const { rerender } = render(<DragChip drag={{ id: "step:s0" }} sim={sim} base="/work" />);
    expect(screen.getByText("prod_0001")).toBeInTheDocument();

    rerender(<DragChip drag={{ id: "phase:p0" }} sim={sim} base="/work" />);
    expect(screen.getByText("Production")).toBeInTheDocument();
  });
});
