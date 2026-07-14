export type DropAction =
  | { type: "pool"; path: string }
  | { type: "starting"; path: string }
  | { type: "step_slot"; stepId: string; kind: "mdin" | "mdout" | "mdcrd"; path: string }
  | { type: "step_topology"; stepId: string; path: string }
  | { type: "phase_topology"; phaseId: string; path: string }
  | { type: "reorder_or_move_step"; activeStepId: string; overStepId: string }
  | { type: "move_step"; stepId: string; phaseId: string }
  | { type: "reorder_phases"; activePhaseId: string; overPhaseId: string };

/** Pure router: maps a dnd-kit (activeId, overId) pair to a DropAction. No React, no side effects. */
export function resolveDrop(activeId: string, overId: string | null): DropAction | null {
  if (overId === null || activeId === overId) return null;

  if (activeId.startsWith("file:")) {
    const path = activeId.slice("file:".length);
    if (overId === "pool") return { type: "pool", path };
    if (overId === "starting") return { type: "starting", path };
    if (overId.startsWith("slot:")) {
      const [, stepId, kind] = overId.split(":");
      return { type: "step_slot", stepId, kind: kind as "mdin" | "mdout" | "mdcrd", path };
    }
    if (overId.startsWith("step:")) {
      const stepId = overId.slice("step:".length);
      return { type: "step_topology", stepId, path };
    }
    if (overId.startsWith("phase:")) {
      const phaseId = overId.slice("phase:".length);
      return { type: "phase_topology", phaseId, path };
    }
    return null;
  }

  if (activeId.startsWith("step:")) {
    const activeStepId = activeId.slice("step:".length);
    if (overId.startsWith("step:")) {
      const overStepId = overId.slice("step:".length);
      return { type: "reorder_or_move_step", activeStepId, overStepId };
    }
    if (overId.startsWith("phase:")) {
      const phaseId = overId.slice("phase:".length);
      return { type: "move_step", stepId: activeStepId, phaseId };
    }
    return null;
  }

  if (activeId.startsWith("phase:")) {
    const activePhaseId = activeId.slice("phase:".length);
    if (overId.startsWith("phase:")) {
      const overPhaseId = overId.slice("phase:".length);
      return { type: "reorder_phases", activePhaseId, overPhaseId };
    }
    return null;
  }

  return null;
}
