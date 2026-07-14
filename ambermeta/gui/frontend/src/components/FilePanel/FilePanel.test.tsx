import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { FilePanel } from "./FilePanel";

function wrap(ui: React.ReactNode) {
  return <QueryClientProvider client={queryClient}><SelectionProvider><DndContext>{ui}</DndContext></SelectionProvider></QueryClientProvider>;
}
it("lists files with a kind subtitle", async () => {
  server.use(http.get("/api/files", () => HttpResponse.json([
    { path: "/work/wt_hmr.prmtop", name: "wt_hmr.prmtop", file_type: "prmtop", is_directory: false, size: 1, extension: ".prmtop", parent: "/work", children: null },
  ])));
  render(wrap(<FilePanel />));
  await waitFor(() => expect(screen.getByText("wt_hmr.prmtop")).toBeInTheDocument());
  expect(screen.getByText(/prmtop/i)).toBeInTheDocument();
});
