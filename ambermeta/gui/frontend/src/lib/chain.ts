import type { SimulationModel, StepModel } from "@/types";

/**
 * Every step keyed by id, so a chained step can name the step it continues from.
 *
 * The chain crosses phase boundaries — an equilibration step is routinely followed by a
 * production one — so this is built once from the whole simulation rather than from the
 * phase a step happens to live in.
 */
export type StepIndex = Map<string, { step: StepModel; phaseName: string }>;

export function buildStepIndex(sim: SimulationModel | undefined): StepIndex {
  const index: StepIndex = new Map();
  for (const phase of sim?.phases ?? []) {
    for (const step of phase.steps) index.set(step.id, { step, phaseName: phase.name });
  }
  return index;
}

/** The step `step` continues from, or null when it does not continue from one. */
export function producerOf(step: StepModel, index: StepIndex): StepModel | null {
  if (step.input_coords.source !== "step" || !step.input_coords.ref) return null;
  return index.get(step.input_coords.ref)?.step ?? null;
}

/**
 * The restart file that links `step` to the step before it in the rendered sequence, or
 * null if these two are not chained. Drives the label on the arrow between step cards, so
 * the file a run hands to the next one is visible on the edge rather than buried in a form.
 */
export function linkBetween(
  previous: StepModel | null,
  step: StepModel,
  index: StepIndex,
): string | null {
  if (!previous) return null;
  const producer = producerOf(step, index);
  if (!producer || producer.id !== previous.id) return null;
  return producer.rst ?? null;
}
