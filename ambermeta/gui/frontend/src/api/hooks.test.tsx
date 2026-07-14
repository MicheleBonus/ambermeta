import { describe, it, expect } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { useDocument, useAddTopology } from "@/api/hooks";

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
