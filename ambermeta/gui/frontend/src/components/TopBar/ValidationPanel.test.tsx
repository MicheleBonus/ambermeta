import { afterEach, it, expect, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyValidationReport } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { ValidationPanel } from "./ValidationPanel";
import type { CoherenceFinding, StageIssue, Suggestion, ValidationReport } from "@/types";

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

const finding = (kind: string, evidence: string): Suggestion => ({
  id: `sug_${kind}`, kind, severity: "needs_you", title: kind, evidence, actions: [],
});

it("counts a run's own finding as a note, not a pass", async () => {
  // `validate --manifest --strict` exits 1 on it, so the badge must not be green.
  await show(report({
    suggestions: [finding("unfinished_run",
      "prod_0005: The mdout has no completion marker: the run stopped early or is still running.")],
  }));
  await waitFor(() => expect(screen.getByText("Valid, with 1 note(s)")).toBeInTheDocument());
  expect(screen.queryByText("All checks passed")).not.toBeInTheDocument();
});

it("counts a sequence hole as a note", async () => {
  await show(report({
    suggestions: [finding("missing_run", "present members of 'prod' skip index(es) 3")],
  }));
  await waitFor(() => expect(screen.getByText("Valid, with 1 note(s)")).toBeInTheDocument());
});

it("lists the sequence hole it counts", async () => {
  // The badge said "Valid, with 6 note(s)" and the panel showed five: a hole belongs to no
  // step, so no step card carried it, and nothing else in the panel did either.
  await show(report({
    suggestions: [{ ...finding("missing_run", "present members of 'prod' skip index(es) 3"),
                    title: "prod sequence is missing member(s) 3" }],
  }));
  await waitFor(() => expect(screen.getByText("Valid, with 1 note(s)")).toBeInTheDocument());
  expect(screen.getByText(/prod sequence is missing member\(s\) 3/)).toBeInTheDocument();
});

it("does not list a run's own finding twice", async () => {
  // A step-scoped finding is already on its step's card, from `stage_issues`.
  const message = "The mdout has no completion marker: the run stopped early or is still running.";
  await show(report({
    stage_issues: [{ name: "prod_0005", ok: true, degraded: false, errors: [], warnings: [message],
                     info: [], continuity: [], missing_files: [] }],
    suggestions: [{ ...finding("unfinished_run", `prod_0005: ${message}`), step_id: "st5" }],
  }));
  await waitFor(() => expect(screen.getByText("Valid, with 1 note(s)")).toBeInTheDocument());
  expect(screen.getAllByText(new RegExp(message.slice(0, 30)))).toHaveLength(1);
  // A second listing would be a line of its own under "Findings", headed by the card title.
  expect(screen.queryByRole("heading", { name: "Findings" })).not.toBeInTheDocument();
});

it("does not count what discovery applied", async () => {
  await show(report({
    suggestions: [{ ...finding("role_guess", "Production->production"), severity: "applied" }],
  }));
  await waitFor(() => expect(screen.getByText("All checks passed")).toBeInTheDocument());
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

it("breaks the totals down per lineage when the document declares more than one", async () => {
  await show(report({
    totals: { stage_count: 7, time_ps: 35000, lineage_count: 2 },
    lineages: {
      rep1: { steps: 10000000, time_ps: 20000, step_count: 4 },
      rep2: { steps: 7500000, time_ps: 15000, step_count: 3 },
    },
  }));
  expect(await screen.findByText("rep1")).toBeInTheDocument();
  expect(screen.getByText(/4 run\(s\)/)).toBeInTheDocument();
  expect(screen.getByText(/4 run\(s\) · 20 ns/)).toBeInTheDocument();
});

it("says nothing about lineages when the report carries none", async () => {
  await show(report());
  expect(screen.queryByText("Per lineage")).not.toBeInTheDocument();
});

const stage = (over: Partial<StageIssue>): StageIssue => ({
  name: "prod_0003", ok: true, degraded: false, errors: [], warnings: [], info: [],
  continuity: [], missing_files: [], ...over,
});

it("marks a step with a finding 'check', not a green 'ok'", async () => {
  // The walk-through found a green "ok" badge sitting right above an orange finding. The
  // server sends a run's finding twice, as the step's warning and as a card; it is the
  // card that makes it a finding.
  const message = "This step declares prod_0001.restrt as its input coordinates, "
    + "but its mdout records prod_0002.restrt.";
  await show(report({
    stage_issues: [stage({ warnings: [message] }), stage({ name: "prod_0004" })],
    suggestions: [{ ...finding("input_mismatch", `prod_0003: ${message}`),
                    title: "Declared input differs from the recorded one", step_id: "st3" }],
  }));
  const flagged = await screen.findByRole("button", { name: /prod_0003/ });
  expect(within(flagged).getByText("check")).toBeInTheDocument();
  const clean = screen.getByRole("button", { name: /prod_0004/ });
  expect(within(clean).getByText("ok")).toBeInTheDocument();
});

it("states simulated time in ns", async () => {
  await show(report({
    totals: { stage_count: 7, time_ps: 41100 },
    lineages: { rep1: { steps: 10000000, time_ps: 20000, step_count: 2 } },
  }));
  await waitFor(() => expect(screen.getByText(/41\.1 ns total/)).toBeInTheDocument());
  expect(screen.getByText(/2 run\(s\) · 20 ns/)).toBeInTheDocument();
});

// --- acknowledged findings ------------------------------------------------------------

it("does not count an acknowledged finding, and lists it with its note", async () => {
  const hole = { ...finding("missing_run", "The prod runs here are numbered 1, 3."),
                 title: "prod run 2 is missing", acknowledged: "not deposited" };
  await show(report({
    suggestions: [hole],
    acknowledged: [{ finding: `${hole.title}: ${hole.evidence}`, note: "not deposited" }],
  }));
  await waitFor(() =>
    expect(screen.getByText("All checks passed, 1 acknowledged")).toBeInTheDocument());
  expect(screen.getByText(/not deposited/)).toBeInTheDocument();
});

it("an acknowledged continuity note is not counted through the protocol notes either", async () => {
  // A continuity gap is both a card and a protocol note, with the same text.
  const gap = { ...finding("continuity_gap", "Gap of 20 ps before prod_0003."),
                title: "Continuity note", step_id: "st3", acknowledged: "queue restart" };
  await show(report({
    suggestions: [gap],
    protocol_issues: [gap.evidence],
    acknowledged: [{ finding: `${gap.title}: ${gap.evidence}`, note: "queue restart" }],
  }));
  await waitFor(() =>
    expect(screen.getByText("All checks passed, 1 acknowledged")).toBeInTheDocument());
});

it("names an acknowledgement that no longer matches any finding", async () => {
  await show(report({
    stale_acknowledgements: [{ finding: "prod run 9 is missing: gone", note: "old" }],
  }));
  expect(await screen.findByText("Acknowledged, no longer found")).toBeInTheDocument();
  expect(screen.getByText("prod run 9 is missing: gone")).toBeInTheDocument();
});

it("a step whose only finding is acknowledged is ok again, and says so", async () => {
  const message = "Time step of 4 fs, but the topology has standard hydrogen masses.";
  await show(report({
    stage_issues: [stage({ name: "prod_0001", warnings: [message] })],
    suggestions: [{ ...finding("step_check", `prod_0001: ${message}`), title: "Run check",
                    step_id: "st1", acknowledged: "HMR topology not deposited" }],
    acknowledged: [{ finding: `Run check: prod_0001: ${message}`, note: "HMR topology not deposited" }],
  }));
  const row = await screen.findByRole("button", { name: /prod_0001/ });
  expect(within(row).getByText("ok")).toBeInTheDocument();
  expect(screen.getByText(`${message} (acknowledged)`)).toBeInTheDocument();
});

it("a remark that is not a finding does not mark its step 'check'", async () => {
  // "No atom counts available" is a stage warning but no finding: nothing counts it, so a
  // 'check' badge beside "All checks passed" contradicted the panel's own verdict.
  await show(report({
    stage_issues: [stage({ name: "prod_0001",
                            warnings: ["No atom counts available for validation."] })],
  }));
  const row = await screen.findByRole("button", { name: /prod_0001/ });
  expect(within(row).getByText("ok")).toBeInTheDocument();
  expect(screen.getByText("All checks passed")).toBeInTheDocument();
});
