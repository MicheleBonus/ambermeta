import { describe, it, expect, beforeEach } from "vitest";
import { queryClient, setDocument, DOCUMENT_KEY } from "./queryClient";
import { emptyDocument } from "@/test/server";

describe("setDocument cache coherence", () => {
  beforeEach(() => queryClient.clear());
  it("stores the document and invalidates the sequences query", () => {
    queryClient.setQueryData(["sequences"], { a: ["1", "2"] });
    setDocument({ ...emptyDocument });
    expect(queryClient.getQueryData(DOCUMENT_KEY)).toBeTruthy();
    expect(queryClient.getQueryState(["sequences"])?.isInvalidated).toBe(true);
  });
});
