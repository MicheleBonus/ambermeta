import { it, expect } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient, DOCUMENT_KEY } from "@/api/queryClient";
import { AssignActions } from "./AssignActions";
import type { DocumentResponse } from "@/types";

const PATH = "/work/wt_hmr.prmtop";

function setup() {
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <AssignActions path={PATH} fileType="prmtop" />
    </QueryClientProvider>
  );
}

it("Add to pool as HMR posts to /api/topologies and writes the returned doc into the cache", async () => {
  let body: unknown;
  server.use(
    http.post("/api/topologies", async ({ request }) => {
      body = await request.json();
      const doc: DocumentResponse = {
        ...emptyDocument,
        simulation: {
          ...emptyDocument.simulation,
          topologies: [{ id: "t0", path: PATH, kind: "hmr" }],
        },
      };
      return HttpResponse.json(doc);
    }),
    http.post("/api/assign", () => HttpResponse.json(emptyDocument))
  );

  setup();

  await act(async () => {
    screen.getByText("Add to pool as HMR").click();
  });

  await waitFor(() => expect(body).toEqual({ path: PATH, kind: "hmr" }));
  await waitFor(() =>
    expect((queryClient.getQueryData(DOCUMENT_KEY) as DocumentResponse).simulation.topologies).toHaveLength(1)
  );
});
