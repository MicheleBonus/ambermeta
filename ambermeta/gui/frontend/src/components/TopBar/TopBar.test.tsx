import { describe, it, expect, vi } from "vitest";
import type { ComponentProps } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { TopBar } from "./TopBar";
import { ExportModal } from "./ExportModal";

// Accepts overrides rather than hard-coding all seven spies, so a test that only cares
// about one callback (e.g. onDefineReplicas below) can supply just that one and still get
// working no-op spies for the rest -- the previous zero-argument version forced every new
// action to either grow yet another hard-coded vi.fn() here or silently receive one that
// no test could ever assert against.
function renderTopBar(overrides: Partial<ComponentProps<typeof TopBar>> = {}) {
  queryClient.clear();
  return render(
    <QueryClientProvider client={queryClient}>
      <TopBar onOpen={vi.fn()} onSave={vi.fn()} onDiscover={vi.fn()}
        onExport={vi.fn()} onValidate={vi.fn()} onPlan={vi.fn()}
        onDefineReplicas={vi.fn()} {...overrides} />
    </QueryClientProvider>
  );
}

describe("TopBar", () => {
  it("renders all workflow buttons", async () => {
    renderTopBar();
    await waitFor(() => expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discover" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Validate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Redo" })).toBeInTheDocument();
  });

  it("disables Undo/Redo when the document reports can_undo/can_redo false", async () => {
    renderTopBar();
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Redo" })).toBeDisabled();
  });

  it("enables Undo/Redo when the document reports can_undo/can_redo true", async () => {
    server.use(
      http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, can_undo: true, can_redo: true }))
    );
    renderTopBar();
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).not.toBeDisabled());
    expect(screen.getByRole("button", { name: "Redo" })).not.toBeDisabled();
  });

  it("offers a way to declare replicas whatever state the document is in", async () => {
    const onDefineReplicas = vi.fn();
    renderTopBar({ onDefineReplicas });
    await userEvent.click(screen.getByRole("button", { name: "Define replicas…" }));
    expect(onDefineReplicas).toHaveBeenCalled();
  });
});

describe("ExportModal", () => {
  it("offers only yaml/json export formats", () => {
    queryClient.clear();
    render(
      <QueryClientProvider client={queryClient}>
        <ExportModal open onClose={vi.fn()} />
      </QueryClientProvider>
    );
    const select = screen.getByLabelText(/format/i) as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(["yaml", "json"]);
  });
});
