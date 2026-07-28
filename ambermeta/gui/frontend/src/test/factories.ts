import type { InputCoordsModel, PhaseModel, StepModel } from "@/types";

/**
 * A complete `StepModel` with everything the server always sends, overridable per test.
 *
 * Hand-written step literals used to be spread across nine test files, so every new field
 * on the model broke all of them at once and tempted the next person to make the field
 * optional just to keep the fixtures compiling.
 */
export function makeStep(over: Partial<StepModel> & { id: string; name: string }): StepModel {
  return {
    topology: null,
    input_coords: { source: "starting_structure", ref: null, path: null },
    mdin: null,
    mdout: null,
    mdcrd: null,
    rst: null,
    resolved_input_coords: null,
    expected_gap_ps: null,
    gap_tolerance_ps: null,
    notes: [],
    ...over,
  };
}

/** `input_coords` for a step that continues from `ref`. */
export function continuesFrom(ref: string): InputCoordsModel {
  return { source: "step", ref, path: null };
}

export function makePhase(over: Partial<PhaseModel> & { id: string; name: string }): PhaseModel {
  return { role: "", steps: [], ...over };
}
