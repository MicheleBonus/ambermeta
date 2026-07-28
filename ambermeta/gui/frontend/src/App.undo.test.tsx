import { afterEach, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import App from "@/App";
import { makeStep } from "@/test/factories";
import type { DocumentResponse } from "@/types";

/** A document that has something to undo and something to redo. */
const REVERSIBLE: DocumentResponse = { ...emptyDocument, can_undo: true, can_redo: true };

function countCalls(path: string): { calls: number } {
  const seen = { calls: 0 };
  server.use(http.post(path, () => {
    seen.calls += 1;
    return HttpResponse.json(REVERSIBLE);
  }));
  return seen;
}

async function renderApp(doc: DocumentResponse = REVERSIBLE) {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json(doc)));
  render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);
  await waitFor(() => expect(screen.getByTestId("pane-canvas")).toBeInTheDocument());
}

afterEach(() => {
  vi.restoreAllMocks();
});

it("undoes with Ctrl+Z — the top-bar icon was the only way in", async () => {
  const undo = countCalls("/api/undo");
  await renderApp();

  await userEvent.keyboard("{Control>}z{/Control}");

  await waitFor(() => expect(undo.calls).toBe(1));
});

it("redoes with both Ctrl+Shift+Z and Ctrl+Y", async () => {
  const redo = countCalls("/api/redo");
  await renderApp();

  await userEvent.keyboard("{Control>}{Shift>}z{/Shift}{/Control}");
  await waitFor(() => expect(redo.calls).toBe(1));

  await userEvent.keyboard("{Control>}y{/Control}");
  await waitFor(() => expect(redo.calls).toBe(2));
});

it("leaves Ctrl+Z alone while the user is typing into a field", async () => {
  const undo = countCalls("/api/undo");
  await renderApp();

  const search = screen.getByPlaceholderText("Search files…");
  search.focus();
  await userEvent.keyboard("{Control>}z{/Control}");

  await new Promise((r) => setTimeout(r, 20));
  expect(undo.calls).toBe(0);
});

it("does not fire an undo the document says is unavailable", async () => {
  const undo = countCalls("/api/undo");
  await renderApp({ ...emptyDocument, can_undo: false });

  await userEvent.keyboard("{Control>}z{/Control}");

  await new Promise((r) => setTimeout(r, 20));
  expect(undo.calls).toBe(0);
});

it("labels the top-bar buttons with their shortcut", async () => {
  await renderApp();
  expect(screen.getByRole("button", { name: "Undo" })).toHaveAttribute("title", "Undo (Ctrl+Z)");
  expect(screen.getByRole("button", { name: "Redo" }))
    .toHaveAttribute("title", "Redo (Ctrl+Shift+Z)");
});

it("suspends Ctrl+Z while a file picker raised by a step card is open", async () => {
  // The picker is owned by StepNode, not by App, so enumerating App's own modal flags
  // missed it: the document would rewind behind the open dialog and the file then picked
  // would be written into a document that no longer has the step it was opened for.
  const undo = countCalls("/api/undo");
  server.use(http.get("/api/files", () => HttpResponse.json([])));
  await renderApp({
    ...REVERSIBLE,
    simulation: {
      version: 2, topologies: [], starting_structure: null,
      phases: [{
        id: "p0", name: "Production", role: "production",
        steps: [makeStep({ id: "s0", name: "prod_0001" })],
      }],
    },
  });

  await userEvent.click(await screen.findByRole("button", { name: "choose a mdin file" }));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();

  await userEvent.keyboard("{Control>}z{/Control}");
  await new Promise((r) => setTimeout(r, 20));
  expect(undo.calls).toBe(0);
});
