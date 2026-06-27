import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { StageList } from "./StageList";
import type { StageModel } from "@/types";

function mkStage(p: Partial<StageModel>): StageModel {
  return { id: "", name: "", role: "", prmtop: null, mdin: null, mdout: null, mdcrd: null,
    inpcrd: null, expected_gap_ps: null, gap_tolerance_ps: null, notes: [], ...p };
}

function renderList() {
  queryClient.clear();
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider><DndContext><StageList /></DndContext></SelectionProvider>
    </QueryClientProvider>
  );
}

describe("StageList", () => {
  it("renders stages and shows a configured gap inline", async () => {
    server.use(
      http.get("/api/document", () =>
        HttpResponse.json({ ...emptyDocument, stages: [
          mkStage({ id: "1", name: "min", role: "minimization" }),
          mkStage({ id: "2", name: "prod", role: "production", expected_gap_ps: 5 }),
        ] })),
      http.get("/api/sequences", () => HttpResponse.json({})),
    );
    renderList();
    await waitFor(() => expect(screen.getByText("min")).toBeInTheDocument());
    expect(screen.getByText("prod")).toBeInTheDocument();
    expect(screen.getByText(/\+5 ps gap/)).toBeInTheDocument();
  });

  it("collapses a numbered sequence into one summary row", async () => {
    const stages = [1, 2, 3].map((i) =>
      mkStage({ id: String(i), name: `prod_00${i}`, role: "production" }));
    server.use(
      http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, stages })),
      http.get("/api/sequences", () => HttpResponse.json({ prod_: ["1", "2", "3"] })),
    );
    renderList();
    await waitFor(() => expect(screen.getByText(/prod_ · 3 runs/)).toBeInTheDocument());
    // collapsed by default: individual members hidden until expanded
    expect(screen.queryByText("prod_001")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText(/prod_ · 3 runs/));
    await waitFor(() => expect(screen.getByText("prod_001")).toBeInTheDocument());
  });
});
