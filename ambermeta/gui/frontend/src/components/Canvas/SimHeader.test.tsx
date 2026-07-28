import { afterEach, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { makeStep } from "@/test/factories";
import { _resetToasts } from "@/lib/toast";
import { Toaster } from "@/components/common";
import { SimHeader } from "./SimHeader";
import type { SimulationModel } from "@/types";

const sim: SimulationModel = {
  version: 2,
  topologies: [
    { id: "t0", path: "/w/cryst/wt.prmtop", kind: "normal" },
    { id: "t1", path: "/w/cryst/wt_hmr.prmtop", kind: "hmr" },
  ],
  starting_structure: "/w/cryst/wt.crd",
  phases: [{
    id: "p0", name: "Production", role: "production",
    steps: [makeStep({ id: "s0", name: "prod_0001", topology: "t0" }),
            makeStep({ id: "s1", name: "prod_0002", topology: "t0" })],
  }],
};

interface Captured { body: unknown; params: Record<string, unknown>; calls: number }

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

function renderHeader(s: SimulationModel = sim) {
  queryClient.clear();
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <DndContext>
          <SimHeader sim={s} base="/w" />
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

it("removes a topology from the pool — the pool used to be display-only", async () => {
  const del = capture("delete", "/api/topologies/:id");
  renderHeader();

  await userEvent.click(screen.getByRole("button", { name: "remove topology wt.prmtop" }));

  await waitFor(() => expect(del.calls).toBe(1));
  expect(del.params.id).toBe("t0");
});

it("says how many steps a removal would strip, so it is not a silent cascade", () => {
  renderHeader();
  expect(screen.getByRole("button", { name: "remove topology wt.prmtop" }))
    .toHaveAttribute("title", expect.stringContaining("2 step(s)"));
  // Nothing runs against the HMR entry, so its tooltip makes no such claim.
  expect(screen.getByRole("button", { name: "remove topology wt_hmr.prmtop" }))
    .toHaveAttribute("title", "Remove from the pool");
});

it("offers to undo a removal, and the offer runs the real undo", async () => {
  const undone = capture("post", "/api/undo");
  capture("delete", "/api/topologies/:id");
  renderHeader();

  await userEvent.click(screen.getByRole("button", { name: "remove topology wt.prmtop" }));
  const undo = await screen.findByRole("button", { name: "Undo" });
  await userEvent.click(undo);

  await waitFor(() => expect(undone.calls).toBe(1));
});

it("corrects a topology wrongly guessed as HMR", async () => {
  const put = capture("put", "/api/topologies/:id");
  renderHeader();

  await userEvent.selectOptions(
    screen.getByRole("combobox", { name: "topology kind for wt_hmr.prmtop" }), "normal");

  await waitFor(() => expect(put.calls).toBe(1));
  expect(put.params.id).toBe("t1");
  expect(put.body).toEqual({ kind: "normal" });
});

it("clears the starting structure", async () => {
  const put = capture("put", "/api/simulation/starting-structure");
  renderHeader();

  await userEvent.click(screen.getByRole("button", { name: "clear starting structure" }));

  await waitFor(() => expect(put.calls).toBe(1));
  expect(put.body).toEqual({ path: null });
});

it("offers a way in when no starting structure is set yet, not just a drop hint", async () => {
  renderHeader({ ...sim, starting_structure: null });
  expect(screen.queryByRole("button", { name: "clear starting structure" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /choose a file/ }));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
});

it("shows pooled topologies as file labels, not absolute paths", () => {
  renderHeader();
  expect(screen.getByText("wt.prmtop")).toBeInTheDocument();
  expect(screen.getByTitle("/w/cryst/wt.prmtop")).toBeInTheDocument();
});
