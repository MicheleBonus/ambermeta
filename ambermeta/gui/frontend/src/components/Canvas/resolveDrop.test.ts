import { describe, it, expect } from "vitest";
import { resolveDrop } from "./resolveDrop";

describe("resolveDrop", () => {
  it("routes a file onto the pool / starting / a slot", () => {
    expect(resolveDrop("file:/w/wt.prmtop", "pool")).toEqual({ type: "pool", path: "/w/wt.prmtop" });
    expect(resolveDrop("file:/w/wt.inpcrd", "starting")).toEqual({ type: "starting", path: "/w/wt.inpcrd" });
    expect(resolveDrop("file:/w/min.in", "slot:s0:mdin")).toEqual({ type: "step_slot", stepId: "s0", kind: "mdin", path: "/w/min.in" });
    expect(resolveDrop("file:/w/wt_hmr.prmtop", "step:s0")).toEqual({ type: "step_topology", stepId: "s0", path: "/w/wt_hmr.prmtop" });
    expect(resolveDrop("file:/w/wt_hmr.prmtop", "phase:p0")).toEqual({ type: "phase_topology", phaseId: "p0", path: "/w/wt_hmr.prmtop" });
  });
  it("routes step/phase reorder + move", () => {
    expect(resolveDrop("step:s1", "step:s2")).toEqual({ type: "reorder_or_move_step", activeStepId: "s1", overStepId: "s2" });
    expect(resolveDrop("step:s1", "phase:p2")).toEqual({ type: "move_step", stepId: "s1", phaseId: "p2" });
    expect(resolveDrop("phase:p1", "phase:p2")).toEqual({ type: "reorder_phases", activePhaseId: "p1", overPhaseId: "p2" });
  });
  it("returns null on unknown/self drops", () => {
    expect(resolveDrop("file:/w/x", null)).toBeNull();
    expect(resolveDrop("step:s1", "step:s1")).toBeNull();
  });
});
