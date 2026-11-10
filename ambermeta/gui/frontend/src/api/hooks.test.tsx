import { it, expect } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { useDocument, useAddTopology, useFiles, useSave } from "@/api/hooks";

function Probe() {
  const { data } = useDocument();
  const add = useAddTopology();
  return (
    <div>
      <span data-testid="n">{data?.simulation.topologies.length ?? -1}</span>
      <button onClick={() => add.mutate({ path: "wt.prmtop", kind: "hmr" })}>add</button>
    </div>
  );
}

it("addTopology writes the returned doc into the one cache", async () => {
  server.use(http.post("/api/topologies", () => HttpResponse.json(
    { ...emptyDocument, simulation: { ...emptyDocument.simulation, topologies: [{ id: "t0", path: "wt.prmtop", kind: "hmr" }] } })));
  render(<QueryClientProvider client={queryClient}><Probe /></QueryClientProvider>);
  await waitFor(() => expect(screen.getByTestId("n").textContent).toBe("0"));
  await act(async () => { screen.getByText("add").click(); });
  await waitFor(() => expect(screen.getByTestId("n").textContent).toBe("1"));
});

// A file the GUI had just saved did not appear in Open, or in the Files pane, until the
// page was reloaded: the tree is cached and nothing told it the disk had changed.
it("a save refreshes the file list, which now holds the file it wrote", async () => {
  let listed = 0;
  server.use(
    http.get("/api/files", () => { listed += 1; return HttpResponse.json([]); }),
    http.post("/api/document/save", () => HttpResponse.json(
      { document: { ...emptyDocument, manifest_path: "/work/manifest.yaml" }, warnings: [] })),
  );
  function FilesAndSave() {
    useFiles({ recursive: true, include_all: false });
    const save = useSave();
    return <button onClick={() => save.mutate({ path: "manifest.yaml" })}>save</button>;
  }
  queryClient.clear();
  render(<QueryClientProvider client={queryClient}><FilesAndSave /></QueryClientProvider>);
  await waitFor(() => expect(listed).toBe(1));

  await act(async () => { screen.getByText("save").click(); });

  await waitFor(() => expect(listed).toBe(2));
});
