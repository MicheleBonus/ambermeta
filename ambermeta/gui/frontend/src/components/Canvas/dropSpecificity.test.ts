import { describe, it, expect } from "vitest";
import type { CollisionDetection } from "@dnd-kit/core";
import { canvasCollisionDetection, dropCeiling, dropRank, mostSpecific } from "./dropSpecificity";

describe("dropRank", () => {
  it("ranks nested droppables most-specific-first", () => {
    expect(dropRank("slot:s0:mdin")).toBeGreaterThan(dropRank("step:s0"));
    expect(dropRank("step:s0")).toBeGreaterThan(dropRank("phase:p0"));
    expect(dropRank("phase:p0")).toBeGreaterThan(dropRank("pool"));
    expect(dropRank("phase:p0")).toBeGreaterThan(dropRank("starting"));
    expect(dropRank("pool")).toBeGreaterThan(dropRank("canvas"));
    expect(dropRank("starting")).toBeGreaterThan(dropRank("canvas"));
    expect(dropRank("canvas")).toBeGreaterThan(dropRank("something-else"));
  });
  it("ranks pool and starting equally", () => {
    expect(dropRank("pool")).toBe(dropRank("starting"));
  });
  it("gives every unknown id the same lowest rank", () => {
    expect(dropRank("sidebar")).toBe(dropRank("file:/w/x.prmtop"));
  });
  it("does not confuse a bare id with a prefixed one", () => {
    expect(dropRank("steps")).toBe(dropRank("whatever"));
    expect(dropRank("phased")).toBe(dropRank("whatever"));
  });
});

describe("mostSpecific", () => {
  it("returns null for no collisions", () => {
    expect(mostSpecific([])).toBeNull();
  });
  it("picks the slot over the enclosing step, phase and canvas", () => {
    const collisions = [{ id: "canvas" }, { id: "phase:p0" }, { id: "step:s0" }, { id: "slot:s0:mdin" }];
    expect(mostSpecific(collisions)).toEqual({ id: "slot:s0:mdin" });
  });
  it("picks the step over the enclosing phase", () => {
    expect(mostSpecific([{ id: "phase:p0" }, { id: "step:s0" }])).toEqual({ id: "step:s0" });
  });
  it("picks the phase over the canvas", () => {
    expect(mostSpecific([{ id: "canvas" }, { id: "phase:p0" }])).toEqual({ id: "phase:p0" });
  });
  it("falls back to the canvas when it is the only collision", () => {
    expect(mostSpecific([{ id: "canvas" }])).toEqual({ id: "canvas" });
  });
  it("keeps the first collision on a rank tie", () => {
    const first = { id: "step:s0", rect: 1 };
    const second = { id: "step:s1", rect: 2 };
    expect(mostSpecific([first, second])).toBe(first);
  });
  it("preserves the full collision object, not just the id", () => {
    const hit = { id: "step:s0", data: { droppableContainer: "x" } };
    expect(mostSpecific([{ id: "canvas" }, hit])).toBe(hit);
  });
  it("accepts numeric dnd-kit ids", () => {
    expect(mostSpecific([{ id: 42 }, { id: "step:s0" }])).toEqual({ id: "step:s0" });
    expect(mostSpecific([{ id: 42 }])).toEqual({ id: 42 });
  });
});

describe("dropCeiling", () => {
  it("lets a file reach the innermost target there is", () => {
    expect(dropCeiling("file:/w/min.in")).toBe(dropRank("slot:s0:mdin"));
  });
  it("stops a step drag at the step level, above the slot chips inside a step", () => {
    expect(dropCeiling("step:s1")).toBe(dropRank("step:s0"));
    expect(dropCeiling("step:s1")).toBeLessThan(dropRank("slot:s0:mdin"));
  });
  it("stops a phase drag at the phase level, above the steps inside a phase", () => {
    expect(dropCeiling("phase:p1")).toBe(dropRank("phase:p0"));
    expect(dropCeiling("phase:p1")).toBeLessThan(dropRank("step:s0"));
  });
});

describe("canvasCollisionDetection", () => {
  const rect = (left: number, top: number, width: number, height: number) => ({
    left, top, width, height, right: left + width, bottom: top + height,
  });
  // canvas > phase > step > slot, each nested inside the previous one.
  const rects = new Map([
    ["canvas", rect(0, 0, 600, 600)],
    ["phase:p0", rect(0, 0, 400, 300)],
    ["step:s0", rect(0, 0, 200, 100)],
    ["slot:s0:mdin", rect(0, 0, 60, 20)],
  ]);

  function args(
    pointer: { x: number; y: number } | null,
    collisionRect = rect(0, 0, 10, 10),
    activeId = "file:/w/min.in",
  ) {
    return {
      active: { id: activeId, data: { current: {} }, rect: { current: { initial: null, translated: null } } },
      collisionRect,
      droppableRects: rects,
      droppableContainers: [...rects.keys()].map((id) => ({ id })),
      pointerCoordinates: pointer,
    } as unknown as Parameters<CollisionDetection>[0];
  }

  const hits = (...a: Parameters<typeof args>) => canvasCollisionDetection(args(...a)).map((c) => c.id);

  it("picks the innermost droppable under the pointer for a file drag", () => {
    expect(hits({ x: 10, y: 10 })).toEqual(["slot:s0:mdin"]);
    expect(hits({ x: 150, y: 50 })).toEqual(["step:s0"]);
    expect(hits({ x: 350, y: 250 })).toEqual(["phase:p0"]);
    expect(hits({ x: 500, y: 500 })).toEqual(["canvas"]);
  });

  it("falls back to rect intersection when the pointer is outside every rect", () => {
    // No pointer at all -- the dragged rect still overlaps phase + canvas.
    expect(hits(null, rect(350, 250, 100, 100))).toEqual(["phase:p0"]);
    // Pointer far outside, dragged rect still on the canvas only.
    expect(hits({ x: 5000, y: 5000 }, rect(450, 350, 50, 50))).toEqual(["canvas"]);
  });

  it("returns nothing when neither the pointer nor the dragged rect touch a droppable", () => {
    expect(canvasCollisionDetection(args({ x: 5000, y: 5000 }, rect(5000, 5000, 10, 10)))).toEqual([]);
  });

  it("hands a step drag the enclosing step, never one of that step's slot chips", () => {
    // The slot chips are a strip across the bottom of every step card; releasing a reorder on
    // one must still reorder against the card, not resolve to a target with no route.
    expect(hits({ x: 10, y: 10 }, undefined, "step:s1")).toEqual(["step:s0"]);
    expect(hits({ x: 150, y: 50 }, undefined, "step:s1")).toEqual(["step:s0"]);
    // Outside every step, a step drag still lands on the phase (move between phases).
    expect(hits({ x: 350, y: 250 }, undefined, "step:s1")).toEqual(["phase:p0"]);
  });

  it("hands a phase drag the enclosing phase, never a step or slot inside it", () => {
    // Most of a phase section's area is step cards, so this is where a phase reorder is aimed.
    expect(hits({ x: 10, y: 10 }, undefined, "phase:p1")).toEqual(["phase:p0"]);
    expect(hits({ x: 150, y: 50 }, undefined, "phase:p1")).toEqual(["phase:p0"]);
    expect(hits({ x: 350, y: 250 }, undefined, "phase:p1")).toEqual(["phase:p0"]);
    expect(hits({ x: 500, y: 500 }, undefined, "phase:p1")).toEqual(["canvas"]);
  });

  it("applies the ceiling to the rect-intersection fallback too", () => {
    // No pointer, dragged rect over the nested step: a phase drag must still see the phase.
    expect(hits(null, rect(0, 0, 50, 50), "phase:p1")).toEqual(["phase:p0"]);
    expect(hits(null, rect(0, 0, 10, 10), "step:s1")).toEqual(["step:s0"]);
  });
});
