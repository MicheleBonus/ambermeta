import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { FileDropZone } from "./FileDropZone";

function renderZone(current: string | null) {
  queryClient.clear();
  server.use(http.get("/api/document", () =>
    HttpResponse.json({ ...emptyDocument, base_directory: "/work" })));
  return render(
    <QueryClientProvider client={queryClient}>
      <DndContext><FileDropZone stageId="1" kind="mdin" current={current} /></DndContext>
    </QueryClientProvider>
  );
}

describe("FileDropZone", () => {
  it("shows the kind label and a folder-qualified, extension-bearing filename", async () => {
    renderZone("/work/equil/01_min.mdin");
    // "equil/" only appears once the base_directory fetch resolves and the
    // path is relativized, so wait on it first to avoid a race against the
    // initial (pre-fetch) render, where the raw, un-relativized path already
    // happens to contain the same filename text.
    expect(await screen.findByText("equil/")).toBeInTheDocument();
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
    expect(screen.getByText("mdin")).toBeInTheDocument();
  });
  it("shows a dash when empty", async () => {
    renderZone(null);
    expect(await screen.findByText("—")).toBeInTheDocument();
  });
});
