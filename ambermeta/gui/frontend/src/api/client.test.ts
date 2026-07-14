import { it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { api, ApiError } from "./client";
import { emptyDocument } from "@/test/server";

const server = setupServer(
  http.post("/api/topologies", async ({ request }) => {
    const body = (await request.json()) as { path: string; kind: string };
    return HttpResponse.json({ ...emptyDocument, simulation: { ...emptyDocument.simulation,
      topologies: [{ id: "t0", path: body.path, kind: body.kind }] } });
  }),
  http.post("/api/assign", () => HttpResponse.json(emptyDocument)),
  http.get("/api/files/raw", () => HttpResponse.json({ path: "/w/x", content: "hi", truncated: false })),
  http.put("/api/steps/s0", () => new HttpResponse(null, { status: 404 })),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

it("addTopology posts and returns the document", async () => {
  const doc = await api.addTopology({ path: "wt.prmtop", kind: "hmr" });
  expect(doc.simulation.topologies[0].kind).toBe("hmr");
});
it("fileRaw fetches the head", async () => {
  expect((await api.fileRaw("x")).content).toBe("hi");
});
it("surfaces ApiError on 404", async () => {
  await expect(api.updateStep("s0", { name: "x" })).rejects.toBeInstanceOf(ApiError);
});
