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

describe("resolveDrop — file-type aware routing", () => {
  const P = "file:/w/wt.prmtop";
  const I = "file:/w/wt.inpcrd";
  const IN = "file:/w/min.in";
  const OUT = "file:/w/min.out";
  const CRD = "file:/w/prod.nc";
  const OTHER = "file:/w/notes.txt";

  describe("over `pool` — always pools, whatever the type", () => {
    it("prmtop", () => expect(resolveDrop(P, "pool", "prmtop")).toEqual({ type: "pool", path: "/w/wt.prmtop" }));
    it("inpcrd", () => expect(resolveDrop(I, "pool", "inpcrd")).toEqual({ type: "pool", path: "/w/wt.inpcrd" }));
    it("mdin", () => expect(resolveDrop(IN, "pool", "mdin")).toEqual({ type: "pool", path: "/w/min.in" }));
    it("mdout", () => expect(resolveDrop(OUT, "pool", "mdout")).toEqual({ type: "pool", path: "/w/min.out" }));
    it("mdcrd", () => expect(resolveDrop(CRD, "pool", "mdcrd")).toEqual({ type: "pool", path: "/w/prod.nc" }));
    it("other", () => expect(resolveDrop(OTHER, "pool", "other")).toEqual({ type: "pool", path: "/w/notes.txt" }));
  });

  describe("over `starting` — always the starting structure, whatever the type", () => {
    it("prmtop", () => expect(resolveDrop(P, "starting", "prmtop")).toEqual({ type: "starting", path: "/w/wt.prmtop" }));
    it("inpcrd", () => expect(resolveDrop(I, "starting", "inpcrd")).toEqual({ type: "starting", path: "/w/wt.inpcrd" }));
    it("mdin", () => expect(resolveDrop(IN, "starting", "mdin")).toEqual({ type: "starting", path: "/w/min.in" }));
    it("mdcrd", () => expect(resolveDrop(CRD, "starting", "mdcrd")).toEqual({ type: "starting", path: "/w/prod.nc" }));
    it("other", () => expect(resolveDrop(OTHER, "starting", "other")).toEqual({ type: "starting", path: "/w/notes.txt" }));
  });

  describe("over an explicit `slot:` — permissive, the user aimed at that slot", () => {
    it("prmtop into an mdin slot is honoured", () =>
      expect(resolveDrop(P, "slot:s0:mdin", "prmtop")).toEqual({ type: "step_slot", stepId: "s0", kind: "mdin", path: "/w/wt.prmtop" }));
    it("inpcrd into an mdcrd slot is honoured", () =>
      expect(resolveDrop(I, "slot:s0:mdcrd", "inpcrd")).toEqual({ type: "step_slot", stepId: "s0", kind: "mdcrd", path: "/w/wt.inpcrd" }));
    it("mdout into an mdin slot is honoured (no type coercion)", () =>
      expect(resolveDrop(OUT, "slot:s0:mdin", "mdout")).toEqual({ type: "step_slot", stepId: "s0", kind: "mdin", path: "/w/min.out" }));
    it("other into an mdout slot is honoured", () =>
      expect(resolveDrop(OTHER, "slot:s0:mdout", "other")).toEqual({ type: "step_slot", stepId: "s0", kind: "mdout", path: "/w/notes.txt" }));
  });

  describe("over `step:<id>`", () => {
    it("prmtop -> step topology", () =>
      expect(resolveDrop(P, "step:s0", "prmtop")).toEqual({ type: "step_topology", stepId: "s0", path: "/w/wt.prmtop" }));
    it("inpcrd -> step input coords", () =>
      expect(resolveDrop(I, "step:s0", "inpcrd")).toEqual({ type: "step_input_coords", stepId: "s0", path: "/w/wt.inpcrd" }));
    it("mdin -> the mdin slot of that step", () =>
      expect(resolveDrop(IN, "step:s0", "mdin")).toEqual({ type: "step_slot", stepId: "s0", kind: "mdin", path: "/w/min.in" }));
    it("mdout -> the mdout slot of that step", () =>
      expect(resolveDrop(OUT, "step:s0", "mdout")).toEqual({ type: "step_slot", stepId: "s0", kind: "mdout", path: "/w/min.out" }));
    it("mdcrd -> the mdcrd slot of that step", () =>
      expect(resolveDrop(CRD, "step:s0", "mdcrd")).toEqual({ type: "step_slot", stepId: "s0", kind: "mdcrd", path: "/w/prod.nc" }));
    // "Show all files" surfaces file_type=="other" rows that used to be unreachable. Letting one
    // fall through to a topology assignment overwrites the step's real .prmtop on a single drag.
    it("other -> rejected, naming the file, rather than a silent topology overwrite", () => {
      const action = resolveDrop(OTHER, "step:s0", "other");
      expect(action?.type).toBe("rejected");
      expect(action).toMatchObject({ path: "/w/notes.txt" });
      expect(action && "reason" in action && action.reason).toMatch(/notes\.txt/);
    });
  });

  describe("over `phase:<id>`", () => {
    it("prmtop -> phase topology", () =>
      expect(resolveDrop(P, "phase:p0", "prmtop")).toEqual({ type: "phase_topology", phaseId: "p0", path: "/w/wt.prmtop" }));
    it("inpcrd -> create a step in that phase continuing from that file", () =>
      expect(resolveDrop(I, "phase:p0", "inpcrd")).toEqual({
        type: "create_step_with_coords", phaseId: "p0", path: "/w/wt.inpcrd",
      }));
    it("mdin -> create a step in that phase with the mdin slot filled", () =>
      expect(resolveDrop(IN, "phase:p0", "mdin")).toEqual({ type: "create_step_in_phase", phaseId: "p0", path: "/w/min.in", slot: "mdin" }));
    it("mdout -> create a step in that phase with the mdout slot filled", () =>
      expect(resolveDrop(OUT, "phase:p0", "mdout")).toEqual({ type: "create_step_in_phase", phaseId: "p0", path: "/w/min.out", slot: "mdout" }));
    it("mdcrd -> create a step in that phase with the mdcrd slot filled", () =>
      expect(resolveDrop(CRD, "phase:p0", "mdcrd")).toEqual({ type: "create_step_in_phase", phaseId: "p0", path: "/w/prod.nc", slot: "mdcrd" }));
    // phase_topology rewrites `topology` on every step in the phase, so the blast radius of
    // letting an unrecognised file through here is the whole phase.
    it("other -> rejected, naming the file, rather than a phase-wide topology overwrite", () => {
      const action = resolveDrop(OTHER, "phase:p0", "other");
      expect(action?.type).toBe("rejected");
      expect(action).toMatchObject({ path: "/w/notes.txt" });
      expect(action && "reason" in action && action.reason).toMatch(/notes\.txt/);
    });
  });

  describe("over `canvas` (empty background)", () => {
    it("prmtop -> pool", () => expect(resolveDrop(P, "canvas", "prmtop")).toEqual({ type: "pool", path: "/w/wt.prmtop" }));
    it("inpcrd -> starting structure", () => expect(resolveDrop(I, "canvas", "inpcrd")).toEqual({ type: "starting", path: "/w/wt.inpcrd" }));
    it("mdin -> create a new phase carrying a step with that mdin", () =>
      expect(resolveDrop(IN, "canvas", "mdin")).toEqual({ type: "create_phase_with_step", path: "/w/min.in", slot: "mdin" }));
    it("mdout -> create a new phase carrying a step with that mdout", () =>
      expect(resolveDrop(OUT, "canvas", "mdout")).toEqual({ type: "create_phase_with_step", path: "/w/min.out", slot: "mdout" }));
    it("mdcrd -> create a new phase carrying a step with that mdcrd", () =>
      expect(resolveDrop(CRD, "canvas", "mdcrd")).toEqual({ type: "create_phase_with_step", path: "/w/prod.nc", slot: "mdcrd" }));
    it("other -> rejected, naming the file", () => {
      const action = resolveDrop(OTHER, "canvas", "other");
      expect(action?.type).toBe("rejected");
      expect(action && "reason" in action && action.reason).toMatch(/notes\.txt/);
    });
  });

  describe("back-compat: an undefined fileType behaves exactly as before", () => {
    it("pool / starting / slot are unchanged", () => {
      expect(resolveDrop(IN, "pool", undefined)).toEqual({ type: "pool", path: "/w/min.in" });
      expect(resolveDrop(IN, "starting", undefined)).toEqual({ type: "starting", path: "/w/min.in" });
      expect(resolveDrop(IN, "slot:s0:mdout", undefined)).toEqual({ type: "step_slot", stepId: "s0", kind: "mdout", path: "/w/min.in" });
    });
    it("step: -> step_topology even for an mdin path", () =>
      expect(resolveDrop(IN, "step:s0", undefined)).toEqual({ type: "step_topology", stepId: "s0", path: "/w/min.in" }));
    it("phase: -> phase_topology even for an mdin path", () =>
      expect(resolveDrop(IN, "phase:p0", undefined)).toEqual({ type: "phase_topology", phaseId: "p0", path: "/w/min.in" }));
    it("canvas -> null", () => expect(resolveDrop(IN, "canvas", undefined)).toBeNull());
    it("an inpcrd path on a phase is still phase_topology without a type", () =>
      expect(resolveDrop(I, "phase:p0", undefined)).toEqual({ type: "phase_topology", phaseId: "p0", path: "/w/wt.inpcrd" }));
  });

  describe("folder + unknown over-ids", () => {
    it("a folder is treated like `other`", () => {
      expect(resolveDrop("file:/w/run1", "step:s0", "folder")?.type).toBe("rejected");
      expect(resolveDrop("file:/w/run1", "canvas", "folder")?.type).toBe("rejected");
    });
    // Null still means "nothing happened at all" -- no target, a self-drop, an id off the canvas --
    // so App can tell those apart from a live target that had to turn a file away.
    it("an unrecognised over-id is still null", () => expect(resolveDrop(IN, "sidebar", "mdin")).toBeNull());
    it("a drop outside every target is still null", () => expect(resolveDrop(OTHER, null, "other")).toBeNull());
  });

  it("keeps absolute Windows paths (which contain a colon) intact", () => {
    expect(resolveDrop("file:C:\\Users\\me\\run\\min.in", "step:s0", "mdin")).toEqual({
      type: "step_slot",
      stepId: "s0",
      kind: "mdin",
      path: "C:\\Users\\me\\run\\min.in",
    });
    expect(resolveDrop("file:C:\\Users\\me\\run\\wt.prmtop", "canvas", "prmtop")).toEqual({
      type: "pool",
      path: "C:\\Users\\me\\run\\wt.prmtop",
    });
  });

  describe("a step dragged onto another step's slot chips", () => {
    // dropCeiling normally keeps a `slot:` id away from a step drag, but resolving the pair here
    // too means the chips -- the widest row of a step card -- can never be a dead zone.
    it("reorders against the step that owns the chip", () =>
      expect(resolveDrop("step:s1", "slot:s0:mdin")).toEqual({
        type: "reorder_or_move_step", activeStepId: "s1", overStepId: "s0",
      }));
    it("is a no-op on the step's own chips", () =>
      expect(resolveDrop("step:s0", "slot:s0:mdout")).toBeNull());
    it("keeps working for a windows-path-free slot id of any kind", () =>
      expect(resolveDrop("step:s1", "slot:s0:mdcrd")).toEqual({
        type: "reorder_or_move_step", activeStepId: "s1", overStepId: "s0",
      }));
  });

  it("leaves the step/phase active branches untouched when a fileType is passed", () => {
    expect(resolveDrop("step:s1", "step:s2", "mdin")).toEqual({ type: "reorder_or_move_step", activeStepId: "s1", overStepId: "s2" });
    expect(resolveDrop("step:s1", "phase:p2", "mdin")).toEqual({ type: "move_step", stepId: "s1", phaseId: "p2" });
    expect(resolveDrop("phase:p1", "phase:p2", "mdin")).toEqual({ type: "reorder_phases", activePhaseId: "p1", overPhaseId: "p2" });
    expect(resolveDrop("step:s1", "canvas", "mdin")).toBeNull();
  });
});
