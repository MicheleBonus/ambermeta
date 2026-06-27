import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { FileBrowser } from "./FileBrowser";

function renderFB() {
  queryClient.clear();
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider><DndContext><FileBrowser /></DndContext></SelectionProvider>
    </QueryClientProvider>
  );
}

const files = [
  { path: "/work/system.prmtop", name: "system.prmtop", file_type: "prmtop",
    is_directory: false, size: 100, extension: ".prmtop", parent: "/work", children: null },
  { path: "/work/prod.mdin", name: "prod.mdin", file_type: "mdin",
    is_directory: false, size: 50, extension: ".mdin", parent: "/work", children: null },
];

describe("FileBrowser", () => {
  it("lists files and filters by search", async () => {
    server.use(http.get("/api/files", () => HttpResponse.json(files)));
    renderFB();
    await waitFor(() => expect(screen.getByText("system.prmtop")).toBeInTheDocument());
    expect(screen.getByText("prod.mdin")).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText(/search/i), "prod");
    expect(screen.queryByText("system.prmtop")).not.toBeInTheDocument();
    expect(screen.getByText("prod.mdin")).toBeInTheDocument();
  });

  it("shows metadata on selecting a file", async () => {
    server.use(
      http.get("/api/files", () => HttpResponse.json(files)),
      http.get("/api/files/metadata", () =>
        HttpResponse.json({
          file_path: "/work/prod.mdin", file_type: "mdin",
          metadata: { details: { dt: 0.002, length_steps: 1000 }, warnings: [], kind: "mdin" },
          warnings: [],
        })
      )
    );
    renderFB();
    await waitFor(() => expect(screen.getByText("prod.mdin")).toBeInTheDocument());
    await userEvent.click(screen.getByText("prod.mdin"));
    await waitFor(() => expect(screen.getByTestId("file-metadata")).toHaveTextContent("0.002"));
  });
});
