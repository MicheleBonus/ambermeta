import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { makeStep } from "@/test/factories";
import App from "@/App";
import type { DiscoverResult, LineageProposalResponse, ValidationReport } from "@/types";

function renderApp() {
  queryClient.clear();
  return render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);
}

describe("top-bar workflows", () => {
  it("Discover posts /api/document/discover, replaces the document, and feeds the tray", async () => {
    let discovered = false;
    const result: DiscoverResult = {
      document: {
        ...emptyDocument,
        dirty: true,
        simulation: {
          version: 2,
          topologies: [],
          starting_structure: null,
          phases: [
            {
              id: "p1",
              name: "Production",
              role: "production",
              steps: [makeStep({ id: "s1", name: "prod_001", mdin: "prod_001.in" })],
            },
          ],
        },
      },
      suggestions: [
        {
          id: "sug_1",
          kind: "role_guess",
          severity: "applied",
          title: "Phase roles inferred from file content/names",
          evidence: "Production->production",
          actions: ["Undo"],
        },
      ],
      warnings: [],
      // No layout inference to report here -- the fixture's single step has no directory
      // segment to distinguish members by, matching build_lineage_proposal's own "returns
      // None" case.
      proposal: null,
    };
    server.use(
      http.post("/api/document/discover", () => {
        discovered = true;
        return HttpResponse.json(result);
      }),
      // The App re-validates on every document-identity change (single shared
      // suggestions source -- see suggestionsContext). A real backend would
      // surface the same just-applied role_guess suggestion on that follow-up
      // validate call, so the mock mirrors that instead of going quiet.
      http.post("/api/validate", () =>
        HttpResponse.json({ ok: true, totals: {}, protocol_issues: [], stage_issues: [], suggestions: result.suggestions })
      ),
    );
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Discover" }));
    await userEvent.click(await screen.findByRole("button", { name: "Run discover" }));
    await waitFor(() => expect(discovered).toBe(true));
    await waitFor(() => expect(screen.getByText("prod_001")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Production->production")).toBeInTheDocument());
  });

  it("Validate feeds the report's suggestions into the tray", async () => {
    const report: ValidationReport = {
      ok: true,
      totals: { stage_count: 0 },
      lineages: null,
      coherence: [],
      protocol_issues: [],
      stage_issues: [],
      suggestions: [
        {
          id: "sug_2",
          kind: "role_guess",
          severity: "applied",
          title: "Phase roles inferred from file content/names",
          evidence: "Heating->heating",
          actions: ["Undo"],
        },
      ],
    };
    server.use(http.post("/api/validate", () => HttpResponse.json(report)));
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Validate" }));
    await waitFor(() => expect(screen.getByText("Heating->heating")).toBeInTheDocument());
  });

  it("Save posts directly when a manifest_path is already bound", async () => {
    let saved = false;
    server.use(
      http.get("/api/document", () =>
        HttpResponse.json({ ...emptyDocument, manifest_path: "/work/p.yaml", dirty: true })
      ),
      http.post("/api/document/save", () => {
        saved = true;
        return HttpResponse.json({ document: { ...emptyDocument, manifest_path: "/work/p.yaml" }, warnings: [] });
      })
    );
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    await waitFor(() => expect(saved).toBe(true));
  });
});

describe("lineage proposal wiring (P2.2/P2.3)", () => {
  it("shows the proposal after Discover instead of applying it", async () => {
    const result: DiscoverResult = {
      document: { ...emptyDocument, dirty: true },
      suggestions: [],
      warnings: [],
      proposal: {
        segment_index: 1,
        segments: [["equil", "prod"], ["01", "02"]],
        members: [
          { tag: "01", step_ids: ["a1"], sources: [{ directory: "equil/01", run_count: 18 }] },
          { tag: "02", step_ids: ["b1"], sources: [{ directory: "equil/02", run_count: 18 }] },
        ],
        handoffs: [],
      },
    };
    server.use(http.post("/api/document/discover", () => HttpResponse.json(result)));
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Discover" }));
    await userEvent.click(await screen.findByRole("button", { name: "Run discover" }));
    expect(await screen.findByText(/repeated members/)).toBeInTheDocument();
  });

  it("opens a working manual picker from Define replicas… on a tree the smart inference declines", async () => {
    // Mirrors build_lineage_proposal's real contract (routes.py, core_bridge.py): a bare
    // call (segment_index omitted) runs the cohort/nesting inference and can refuse --
    // that refusal is the whole reason this button exists (a nested sweep, a flat chain
    // with no directory segment). An explicit segment_index never refuses that way; it
    // tags every run by its own value at that index. This handler distinguishes the two
    // exactly as the real route does, so this test actually exercises App's fallback
    // (mutate(undefined) then mutate(0)) rather than a stub that cannot tell them apart.
    server.use(
      http.post("/api/steps/infer-lineages", async ({ request }) => {
        const body = (await request.json()) as { segment_index?: number | null };
        if (body.segment_index == null) {
          const declined: LineageProposalResponse = {
            proposal: null,
            warnings: ["No lineages inferred: the directory layout could not be resolved into "
              + "one unambiguous set of members. Use Define replicas… to pick the segment "
              + "yourself."],
          };
          return HttpResponse.json(declined);
        }
        const seeded: LineageProposalResponse = {
          proposal: {
            segment_index: body.segment_index,
            segments: [["min", "heat"]],
            members: [
              { tag: "min", step_ids: ["s1"], sources: [{ directory: "min", run_count: 1 }] },
              { tag: "heat", step_ids: ["s2"], sources: [{ directory: "heat", run_count: 1 }] },
            ],
            handoffs: [],
          },
          warnings: [],
        };
        return HttpResponse.json(seeded);
      }),
    );
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Define replicas…" }));
    expect(await screen.findByText(/which part of the path names the replica/i)).toBeInTheDocument();
    expect(screen.getByLabelText("tag for min")).toBeInTheDocument();
  });
});
