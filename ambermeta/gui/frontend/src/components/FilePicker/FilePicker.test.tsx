import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { FilePicker } from "./FilePicker";
import type { FileInfo, FileType } from "@/types";

const files = [
  { path: "/work/system.prmtop", name: "system.prmtop", file_type: "prmtop",
    is_directory: false, size: 1, extension: ".prmtop", parent: "/work", children: null },
];

const mixed: FileInfo[] = [
  { path: "/work/system.prmtop", name: "system.prmtop", file_type: "prmtop",
    is_directory: false, size: 1, extension: ".prmtop", parent: "/work", children: null },
  { path: "/work/equil/02_heat.mdin", name: "02_heat.mdin", file_type: "mdin",
    is_directory: false, size: 1, extension: ".mdin", parent: "/work/equil", children: null },
  { path: "/work/runs/02_heat.mdout", name: "02_heat.mdout", file_type: "mdout",
    is_directory: false, size: 1, extension: ".mdout", parent: "/work/runs", children: null },
];

function setup(
  mode: "open" | "save",
  onPick = vi.fn(),
  opts: { filterType?: FileType; files?: FileInfo[] } = {},
) {
  queryClient.clear();
  server.use(http.get("/api/files", () => HttpResponse.json(opts.files ?? files)));
  render(
    <QueryClientProvider client={queryClient}>
      <FilePicker open mode={mode} title="Pick a file" filterType={opts.filterType}
        onPick={onPick} onClose={vi.fn()} />
    </QueryClientProvider>
  );
  return onPick;
}

describe("FilePicker", () => {
  it("open mode: clicking a file picks its path", async () => {
    const onPick = setup("open");
    await waitFor(() => expect(screen.getByText("system.prmtop")).toBeInTheDocument());
    await userEvent.click(screen.getByText("system.prmtop"));
    expect(onPick).toHaveBeenCalledWith({ path: "/work/system.prmtop" });
  });

  it("save mode: picks path + chosen format", async () => {
    const onPick = setup("save");
    const pathInput = await screen.findByLabelText(/path/i);
    await userEvent.clear(pathInput);
    await userEvent.type(pathInput, "/work/protocol.json");
    await userEvent.selectOptions(screen.getByLabelText(/format/i), "json");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onPick).toHaveBeenCalledWith({ path: "/work/protocol.json", format: "json" });
  });

  it("save mode offers only the formats the manifest writer accepts", async () => {
    // toml and csv were selectable and always came back 400 — the dialog offered a
    // choice the backend rejects. Export covers the lossy flat views.
    setup("save");
    const format = await screen.findByLabelText(/format/i);
    expect(within(format).getByRole("option", { name: "yaml" })).toBeInTheDocument();
    expect(within(format).getByRole("option", { name: "json" })).toBeInTheDocument();
    expect(within(format).queryByRole("option", { name: "toml" })).not.toBeInTheDocument();
    expect(within(format).queryByRole("option", { name: "csv" })).not.toBeInTheDocument();
  });

  it("save mode will not save a path of pure whitespace", async () => {
    const onPick = setup("save");
    const pathInput = await screen.findByLabelText(/path/i);
    await userEvent.clear(pathInput);
    await userEvent.type(pathInput, "   ");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(onPick).not.toHaveBeenCalled();
  });

  it("without filterType every file is still listed", async () => {
    setup("open", vi.fn(), { files: mixed });
    await waitFor(() => expect(screen.getByText("system.prmtop")).toBeInTheDocument());
    expect(screen.getByText("02_heat.mdin")).toBeInTheDocument();
    expect(screen.getByText("02_heat.mdout")).toBeInTheDocument();
  });

  it("filterType narrows the list to that file type, so the title stops lying", async () => {
    const onPick = setup("open", vi.fn(), { filterType: "mdin", files: mixed });
    await waitFor(() => expect(screen.getByText("02_heat.mdin")).toBeInTheDocument());
    expect(screen.queryByText("02_heat.mdout")).not.toBeInTheDocument();
    expect(screen.queryByText("system.prmtop")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("02_heat.mdin"));
    expect(onPick).toHaveBeenCalledWith({ path: "/work/equil/02_heat.mdin" });
  });

  it("says why the list is empty instead of showing a blank box", async () => {
    // detect_file_type only maps .out/.mdout to MDOUT, so a prod_0001.log output is `other`
    // and a filtered picker had nothing in it and nothing to say about why.
    setup("open", vi.fn(), { filterType: "mdout", files: [files[0] as FileInfo] });
    expect(await screen.findByText(/no mdout files found/i)).toBeInTheDocument();
  });

  it("offers a way out of the filter, so an `other`-typed file is still pickable", async () => {
    const onPick = setup("open", vi.fn(), { filterType: "mdout", files: [files[0] as FileInfo] });
    await screen.findByText(/no mdout files found/i);

    await userEvent.click(screen.getByLabelText(/show all file types/i));

    expect(screen.queryByText(/no mdout files found/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("system.prmtop"));
    expect(onPick).toHaveBeenCalledWith({ path: "/work/system.prmtop" });
  });

  it("offers no filter escape hatch when the picker was never filtered", async () => {
    setup("open", vi.fn(), { files: mixed });
    await screen.findByText("system.prmtop");
    expect(screen.queryByLabelText(/show all file types/i)).not.toBeInTheDocument();
  });

});
