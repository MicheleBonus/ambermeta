import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("clicking a chip opens a picker and assigns", async () => {
    let sent: unknown;
    queryClient.clear();
    server.use(
      http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, base_directory: "/work" })),
      http.get("/api/files", () => HttpResponse.json([
        { path: "/work/equil/03_npt.mdin", name: "03_npt.mdin", file_type: "mdin",
          is_directory: false, size: 1, extension: ".mdin", parent: "/work/equil", children: null },
      ])),
      http.put("/api/stages/:id", async ({ request }) => {
        sent = ((await request.json()) as { files?: { mdin?: string } }).files?.mdin;
        return HttpResponse.json({ ...emptyDocument });
      }),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <DndContext><FileDropZone stageId="1" kind="mdin" current={null} /></DndContext>
      </QueryClientProvider>
    );
    await userEvent.click(await screen.findByRole("button", { name: /assign mdin/i }));
    await userEvent.click(await screen.findByText("03_npt.mdin"));
    await waitFor(() => expect(sent).toBe("equil/03_npt.mdin"));
  });

  it("clicking × clears the assigned file", async () => {
    let body: { files?: { mdin?: string } } | undefined;
    server.use(
      http.put("/api/stages/:id", async ({ request }) => {
        body = (await request.json()) as { files?: { mdin?: string } };
        return HttpResponse.json({ ...emptyDocument });
      }),
    );
    renderZone("/work/equil/01_min.mdin");
    await userEvent.click(await screen.findByRole("button", { name: /clear mdin/i }));
    await waitFor(() => expect(body?.files?.mdin).toBe(""));
  });
});
