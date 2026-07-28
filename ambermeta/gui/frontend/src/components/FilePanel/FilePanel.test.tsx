import type { ReactNode } from "react";
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext, PointerSensor, useSensor, useSensors, type DragStartEvent } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { FilePanel } from "./FilePanel";
import type { FileInfo } from "@/types";

// A bare <DndContext> arms dnd-kit's default PointerSensor on the very first
// pixel of pointer movement, which then swallows the following "click" to
// suppress the ghost click after a drag. Production (App.tsx) avoids that with
// a distance activation constraint; mirror it so these tests exercise real
// click behaviour rather than an artifact of the default sensor config.
function DndTestProvider({
  children,
  onDragStart,
}: {
  children: ReactNode;
  onDragStart?: (e: DragStartEvent) => void;
}) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  return <DndContext sensors={sensors} onDragStart={onDragStart}>{children}</DndContext>;
}

function dir(path: string, name: string, parent: string, children: FileInfo[]): FileInfo {
  return { path, name, file_type: "folder", is_directory: true, size: null, extension: null, parent, children };
}

const tree: FileInfo[] = [
  dir("/work/equil", "equil", "/work", [
    { path: "/work/equil/01_min.mdin", name: "01_min.mdin", file_type: "mdin", is_directory: false,
      size: 50, extension: ".mdin", parent: "/work/equil", children: null },
  ]),
  { path: "/work/system.prmtop", name: "system.prmtop", file_type: "prmtop", is_directory: false,
    size: 100, extension: ".prmtop", parent: "/work", children: null },
];

const deepTree: FileInfo[] = [
  dir("/work/run1", "run1", "/work", [
    dir("/work/run1/equil", "equil", "/work/run1", [
      dir("/work/run1/equil/stage3", "stage3", "/work/run1/equil", [
        { path: "/work/run1/equil/stage3/x.mdin", name: "x.mdin", file_type: "mdin", is_directory: false,
          size: 10, extension: ".mdin", parent: "/work/run1/equil/stage3", children: null },
      ]),
    ]),
  ]),
];

/** Waits for the file listing, so assertions never catch the tree mid-flight. */
async function queriesSettled() {
  await waitFor(() => {
    expect(queryClient.getQueriesData({ queryKey: ["files"] })[0]?.[1]).toBeDefined();
  });
}

function renderPanel(onDragStart?: (e: DragStartEvent) => void) {
  queryClient.clear();
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <DndTestProvider onDragStart={onDragStart}>
          <FilePanel />
        </DndTestProvider>
      </SelectionProvider>
    </QueryClientProvider>,
  );
}

/**
 * jsdom has no PointerEvent, and testing-library's `fireEvent.pointerDown` then falls back to a
 * bare Event that carries neither `isPrimary` nor `button` — the two fields dnd-kit's PointerSensor
 * checks before it activates. A MouseEvent named "pointerdown" carries both.
 */
function pointerEvent(type: string, init: MouseEventInit = {}) {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, ...init });
  Object.assign(event, { isPrimary: true, pointerId: 1, pointerType: "mouse" });
  return event;
}

/** A press-and-move past the 5px activation distance, which is what arms the PointerSensor. */
function dragFrom(el: Element) {
  fireEvent(el, pointerEvent("pointerdown", { clientX: 0, clientY: 0 }));
  fireEvent(document, pointerEvent("pointermove", { clientX: 40, clientY: 0 }));
}

describe("FilePanel folder tree", () => {
  it("renders directories as folder rows instead of hoisting their contents", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    renderPanel();
    const folder = await screen.findByRole("button", { name: "equil" });
    expect(folder).toHaveAttribute("aria-expanded", "true");
    // the folder's child renders nested under it, not as a sibling of the tree root
    expect(screen.getByTestId("row:/work/equil/01_min.mdin")).toBeInTheDocument();
    expect(screen.getByTestId("row:/work/equil")).toBeInTheDocument();
  });

  it("hides a folder's children once it is collapsed, and shows them again on re-click", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    renderPanel();
    const folder = await screen.findByRole("button", { name: "equil" });
    await queriesSettled();
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();

    await userEvent.click(folder);
    expect(screen.queryByText("01_min.mdin")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "equil" })).toHaveAttribute("aria-expanded", "false");
    // a sibling file at the root is untouched by collapsing the folder
    expect(screen.getByText("system.prmtop")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "equil" }));
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
  });

  it("expands a depth-2 folder — collapsed by default — with a single click", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(deepTree)));
    renderPanel();
    // depth 0 (run1) and depth 1 (equil) are open by default; depth 2 (stage3) is not
    const stage3 = await screen.findByRole("button", { name: "stage3" });
    await queriesSettled();
    expect(stage3).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("x.mdin")).not.toBeInTheDocument();

    await userEvent.click(stage3);
    expect(screen.getByText("x.mdin")).toBeInTheDocument();
  });

  it("indents rows by depth", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    renderPanel();
    await screen.findByRole("button", { name: "equil" });
    expect(screen.getByTestId("row:/work/equil")).toHaveStyle({ paddingLeft: "8px" });
    expect(screen.getByTestId("row:/work/equil/01_min.mdin")).toHaveStyle({ paddingLeft: "20px" });
  });

  it("search reveals a match inside a folder the user has collapsed", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    renderPanel();
    await screen.findByRole("button", { name: "equil" });
    await queriesSettled();
    await userEvent.click(screen.getByRole("button", { name: "equil" }));
    expect(screen.queryByText("01_min.mdin")).not.toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText(/search/i), "01_min");
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "equil" })).toBeInTheDocument(); // ancestor kept
    expect(screen.queryByText("system.prmtop")).not.toBeInTheDocument(); // non-matches pruned
  });

  it("re-queries with include_all when 'Show all files' is ticked", async () => {
    const searches: string[] = [];
    server.use(http.get("/api/files", ({ request }) => {
      searches.push(new URL(request.url).search);
      return HttpResponse.json(tree);
    }));
    renderPanel();
    await screen.findByRole("button", { name: "equil" });
    await queriesSettled();
    expect(searches[0]).toContain("include_all=false");
    expect(searches[0]).toContain("recursive=true");

    await userEvent.click(screen.getByLabelText(/show all files/i));
    await waitFor(() => expect(searches.some((s) => s.includes("include_all=true"))).toBe(true));
  });

  it("labels a file with its extension and keeps the kind subtitle and hint", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json([
      { path: "/work/wt_hmr.prmtop", name: "wt_hmr.prmtop", file_type: "prmtop", is_directory: false,
        size: 1, extension: ".prmtop", parent: "/work", children: null },
    ])));
    renderPanel();
    expect(await screen.findByText("wt_hmr.prmtop")).toBeInTheDocument();
    expect(screen.getByText("topology")).toBeInTheDocument();
    expect(screen.getByText(/hmr topology/i)).toBeInTheDocument();
  });

  it("shows the bare basename in the tree, with the full path as its tooltip", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    renderPanel();
    await screen.findByText("01_min.mdin");
    await queriesSettled();
    // The tree already renders "equil" as the parent row, so repeating it on the child would
    // duplicate the qualifier and eat width in a 280px pane.
    expect(screen.queryByText("equil/")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "01_min.mdin" }))
      .toHaveAttribute("title", "/work/equil/01_min.mdin");
  });

  it("searching for a folder keeps that folder and everything under it", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    renderPanel();
    await screen.findByRole("button", { name: "equil" });
    await queriesSettled();

    await userEvent.type(screen.getByPlaceholderText(/search/i), "equil");

    expect(screen.getByTestId("row:/work/equil")).toBeInTheDocument();
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
    expect(screen.queryByText(/no files found/i)).not.toBeInTheDocument();
    // A non-matching sibling is still pruned.
    expect(screen.queryByText("system.prmtop")).not.toBeInTheDocument();
  });

  it("disables the chevron while a search pins folders open, and keeps the pre-search state", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    renderPanel();
    await screen.findByRole("button", { name: "equil" });
    await queriesSettled();

    const search = screen.getByPlaceholderText(/search/i);
    await userEvent.type(search, "min");
    const folder = screen.getByRole("button", { name: "equil" });
    expect(folder).toHaveAttribute("aria-expanded", "true");
    expect(folder).toBeDisabled();

    // A live-but-inert chevron used to record a collapse that only sprang shut once the
    // search was cleared, hiding files the user never asked to hide.
    await userEvent.click(folder);
    expect(screen.getByRole("button", { name: "equil" })).toHaveAttribute("aria-expanded", "true");

    await userEvent.clear(search);
    expect(screen.getByRole("button", { name: "equil" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
  });

  it("selects a file when its name is clicked", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    renderPanel();
    const name = await screen.findByRole("button", { name: "system.prmtop" });
    await queriesSettled();
    await userEvent.click(name);
    await waitFor(() =>
      expect(screen.getByTestId("row:/work/system.prmtop").className).toContain("bg-accent-subtle"),
    );
  });

  it("starts a drag from the filename, not only from the 14px grip", async () => {
    // The grip is roughly a tenth of a ~48px row that also carries a two-line subtitle. A user
    // who presses on the name and pulls concludes files cannot be dragged at all.
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    const onDragStart = vi.fn();
    renderPanel(onDragStart);
    const name = await screen.findByRole("button", { name: "system.prmtop" });
    await queriesSettled();

    dragFrom(name);

    await waitFor(() => expect(onDragStart).toHaveBeenCalledTimes(1));
    expect(String(onDragStart.mock.calls[0][0].active.id)).toBe("file:/work/system.prmtop");
    fireEvent(document, pointerEvent("pointerup"));
  });

  it("still starts a drag from the grip, which names the file it belongs to", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(tree)));
    const onDragStart = vi.fn();
    renderPanel(onDragStart);
    // Without the label a screen-reader user hears one unnamed "button" per file row.
    const grip = await screen.findByLabelText("drag system.prmtop");
    await queriesSettled();

    dragFrom(grip);

    await waitFor(() => expect(onDragStart).toHaveBeenCalledTimes(1));
    expect(String(onDragStart.mock.calls[0][0].active.id)).toBe("file:/work/system.prmtop");
    fireEvent(document, pointerEvent("pointerup"));
  });

  it("shows loading, then an empty state when nothing matches", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json([])));
    renderPanel();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    expect(await screen.findByText(/no files found/i)).toBeInTheDocument();
  });

  it("shows an error state when the file listing fails", async () => {
    server.use(http.get("/api/files", () => new HttpResponse(null, { status: 500 })));
    renderPanel();
    expect(await screen.findByText(/could not load files/i)).toBeInTheDocument();
  });
});
