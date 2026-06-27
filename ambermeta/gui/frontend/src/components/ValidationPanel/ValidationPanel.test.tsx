import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider, useSelection } from "@/state/selection";
import { ValidationPanel } from "./ValidationPanel";
import type { StageModel } from "@/types";

function mkStage(p: Partial<StageModel>): StageModel {
  return { id: "", name: "", role: "", prmtop: null, mdin: null, mdout: null, mdcrd: null,
    inpcrd: null, expected_gap_ps: null, gap_tolerance_ps: null, notes: [], ...p };
}

let lastSelected = "";
function Probe() { lastSelected = useSelection().selectedId ?? ""; return null; }

function renderVP(report: unknown, stages: StageModel[]) {
  queryClient.clear();
  server.use(
    http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, stages })),
    http.post("/api/validate", () => HttpResponse.json(report as Record<string, unknown>)),
  );
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <Probe />
        <ValidationPanel open onClose={vi.fn()} />
      </SelectionProvider>
    </QueryClientProvider>
  );
}

describe("ValidationPanel", () => {
  it("treats non-empty protocol_issues as not-fully-valid", async () => {
    renderVP(
      { ok: true, totals: { steps: 0, time_ps: 0, stage_count: 1 },
        protocol_issues: ["Stage starts 5 ps after previous ended."],
        stage_issues: [{ name: "prod", ok: true, degraded: false, errors: [], warnings: [], info: [], missing_files: [] }] },
      [mkStage({ id: "9", name: "prod" })]
    );
    await waitFor(() => expect(screen.getByText(/with 1 protocol note/i)).toBeInTheDocument());
    expect(screen.queryByText(/all checks passed/i)).not.toBeInTheDocument();
  });

  it("jump-to-issue selects the stage by name", async () => {
    renderVP(
      { ok: false, totals: { steps: 0, time_ps: 0, stage_count: 1 }, protocol_issues: [],
        stage_issues: [{ name: "prod", ok: false, degraded: false,
          errors: ["missing mdin: prod.in"], warnings: [], info: [], missing_files: [{ kind: "mdin", path: "prod.in" }] }] },
      [mkStage({ id: "9", name: "prod" })]
    );
    await waitFor(() => expect(screen.getByText(/missing mdin: prod.in/)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /prod/ }));
    expect(lastSelected).toBe("9");
  });
});
