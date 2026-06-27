import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { _resetToasts } from "@/lib/toast";
import App from "./App";

function renderApp() {
  queryClient.clear();
  return render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);
}

beforeEach(() => { _resetToasts(); });

describe("top-bar workflows", () => {
  it("Discover calls the discover endpoint and updates the document", async () => {
    let discovered = false;
    server.use(
      http.post("/api/document/discover", () => {
        discovered = true;
        return HttpResponse.json({
          ...emptyDocument, dirty: true,
          stages: [{
            id: "1", name: "prod_001", role: "production", prmtop: null, mdin: "prod_001.in",
            mdout: null, mdcrd: null, inpcrd: null, expected_gap_ps: null, gap_tolerance_ps: null, notes: [],
          }],
        });
      })
    );
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Discover" }));
    await userEvent.click(await screen.findByRole("button", { name: "Run discover" }));
    await waitFor(() => expect(discovered).toBe(true));
    await waitFor(() => expect(screen.getByText("prod_001")).toBeInTheDocument());
  });

  it("Save to a bound manifest path posts save", async () => {
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

  it("Re-link restarts posts link-restarts", async () => {
    let linked = false;
    server.use(
      http.post("/api/link-restarts", () => {
        linked = true;
        return HttpResponse.json(emptyDocument);
      })
    );
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Re-link restarts" }));
    await waitFor(() => expect(linked).toBe(true));
  });

  it("failed open shows error toast with detail from 400 response", async () => {
    server.use(
      http.get("/api/files", () => HttpResponse.json([
        { path: "/work/bad.yaml", name: "bad.yaml", file_type: "other",
          is_directory: false, size: 1, extension: ".yaml", parent: "/work", children: null },
      ])),
      http.post("/api/document/open", () =>
        HttpResponse.json({ detail: "File not found or invalid manifest" }, { status: 400 })
      )
    );
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Open" }));
    const dialog = await screen.findByRole("dialog", { name: "Open manifest" });
    await userEvent.click(within(dialog).getByText("bad.yaml"));
    await screen.findByText(/File not found or invalid manifest/, { selector: "[role=status] span" });
  });
});
