import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider, useSelection } from "@/state/selection";
import { PropertiesPanel } from "./PropertiesPanel";
import type { StageModel } from "@/types";
import { useEffect } from "react";

function mkStage(p: Partial<StageModel>): StageModel {
  return { id: "", name: "", role: "", prmtop: null, mdin: null, mdout: null, mdcrd: null,
    inpcrd: null, expected_gap_ps: null, gap_tolerance_ps: null, notes: [], ...p };
}

function Select({ id }: { id: string }) {
  const { select } = useSelection();
  useEffect(() => { select(id); }, [id, select]);
  return null;
}

function renderPanel(stageId: string, stages: StageModel[]) {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, stages })));
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <Select id={stageId} />
        <PropertiesPanel />
      </SelectionProvider>
    </QueryClientProvider>
  );
}

describe("PropertiesPanel", () => {
  it("commits a name edit on blur via updateStage", async () => {
    const calls: unknown[] = [];
    server.use(
      http.put("/api/stages/1", async ({ request }) => {
        calls.push(await request.json());
        return HttpResponse.json(emptyDocument);
      })
    );
    renderPanel("1", [mkStage({ id: "1", name: "min" })]);
    const name = await screen.findByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "minim");
    await userEvent.tab(); // blur
    await waitFor(() => expect(calls).toEqual([{ name: "minim" }]));
  });

  it("edits global settings when nothing is selected", async () => {
    const calls: unknown[] = [];
    server.use(
      http.get("/api/document", () => HttpResponse.json(emptyDocument)),
      http.put("/api/settings", async ({ request }) => {
        calls.push(await request.json());
        return HttpResponse.json(emptyDocument);
      })
    );
    queryClient.clear();
    render(
      <QueryClientProvider client={queryClient}>
        <SelectionProvider><PropertiesPanel /></SelectionProvider>
      </QueryClientProvider>
    );
    const strict = await screen.findByLabelText(/strict validation/i);
    await userEvent.click(strict);
    await waitFor(() => expect(calls.length).toBe(1));
  });

  it("Pick… assigns a file to a stage slot", async () => {
    const calls: unknown[] = [];
    server.use(
      http.get("/api/files", () => HttpResponse.json([
        { path: "/work/min.in", name: "min.in", file_type: "mdin", is_directory: false,
          size: 1, extension: ".mdin", parent: "/work", children: null },
      ])),
      http.put("/api/stages/1", async ({ request }) => { calls.push(await request.json()); return HttpResponse.json(emptyDocument); }),
    );
    renderPanel("1", [mkStage({ id: "1", name: "min" })]);
    // open the picker for the mdin slot
    const pickButtons = await screen.findAllByRole("button", { name: "Pick…" });
    await userEvent.click(pickButtons[1]); // prmtop, mdin, mdout, mdcrd, inpcrd order -> [1] = mdin
    await userEvent.click(await screen.findByText("/work/min.in"));
    await waitFor(() => expect(calls).toEqual([{ files: { mdin: "/work/min.in" } }]));
  });

  it("Delete stage button calls DELETE /api/stages/{id}", async () => {
    let deleted = false;
    server.use(
      http.delete("/api/stages/1", () => {
        deleted = true;
        return HttpResponse.json(emptyDocument);
      })
    );
    renderPanel("1", [mkStage({ id: "1", name: "min" })]);
    await userEvent.click(await screen.findByRole("button", { name: "Delete stage" }));
    await waitFor(() => expect(deleted).toBe(true));
  });
});
