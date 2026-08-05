import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { makeStep } from "@/test/factories";
import App from "@/App";
import type { DiscoverResult, ValidationReport } from "@/types";

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
