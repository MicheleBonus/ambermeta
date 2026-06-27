import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import App from "./App";

function renderApp() {
  queryClient.clear();
  return render(
    <QueryClientProvider client={queryClient}><App /></QueryClientProvider>
  );
}

describe("App shell", () => {
  it("renders three panes and the top bar actions", async () => {
    renderApp();
    await waitFor(() => expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Validate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discover" })).toBeInTheDocument();
    expect(screen.getByTestId("pane-files")).toBeInTheDocument();
    expect(screen.getByTestId("pane-stages")).toBeInTheDocument();
    expect(screen.getByTestId("pane-properties")).toBeInTheDocument();
  });

  it("disables undo/redo per the document flags and shows dirty", async () => {
    server.use(
      http.get("/api/document", () =>
        HttpResponse.json({ ...emptyDocument, dirty: true, can_undo: true, can_redo: false })
      )
    );
    renderApp();
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "Redo" })).toBeDisabled();
    expect(screen.getByTestId("dirty-indicator")).toBeInTheDocument();
  });
});
