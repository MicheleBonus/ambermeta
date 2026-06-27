import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "./queryClient";
import { useDocument, useCreateStage } from "./hooks";
import type { ReactNode } from "react";

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("react-query hooks", () => {
  beforeEach(() => queryClient.clear()); // singleton cache — clear between tests to avoid leakage

  it("useDocument loads the document", async () => {
    const { result } = renderHook(() => useDocument(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.base_directory).toBe("/work");
  });

  it("createStage writes the returned document into the cache", async () => {
    const withStage = {
      ...emptyDocument, dirty: true,
      stages: [{ ...stageFixture, id: "abc", name: "min" }],
    };
    server.use(http.post("/api/stages", () => HttpResponse.json(withStage)));

    // Render BOTH hooks in ONE tree so the mutation and the query share the same
    // React reconciliation — the cache update propagates within act() (rendering
    // them in two separate renderHook trees races the cross-tree notification).
    const { result } = renderHook(
      () => ({ doc: useDocument(), create: useCreateStage() }),
      { wrapper }
    );
    await waitFor(() => expect(result.current.doc.isSuccess).toBe(true));
    await act(async () => { await result.current.create.mutateAsync({ name: "min" }); });

    await waitFor(() =>
      expect(result.current.doc.data?.stages.map((s) => s.name)).toEqual(["min"])
    );
    expect(result.current.doc.data?.dirty).toBe(true);
  });
});

const stageFixture = {
  id: "", name: "", role: "", prmtop: null, mdin: null, mdout: null,
  mdcrd: null, inpcrd: null, expected_gap_ps: null, gap_tolerance_ps: null, notes: [],
};
