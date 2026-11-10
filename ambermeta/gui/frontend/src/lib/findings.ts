import type { Suggestion } from "@/types";

/** The suggestion kinds that are problems (what `--strict` fails on), as opposed to the
 *  `[applied]` inferences. The same list as `ambermeta.acknowledgements.PROBLEM_KINDS`. */
export const PROBLEM_KINDS = new Set([
  "continuity_gap", "missing_run", "step_check", "unfinished_run", "input_mismatch",
]);

/** The text a finding is known by: the `title: evidence` line `validate` prints. An
 *  acknowledgement names its finding by exactly this, so it must match
 *  `ambermeta.acknowledgements.finding_text` character for character. */
export function findingText(s: Pick<Suggestion, "title" | "evidence">): string {
  return `${s.title}: ${s.evidence}`;
}

/** A problem the user can settle with a note: not an inference, not already settled. */
export function canAcknowledge(s: Suggestion): boolean {
  return s.severity === "needs_you" && PROBLEM_KINDS.has(s.kind) && !s.acknowledged;
}
