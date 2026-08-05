import { afterEach, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyValidationReport } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { ValidationPanel } from "./ValidationPanel";
import type { CoherenceFinding, ValidationReport } from "@/types";

/**
 * The panel had no test file at all, which is how it came to render a green
 * "All checks passed" for a document the CLI exits 1 on: `errorCount` read only
 * `stage_issues`, and a category error is not attached to any one stage.
 */

function report(over: Partial<ValidationReport> = {}): ValidationReport {
  return { ...emptyValidationReport, ...over };
}

async function show(body: ValidationReport) {
  queryClient.clear();
  server.use(http.post("/api/validate", () => HttpResponse.json(body)));
  render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <ValidationPanel open onClose={vi.fn()} />
      </SelectionProvider>
    </QueryClientProvider>,
  );
  await screen.findByRole("dialog");
}

const CATEGORY_ERROR: CoherenceFinding = {
  severity: "error",
  kind: "atom_count",
  message: "Members do not hold the same number of atoms (rep1: 64528; rep2: 12000).",
};

afterEach(() => {
  queryClient.clear();
});

it("shows a clean document as passing", async () => {
  await show(report());
  await waitFor(() => expect(screen.getByText("All checks passed")).toBeInTheDocument());
});

it("reports a lineage category error as an error, not a note", async () => {
  await show(report({ ok: false, coherence: [CATEGORY_ERROR] }));
  await waitFor(() => expect(screen.getByText("1 lineage error(s)")).toBeInTheDocument());
  expect(screen.queryByText("All checks passed")).not.toBeInTheDocument();
  const line = screen.getByText(CATEGORY_ERROR.message);
  expect(line.className).toMatch(/text-error/);
});

it("keeps a parameter difference a warning", async () => {
  // Decision 5: only a category error is fatal. A temperature that differs between
  // members is a finding the user may well have intended.
  await show(report({
    coherence: [{ severity: "warning", kind: "parameter",
                  message: "Members differ in temp0 (rep1: 300.0; rep2: 310.0)." }],
  }));
  await waitFor(() => expect(screen.getByText("Valid, with 1 note(s)")).toBeInTheDocument());
  expect(screen.getByText(/Members differ in temp0/).className).toMatch(/text-warning/);
});

it("states a fan-out as a plain fact", async () => {
  await show(report({
    coherence: [{ severity: "info", kind: "fan_out",
                  message: "3 steps read the restart written by common/equil and carry 3 distinct resolved seeds." }],
  }));
  // Info is not a note to be counted: nothing is wrong, so the badge stays green.
  await waitFor(() => expect(screen.getByText("All checks passed")).toBeInTheDocument());
  expect(screen.getByText(/3 distinct resolved seeds/).className).toMatch(/text-ink-muted/);
});

it("still reports a stage error when the lineages agree", async () => {
  await show(report({
    ok: false,
    stage_issues: [{
      name: "prod_0001", ok: false, degraded: false,
      errors: ["missing prmtop: wt.prmtop"], warnings: [], info: [],
      continuity: [], missing_files: [],
    }],
  }));
  await waitFor(() =>
    expect(screen.getByText("1 stage(s) with errors")).toBeInTheDocument());
});
