import { afterEach, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { _resetToasts } from "@/lib/toast";
import { PlanModal } from "./PlanModal";
import type { DocumentResponse } from "@/types";

interface Captured { body: any; calls: number }

function capturePlan(written: { artifact: string; path: string }[] = [],
                     warnings: string[] = [],
                     failed: { artifact: string; path: string; error: string }[] = []): Captured {
  const seen: Captured = { body: undefined, calls: 0 };
  server.use(http.post("/api/plan", async ({ request }) => {
    seen.calls += 1;
    seen.body = await request.json();
    return HttpResponse.json({
      written, failed, warnings, stage_count: written.length ? 5 : 0,
      totals: { steps: 25000000, time_ps: 100000 }, document: emptyDocument,
    });
  }));
  return seen;
}

async function renderPlan(doc: DocumentResponse = emptyDocument) {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json(doc)));
  render(
    <QueryClientProvider client={queryClient}>
      <PlanModal open onClose={vi.fn()} />
    </QueryClientProvider>,
  );
  await screen.findByRole("dialog");
}

afterEach(() => {
  vi.restoreAllMocks();
  _resetToasts();
});

it("writes the manifest and both summaries in one action, which is the whole point", async () => {
  const plan = capturePlan([
    { artifact: "manifest", path: "/work/manifest.yaml" },
    { artifact: "summary", path: "/work/summary.json" },
    { artifact: "methods_summary", path: "/work/methods_summary.json" },
  ]);
  await renderPlan();

  await userEvent.click(screen.getByRole("button", { name: "Write" }));

  await waitFor(() => expect(plan.calls).toBe(1));
  expect(plan.body).toEqual({
    // The GUI used to default to `ambermeta.yaml` while `ambermeta init` wrote
    // `manifest.yaml`, so the two halves of the tool disagreed on the file's name.
    save_manifest_path: "manifest.yaml",
    summary_path: "summary.json",
    methods_summary_path: "methods_summary.json",
    stats_csv_path: null,          // unticked by default: it needs mdout files
    summary_format: "json",
  });
});

it("reports every file it wrote, so the user is not left guessing where they went", async () => {
  capturePlan([
    { artifact: "manifest", path: "/work/manifest.yaml" },
    { artifact: "summary", path: "/work/summary.json" },
  ]);
  await renderPlan();

  await userEvent.click(screen.getByRole("button", { name: "Write" }));

  expect(await screen.findByText("/work/manifest.yaml")).toBeInTheDocument();
  expect(screen.getByText("/work/summary.json")).toBeInTheDocument();
  expect(screen.getByText(/5 step\(s\)/)).toBeInTheDocument();
});

it("sends null for an output the user unticked", async () => {
  const plan = capturePlan();
  await renderPlan();

  await userEvent.click(screen.getByRole("checkbox", { name: "Methods summary" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Manifest" }));
  await userEvent.click(screen.getByRole("button", { name: "Write" }));

  await waitFor(() => expect(plan.calls).toBe(1));
  expect(plan.body.methods_summary_path).toBeNull();
  expect(plan.body.save_manifest_path).toBeNull();
  expect(plan.body.summary_path).toBe("summary.json");
});

it("will not run with nothing selected", async () => {
  const plan = capturePlan();
  await renderPlan();

  for (const name of ["Manifest", "Protocol summary", "Methods summary"]) {
    await userEvent.click(screen.getByRole("checkbox", { name }));
  }

  expect(screen.getByRole("button", { name: "Write" })).toBeDisabled();
  expect(plan.calls).toBe(0);
});

it("writes back to the manifest already open rather than inventing a second file", async () => {
  const plan = capturePlan();
  await renderPlan({ ...emptyDocument, manifest_path: "/work/runs/mine.yaml" });

  await userEvent.click(screen.getByRole("button", { name: "Write" }));

  await waitFor(() => expect(plan.calls).toBe(1));
  expect(plan.body.save_manifest_path).toBe("/work/runs/mine.yaml");
});

it("carries the summary format through, and says the methods summary is fixed", async () => {
  const plan = capturePlan();
  await renderPlan();

  await userEvent.selectOptions(screen.getByLabelText("Summary format"), "yaml");
  expect(screen.getByText(/methods summary is always JSON/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Write" }));

  await waitFor(() => expect(plan.calls).toBe(1));
  expect(plan.body.summary_format).toBe("yaml");
});

it("surfaces a warning from the server instead of reporting a clean run", async () => {
  capturePlan([{ artifact: "stats_csv", path: "/work/stats.csv" }],
              ["No step has an mdout, so the statistics CSV has headers only."]);
  await renderPlan();

  await userEvent.click(screen.getByRole("button", { name: "Write" }));

  expect(await screen.findByText(/headers only/)).toBeInTheDocument();
});

it("keeps the totals-delta warning's line breaks, instead of collapsing it into a run-on sentence", async () => {
  // `totals_delta` (protocol.py) builds exactly this shape: embedded "\n"s separating a
  // steps/time_ps/note/queued line each, with space-padded column alignment. Before this
  // fix the warning `<p>` used the browser default `white-space: normal`, which collapses
  // every "\n" into a space -- a four-line block a user reads perfectly well in the CLI
  // arrived here as one run-on sentence.
  const delta = "totals changed since the last summary.json (/work/summary.json):\n"
    + "  steps     20000000.000 -> 17500000.000\n"
    + "  time_ps   40000.000 -> 35000.000\n"
    + "  note      totals count what each run's mdout shows it RAN, not what its mdin declared";
  capturePlan([{ artifact: "summary", path: "/work/summary.json" }], [delta]);
  await renderPlan();

  await userEvent.click(screen.getByRole("button", { name: "Write" }));

  // jsdom does not lay out CSS, so nothing here can assert the actual visual line
  // wrapping -- asserting the CLASS is what proves this test would fail without the fix.
  const rendered = await screen.findByText((_, el) => el?.textContent === delta);
  expect(rendered).toHaveClass("whitespace-pre-line");
  expect(rendered.tagName).toBe("P");
});

it("still renders an ordinary single-line warning exactly as before", async () => {
  // `whitespace-pre-line` only changes how an EXISTING "\n" is honoured; a warning with
  // none of them -- every warning this component rendered before totals_delta existed --
  // must read and wrap exactly as `white-space: normal` already had it.
  const message = "No step has an mdout, so the statistics CSV has headers only.";
  capturePlan([{ artifact: "stats_csv", path: "/work/stats.csv" }], [message]);
  await renderPlan();

  await userEvent.click(screen.getByRole("button", { name: "Write" }));

  const rendered = await screen.findByText(message);
  expect(rendered).toHaveClass("whitespace-pre-line");
  expect(rendered.textContent).toBe(message);
});

it("will not run while a ticked output has no filename, instead of dropping it silently", async () => {
  // The request used to null out a ticked-but-blank path: the user asked for the file,
  // got nothing, and was shown a clean result listing the other three.
  const plan = capturePlan();
  await renderPlan();

  await userEvent.click(screen.getByRole("checkbox", { name: "Statistics CSV" }));
  await userEvent.clear(screen.getByLabelText("Statistics CSV path"));

  expect(screen.getByRole("button", { name: "Write" })).toBeDisabled();
  expect(screen.getByText("Needs a filename.")).toBeInTheDocument();
  expect(plan.calls).toBe(0);
});

it("blocks two outputs aimed at one file before the round trip", async () => {
  // The server rejects it too, but only after the user has clicked.
  const plan = capturePlan();
  await renderPlan();

  await userEvent.clear(screen.getByLabelText("Protocol summary path"));
  await userEvent.type(screen.getByLabelText("Protocol summary path"), "manifest.yaml");

  expect(screen.getByRole("button", { name: "Write" })).toBeDisabled();
  expect(screen.getAllByText(/aimed at this file/)).toHaveLength(2);
  expect(plan.calls).toBe(0);
});

it("warns before replacing a file that is already there", async () => {
  // Every box is ticked by default, so the first click in a directory that already holds
  // one of these names would otherwise replace it without a word.
  server.use(http.get("/api/files", () => HttpResponse.json([
    { path: "/work/summary.json", name: "summary.json", file_type: "other",
      is_directory: false, size: 1, extension: ".json", parent: "/work", children: null },
  ])));
  await renderPlan({ ...emptyDocument, base_directory: "/work" });

  expect(await screen.findByText(/exists and will be replaced/)).toBeInTheDocument();
  // Only the row whose file is actually there says so.
  expect(screen.getAllByText(/exists and will be replaced/)).toHaveLength(1);
  expect(screen.getByRole("button", { name: "Write" })).toBeEnabled();
});

it("reports what landed even when one artifact could not be written", async () => {
  capturePlan(
    [{ artifact: "manifest", path: "/work/m.yaml" }, { artifact: "summary", path: "/work/s.json" }],
    [],
    [{ artifact: "methods_summary", path: "/work/blocked", error: "Permission denied" }],
  );
  await renderPlan();

  await userEvent.click(screen.getByRole("button", { name: "Write" }));

  expect(await screen.findByText("/work/m.yaml")).toBeInTheDocument();
  expect(screen.getByText("/work/s.json")).toBeInTheDocument();
  expect(screen.getByText(/\/work\/blocked — Permission denied/)).toBeInTheDocument();
});
