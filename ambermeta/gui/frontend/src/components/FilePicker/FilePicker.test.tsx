import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { FilePicker } from "./FilePicker";

const files = [
  { path: "/work/system.prmtop", name: "system.prmtop", file_type: "prmtop",
    is_directory: false, size: 1, extension: ".prmtop", parent: "/work", children: null },
];

function setup(mode: "open" | "save", onPick = vi.fn()) {
  queryClient.clear();
  server.use(http.get("/api/files", () => HttpResponse.json(files)));
  render(
    <QueryClientProvider client={queryClient}>
      <FilePicker open mode={mode} title="Pick a file" onPick={onPick} onClose={vi.fn()} />
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
    await userEvent.type(pathInput, "/work/protocol.toml");
    await userEvent.selectOptions(screen.getByLabelText(/format/i), "toml");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onPick).toHaveBeenCalledWith({ path: "/work/protocol.toml", format: "toml" });
  });
});
