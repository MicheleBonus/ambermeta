import { useEffect } from "react";
import { afterEach, describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider, useSelection, type SelKind } from "@/state/selection";
import { Inspector } from "./Inspector";
import type { DocumentResponse, PhaseModel, StepModel } from "@/types";

function makeStep(id: string, name: string, over: Partial<StepModel> = {}): StepModel {
  return {
    id, name, topology: null,
    input_coords: { source: "starting_structure", ref: null, path: null },
    mdin: null, mdout: null, mdcrd: null, rst: null, resolved_input_coords: null,
    expected_gap_ps: null, gap_tolerance_ps: null, notes: [],
    ...over,
  };
}

const PHASES: PhaseModel[] = [
  { id: "p0", name: "Production", role: "production",
    steps: [makeStep("s0", "prod_0001"),
            makeStep("s1", "prod_0002", { expected_gap_ps: 20 })] },
  { id: "p1", name: "Heating", role: "heating", steps: [] },
];

const DOC: DocumentResponse = {
  ...emptyDocument,
  simulation: {
    ...emptyDocument.simulation,
    topologies: [{ id: "t0", path: "/work/wt.prmtop", kind: "normal" }],
    phases: PHASES,
  },
};

interface Captured {
  body: unknown;
  params: Record<string, string | readonly string[] | undefined>;
  url: string;
  calls: number;
}

function capture(method: "put" | "delete", path: string): Captured {
  const seen: Captured = { body: undefined, params: {}, url: "", calls: 0 };
  server.use(
    http[method](path, async ({ request, params }) => {
      seen.calls += 1;
      seen.params = params;
      seen.url = request.url;
      if (method === "put") seen.body = await request.json();
      return HttpResponse.json(DOC);
    }),
  );
  return seen;
}

function Select({ kind, id }: { kind: SelKind; id: string }) {
  const { select } = useSelection();
  useEffect(() => { select(kind, id); }, [kind, id]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

async function renderInspector(kind: SelKind, id: string) {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json(DOC)));
  render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <Select kind={kind} id={id} />
        <Inspector />
      </SelectionProvider>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByLabelText("Name")).toBeInTheDocument());
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("selecting a step no longer lands on a placeholder pane", () => {
  it("renames the step from the inspector", async () => {
    const patch = capture("put", "/api/steps/:stepId");
    await renderInspector("step", "s0");

    const name = screen.getByLabelText("Name");
    expect(name).toHaveValue("prod_0001");
    await userEvent.clear(name);
    await userEvent.type(name, "prod_0042{Enter}");

    await waitFor(() => expect(patch.calls).toBe(1));
    expect(patch.params.stepId).toBe("s0");
    expect(patch.body).toEqual({ name: "prod_0042" });
  });

  it("sets and clears the step's topology", async () => {
    const patch = capture("put", "/api/steps/:stepId");
    await renderInspector("step", "s0");

    await userEvent.selectOptions(screen.getByLabelText("Topology"), "t0");
    await waitFor(() => expect(patch.calls).toBe(1));
    expect(patch.body).toEqual({ topology: "t0" });

    // Present-but-null is how the backend distinguishes "clear" from "leave alone".
    await userEvent.selectOptions(screen.getByLabelText("Topology"), "");
    await waitFor(() => expect(patch.calls).toBe(2));
    expect(patch.body).toEqual({ topology: null });
  });

  it("points the step's input coordinates at the restart of another step", async () => {
    const patch = capture("put", "/api/steps/:stepId");
    await renderInspector("step", "s1");

    await userEvent.selectOptions(screen.getByLabelText("Source"), "step");
    await waitFor(() => expect(patch.calls).toBe(1));
    expect(patch.body).toEqual({ input_coords: { source: "step", ref: null, path: null } });
  });

  it("edits the continuity gap and the notes", async () => {
    const patch = capture("put", "/api/steps/:stepId");
    await renderInspector("step", "s0");

    await userEvent.type(screen.getByLabelText("Expected gap (ps)"), "20{Enter}");
    await waitFor(() => expect(patch.calls).toBe(1));
    expect(patch.body).toEqual({ expected_gap_ps: 20 });

    await userEvent.type(screen.getByLabelText("Notes"), "restarted after a node failure");
    await userEvent.tab();
    await waitFor(() => expect(patch.calls).toBe(2));
    expect(patch.body).toEqual({ notes: ["restarted after a node failure"] });
  });

  it("ignores a gap field that is not a number rather than sending NaN", async () => {
    const patch = capture("put", "/api/steps/:stepId");
    await renderInspector("step", "s0");

    await userEvent.type(screen.getByLabelText("Gap tolerance (ps)"), "soon{Enter}");

    await new Promise((r) => setTimeout(r, 20));
    expect(patch.calls).toBe(0);
  });

  it("deletes the step on one click, matching the canvas rather than asking again", async () => {
    const del = capture("delete", "/api/steps/:stepId");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await renderInspector("step", "s0");

    await userEvent.click(screen.getByRole("button", { name: /delete this step/i }));

    await waitFor(() => expect(del.calls).toBe(1));
    expect(confirm).not.toHaveBeenCalled();
  });

  it("clears a gap by blanking the field, instead of quietly restoring the old value", async () => {
    const patch = capture("put", "/api/steps/:stepId");
    await renderInspector("step", "s1");   // the fixture that carries expected_gap_ps

    const field = screen.getByLabelText("Expected gap (ps)");
    await userEvent.clear(field);
    await userEvent.tab();

    await waitFor(() => expect(patch.calls).toBe(1));
    expect(patch.body).toEqual({ expected_gap_ps: null });
  });

  it("records the restart a step writes, on the step that writes it", async () => {
    const patch = capture("put", "/api/steps/:stepId");
    await renderInspector("step", "s0");

    const field = screen.getByLabelText("Restart written (rst)");
    await userEvent.type(field, "equil/02_nvt.rst{Enter}");

    await waitFor(() => expect(patch.calls).toBe(1));
    expect(patch.body).toEqual({ files: { rst: "equil/02_nvt.rst" } });
  });
});

describe("selecting a phase no longer lands on a placeholder pane", () => {
  it("renames the phase and changes its role", async () => {
    const patch = capture("put", "/api/phases/:phaseId");
    await renderInspector("phase", "p0");

    const name = screen.getByLabelText("Name");
    expect(name).toHaveValue("Production");
    await userEvent.clear(name);
    await userEvent.type(name, "Long production{Enter}");
    await waitFor(() => expect(patch.calls).toBe(1));
    expect(patch.body).toEqual({ name: "Long production" });

    await userEvent.selectOptions(screen.getByLabelText("Role"), "equilibration");
    await waitFor(() => expect(patch.calls).toBe(2));
    expect(patch.body).toEqual({ role: "equilibration" });
  });

  it("can keep the phase's steps by reassigning them, which the canvas delete cannot", async () => {
    const del = capture("delete", "/api/phases/:phaseId");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await renderInspector("phase", "p0");

    await userEvent.selectOptions(screen.getByLabelText(/move its steps to/i), "p1");
    await userEvent.click(screen.getByRole("button", { name: /delete this phase/i }));

    await waitFor(() => expect(del.calls).toBe(1));
    expect(del.url).toContain("reassign_to=p1");
  });

  it("offers no reassign target for a phase with no steps", async () => {
    await renderInspector("phase", "p1");
    expect(screen.queryByLabelText(/move its steps to/i)).not.toBeInTheDocument();
  });
});
