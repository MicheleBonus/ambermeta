import type { ReactNode } from "react";
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { FileBrowser } from "./FileBrowser";

// A bare <DndContext> activates dnd-kit's default PointerSensor on the very
// first pixel of pointer movement (no activation constraint), which then
// swallows the next "click" event globally (dnd-kit stops its propagation to
// suppress the ghost click after a drag). That breaks plain-click selection
// on rows that are also drag sources. Production (App.tsx) avoids this with
// a distance-based activation constraint; mirror it here so this test
// exercises real click-to-select behavior instead of an artifact of the
// default sensor config.
function DndTestProvider({ children }: { children: ReactNode }) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  return <DndContext sensors={sensors}>{children}</DndContext>;
}

const tree = [
  { path: "/work/equil", name: "equil", file_type: "folder", is_directory: true,
    size: null, extension: null, parent: "/work", children: [
      { path: "/work/equil/01_min.mdin", name: "01_min.mdin", file_type: "mdin",
        is_directory: false, size: 50, extension: ".mdin", parent: "/work/equil", children: null },
    ] },
  { path: "/work/system.prmtop", name: "system.prmtop", file_type: "prmtop",
    is_directory: false, size: 100, extension: ".prmtop", parent: "/work", children: null },
];

function renderFB() {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json({ ...emptyDocument, base_directory: "/work" })));
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider><DndTestProvider><FileBrowser /></DndTestProvider></SelectionProvider>
    </QueryClientProvider>
  );
}

describe("FileBrowser tree", () => {
  it("renders folders and their files, with a working collapse toggle", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    renderFB();
    await waitFor(() => expect(screen.getByText("equil")).toBeInTheDocument());
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument(); // top levels expanded by default
    await userEvent.click(screen.getByText("equil"));            // collapse
    expect(screen.queryByText("01_min.mdin")).not.toBeInTheDocument();
  });

  it("expands a depth-2 (default-collapsed) folder on a single click", async () => {
    const deepTree = [
      { path: "/work/run1", name: "run1", file_type: "folder", is_directory: true,
        size: null, extension: null, parent: "/work", children: [
          { path: "/work/run1/equil", name: "equil", file_type: "folder", is_directory: true,
            size: null, extension: null, parent: "/work/run1", children: [
              { path: "/work/run1/equil/stage3", name: "stage3", file_type: "folder", is_directory: true,
                size: null, extension: null, parent: "/work/run1/equil", children: [
                  { path: "/work/run1/equil/stage3/x.mdin", name: "x.mdin", file_type: "mdin",
                    is_directory: false, size: 10, extension: ".mdin",
                    parent: "/work/run1/equil/stage3", children: null },
                ] },
            ] },
        ] },
    ];
    server.use(http.get("/api/files", () => HttpResponse.json(deepTree)));
    renderFB();
    // Depth 0 (run1) and depth 1 (equil) are auto-open; depth 2 (stage3) is collapsed by default.
    await waitFor(() => expect(screen.getByText("stage3")).toBeInTheDocument());
    expect(screen.queryByText("x.mdin")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("stage3")); // single click should reveal the child
    expect(screen.getByText("x.mdin")).toBeInTheDocument();
  });

  it("search prunes to matches and reveals their folder", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    renderFB();
    await waitFor(() => expect(screen.getByText("system.prmtop")).toBeInTheDocument());
    await userEvent.type(screen.getByPlaceholderText(/search/i), "01_min");
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
    expect(screen.getByText("equil")).toBeInTheDocument();          // ancestor kept
    expect(screen.queryByText("system.prmtop")).not.toBeInTheDocument();
  });

  it("shows an empty state when the folder has no recognized files", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json([])));
    renderFB();
    expect(await screen.findByText(/no files/i)).toBeInTheDocument();
  });

  it("shows metadata on selecting a file", async () => {
    server.use(
      http.get("/api/files", () => HttpResponse.json(tree)),
      http.get("/api/files/metadata", () => HttpResponse.json({
        file_path: "/work/system.prmtop", file_type: "prmtop",
        metadata: { details: { natom: 1234 }, warnings: [], kind: "prmtop" }, warnings: [],
      })),
    );
    renderFB();
    await userEvent.click(await screen.findByText("system.prmtop"));
    await waitFor(() => expect(screen.getByTestId("file-metadata")).toHaveTextContent("1234"));
  });
});
