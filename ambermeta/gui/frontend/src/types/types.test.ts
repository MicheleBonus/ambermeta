// src/types/types.test.ts
import { describe, it, expect } from "vitest";
import type { DocumentResponse, SimulationModel, AssignRequest } from "@/types";

it("document response nests a simulation", () => {
  const doc: DocumentResponse = {
    base_directory: "/w", manifest_path: null, dirty: false, can_undo: false, can_redo: false,
    settings: { auto_link_restarts: true, strict_validation: true, allow_gaps: false, use_relative_paths: true },
    simulation: { version: 2, topologies: [], starting_structure: null, phases: [] },
  };
  expect(doc.simulation.version).toBe(2);
  const sim: SimulationModel = doc.simulation;
  expect(sim.phases).toEqual([]);
  const a: AssignRequest = { path: "wt.prmtop", target_type: "pool", kind: "normal" };
  expect(a.target_type).toBe("pool");
});
