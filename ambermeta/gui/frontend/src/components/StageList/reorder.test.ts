import { describe, it, expect } from "vitest";
import { reorderIds, resolveDrop } from "./reorder";

describe("reorderIds", () => {
  it("moves active before/after over preserving the rest", () => {
    expect(reorderIds(["a", "b", "c", "d"], "d", "b")).toEqual(["a", "d", "b", "c"]);
    expect(reorderIds(["a", "b", "c"], "a", "c")).toEqual(["b", "c", "a"]);
  });
  it("is a no-op when active === over", () => {
    expect(reorderIds(["a", "b"], "a", "a")).toEqual(["a", "b"]);
  });
});

describe("resolveDrop", () => {
  it("routes a file→slot drop to an assign", () => {
    expect(resolveDrop("file:/work/min.in", "slot:s1:mdin")).toEqual({
      type: "assign", stageId: "s1", kind: "mdin", path: "/work/min.in",
    });
  });
  it("routes a file path containing colons correctly (only the prefix is split)", () => {
    expect(resolveDrop("file:C:/work/min.in", "slot:s1:prmtop")).toEqual({
      type: "assign", stageId: "s1", kind: "prmtop", path: "C:/work/min.in",
    });
  });
  it("routes a stage→stage drop to a reorder", () => {
    expect(resolveDrop("s1", "s2")).toEqual({ type: "reorder", activeId: "s1", overId: "s2" });
  });
  it("returns null for unhandled combinations", () => {
    expect(resolveDrop("file:/x", "s2")).toBeNull();
    expect(resolveDrop("file:/x", null)).toBeNull();
    expect(resolveDrop("s1", null)).toBeNull();
  });
  it("resolves a file dropped on the empty canvas to a create", () => {
    expect(resolveDrop("file:/work/equil/01_min.mdin", "new-stage"))
      .toEqual({ type: "create", path: "/work/equil/01_min.mdin" });
  });
});
