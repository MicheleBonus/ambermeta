import type { StageRole } from "@/types";

/**
 * The stage-role vocabulary, shared by every control that offers it — the
 * inspector's assign flow and the phase header on the canvas — so the two can
 * never drift into offering different roles or different labels for them.
 */
export const ROLE_OPTIONS: { value: StageRole; label: string }[] = [
  { value: "minimization", label: "Minimization" },
  { value: "heating", label: "Heating" },
  { value: "equilibration", label: "Equilibration" },
  { value: "production", label: "Production" },
  { value: "", label: "Unassigned" },
];
