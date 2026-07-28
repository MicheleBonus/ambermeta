import { it, expect } from "vitest";
import { buildStepIndex, linkBetween, producerOf } from "./chain";
import { makeStep } from "@/test/factories";
import type { SimulationModel } from "@/types";

const min = makeStep({ id: "s0", name: "01_min", rst: "equil/01_min.rst" });
const nvt = makeStep({
  id: "s1", name: "02_nvt", rst: "equil/02_nvt.rst",
  input_coords: { source: "step", ref: "s0", path: null },
});
// Deliberately in a second phase: an equilibration run routinely hands off to production.
const prod = makeStep({
  id: "s2", name: "prod_0001",
  input_coords: { source: "step", ref: "s1", path: null },
});

const sim: SimulationModel = {
  version: 2, topologies: [], starting_structure: "cryst/wt.crd",
  phases: [
    { id: "p0", name: "Equil", role: "equilibration", steps: [min, nvt] },
    { id: "p1", name: "Prod", role: "production", steps: [prod] },
  ],
};
const index = buildStepIndex(sim);

it("finds the step a chained step continues from, across phases", () => {
  expect(producerOf(nvt, index)?.name).toBe("01_min");
  expect(producerOf(prod, index)?.name).toBe("02_nvt");
});

it("has no producer for a step that reads the starting structure or a plain path", () => {
  expect(producerOf(min, index)).toBeNull();
  expect(producerOf(
    makeStep({ id: "x", name: "x", input_coords: { source: "path", ref: null, path: "a.rst" } }),
    index,
  )).toBeNull();
});

it("returns null rather than a wrong step when the ref is dead", () => {
  const orphan = makeStep({
    id: "x", name: "x", input_coords: { source: "step", ref: "gone", path: null },
  });
  expect(producerOf(orphan, index)).toBeNull();
});

it("names the restart that joins two adjacent steps", () => {
  expect(linkBetween(min, nvt, index)).toBe("equil/01_min.rst");
});

it("draws no link between neighbours that are not actually chained", () => {
  // Adjacent on screen, but nvt does not continue from prod.
  expect(linkBetween(prod, nvt, index)).toBeNull();
  expect(linkBetween(null, nvt, index)).toBeNull();
});

it("draws no link when the producer never named a restart", () => {
  const bare = makeStep({ id: "s9", name: "00_setup" });
  const after = makeStep({
    id: "s10", name: "01_min", input_coords: { source: "step", ref: "s9", path: null },
  });
  const idx = buildStepIndex({
    version: 2, topologies: [], starting_structure: null,
    phases: [{ id: "p", name: "P", role: "", steps: [bare, after] }],
  });
  expect(linkBetween(bare, after, idx)).toBeNull();
});
