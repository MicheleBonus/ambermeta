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

function SelectTwo() {
  const { select } = useSelection();
  useEffect(() => { select("1", { additive: true }); select("2", { additive: true }); }, []); // eslint-disable-line
  return null;
}

function renderBulk() {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json(emptyDocument)));
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <SelectTwo />
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
    await waitFor(() => expect(calls).toEqual([{ files: { mdin: "min.in" } }]));
  });

  it("commits a base-relative path when a file is picked", async () => {
    let sentPath: unknown;
    server.use(
      http.get("/api/files", () => HttpResponse.json([
        { path: "/work/equil/02_nvt.mdin", name: "02_nvt.mdin", file_type: "mdin",
          is_directory: false, size: 1, extension: ".mdin", parent: "/work/equil", children: null },
      ])),
      http.put("/api/stages/1", async ({ request }) => {
        const body = await request.json() as { files?: { mdin?: string } };
        sentPath = body.files?.mdin;
        return HttpResponse.json({ ...emptyDocument, base_directory: "/work" });
      }),
    );
    renderPanel("1", [mkStage({ id: "1", name: "min" })]);
    const pickButtons = await screen.findAllByRole("button", { name: "Pick…" });
    await userEvent.click(pickButtons[1]); // prmtop, mdin, mdout, mdcrd, inpcrd order -> [1] = mdin
    await userEvent.click(await screen.findByText("02_nvt.mdin"));
    await waitFor(() => expect(sentPath).toBe("equil/02_nvt.mdin"));
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

  it("renders assigned file paths folder-qualified with extension", async () => {
    renderPanel("1", [mkStage({ id: "1", name: "min", mdin: "/work/equil/01_min.mdin" })]);
    expect(await screen.findByText("01_min.mdin")).toBeInTheDocument();
    expect(screen.getByText("equil/")).toBeInTheDocument();
  });

  it("bulk role select is controlled and Title-cased, and re-applies", async () => {
    let calls = 0;
    server.use(http.put("/api/stages/bulk", () => { calls++; return HttpResponse.json(emptyDocument); }));
    renderBulk();
    const sel = await screen.findByLabelText(/set role for all/i) as HTMLSelectElement;
    expect(screen.getByRole("option", { name: "Production" })).toBeInTheDocument();
    await userEvent.selectOptions(sel, "production");
    await userEvent.selectOptions(sel, "equilibration");
    await waitFor(() => expect(calls).toBe(2));
  });
});
