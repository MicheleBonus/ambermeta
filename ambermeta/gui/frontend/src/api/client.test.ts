import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { api, ApiError } from "./client";

describe("api client", () => {
  it("GET /document returns the document", async () => {
    const doc = await api.getDocument();
    expect(doc.base_directory).toBe("/work");
    expect(doc.stages).toEqual([]);
  });

  it("POST /document/open posts the path and returns a document", async () => {
    server.use(
      http.post("/api/document/open", async ({ request }) => {
        const body = (await request.json()) as { path: string };
        expect(body.path).toBe("/work/p.yaml");
        return HttpResponse.json({ ...emptyDocument, manifest_path: "/work/p.yaml" });
      })
    );
    const doc = await api.openDocument("/work/p.yaml");
    expect(doc.manifest_path).toBe("/work/p.yaml");
  });

  it("throws ApiError with status + detail on 4xx", async () => {
    server.use(
      http.post("/api/document/open", () =>
        HttpResponse.json({ detail: "Could not read manifest: bad" }, { status: 400 })
      )
    );
    await expect(api.openDocument("/work/bad.yaml")).rejects.toMatchObject({
      status: 400,
      detail: "Could not read manifest: bad",
    });
    await expect(api.openDocument("/work/bad.yaml")).rejects.toBeInstanceOf(ApiError);
  });

  it("save returns a SaveResult with warnings", async () => {
    server.use(
      http.post("/api/document/save", () =>
        HttpResponse.json({ document: emptyDocument, warnings: ["w"] })
      )
    );
    const res = await api.saveDocument({ path: "/work/p.csv", format: "csv" });
    expect(res.warnings).toEqual(["w"]);
  });
});
