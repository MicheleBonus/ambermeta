import { fileLabel } from "@/lib/format";
import type { FileType } from "@/types";

/** The three per-step file slots a run produces. */
export type SlotKind = "mdin" | "mdout" | "mdcrd" | "rst";

export type DropAction =
  | { type: "pool"; path: string }
  | { type: "starting"; path: string }
  | { type: "step_slot"; stepId: string; kind: SlotKind; path: string }
  | { type: "step_topology"; stepId: string; path: string }
  | { type: "phase_topology"; phaseId: string; path: string }
  | { type: "step_input_coords"; stepId: string; path: string }
  | { type: "create_step_in_phase"; phaseId: string; path: string; slot: SlotKind }
  | { type: "create_step_with_coords"; phaseId: string; path: string }
  | { type: "create_phase_with_step"; path: string; slot: SlotKind }
  | { type: "reorder_or_move_step"; activeStepId: string; overStepId: string }
  | { type: "move_step"; stepId: string; phaseId: string }
  | { type: "reorder_phases"; activePhaseId: string; overPhaseId: string }
  | { type: "rejected"; path: string; reason: string };

/** Narrows a FileType to the slot it belongs in, or null when it is not a slot-shaped file. */
function slotOf(fileType?: FileType): SlotKind | null {
  return fileType === "mdin" || fileType === "mdout" || fileType === "mdcrd" ? fileType : null;
}

/**
 * Only a .prmtop may become a topology. Assigning one rewrites `topology` on the step — or,
 * on a phase, on *every* step in it — so letting an unrecognised file fall through here turns
 * one stray drop into a silent, phase-wide overwrite. `undefined` still passes: a caller that
 * knows no type at all gets the pre-file-type behaviour.
 */
function isTopology(fileType?: FileType): boolean {
  return fileType === "prmtop" || fileType === undefined;
}

/** A drop that hit a live target but has nowhere sensible to go, so the user hears why. */
function rejected(path: string, reason: string): DropAction {
  return { type: "rejected", path, reason: `${fileLabel(path).name} ${reason}` };
}

const NOT_A_TOPOLOGY =
  "is not a topology — drop it on a step's mdin, mdout, mdcrd or rst slot instead.";

/**
 * Pure router: maps a dnd-kit (activeId, overId) pair to a DropAction. No React, no side effects.
 *
 * `fileType` refines where a dragged file lands: an .mdin dropped on a step fills that step's mdin
 * slot rather than becoming its topology, and dropping one on a phase or on empty canvas creates the
 * step (and phase) to hold it. An explicit `slot:` target stays permissive — the user aimed at it.
 * When `fileType` is omitted the routing is identical to the pre-file-type behaviour.
 *
 * A file that has no home on the target it was released over resolves to `rejected` rather than to
 * null: the target lit up under the pointer, so the drop owes the user an explanation. Null is kept
 * for the cases where nothing happened at all — no target, a self-drop, an unknown id.
 */
export function resolveDrop(activeId: string, overId: string | null, fileType?: FileType): DropAction | null {
  if (overId === null || activeId === overId) return null;

  if (activeId.startsWith("file:")) {
    // Absolute Windows paths contain a colon, so never split the tail — slice the prefix off.
    const path = activeId.slice("file:".length);
    const slot = slotOf(fileType);

    if (overId === "pool") return { type: "pool", path };
    if (overId === "starting") return { type: "starting", path };
    if (overId.startsWith("slot:")) {
      const [, stepId, kind] = overId.split(":");
      return { type: "step_slot", stepId, kind: kind as SlotKind, path };
    }
    if (overId.startsWith("step:")) {
      const stepId = overId.slice("step:".length);
      if (slot) return { type: "step_slot", stepId, kind: slot, path };
      if (fileType === "inpcrd") return { type: "step_input_coords", stepId, path };
      if (isTopology(fileType)) return { type: "step_topology", stepId, path };
      return rejected(path, NOT_A_TOPOLOGY);
    }
    if (overId.startsWith("phase:")) {
      const phaseId = overId.slice("phase:".length);
      if (slot) return { type: "create_step_in_phase", phaseId, path, slot };
      // A phase has no input coordinates of its own, but a restart file dropped on one is a
      // plain request for a step that continues from it — the same shape as an .mdin drop.
      if (fileType === "inpcrd") return { type: "create_step_with_coords", phaseId, path };
      if (isTopology(fileType)) return { type: "phase_topology", phaseId, path };
      return rejected(path, NOT_A_TOPOLOGY);
    }
    if (overId === "canvas") {
      if (slot) return { type: "create_phase_with_step", path, slot };
      if (fileType === "prmtop") return { type: "pool", path };
      if (fileType === "inpcrd") return { type: "starting", path };
      if (fileType === undefined) return null;
      return rejected(path, "is not an Amber file AmberMeta recognises — drop it on a step's slot to use it anyway.");
    }
    return null;
  }

  if (activeId.startsWith("step:")) {
    const activeStepId = activeId.slice("step:".length);
    // A slot chip is a child of its step card. Collision ranking normally hands a step drag the
    // enclosing `step:` (see dropCeiling), but resolving the pair here too means a drop released
    // on the chips can never be a silent no-op.
    const overStepId = overId.startsWith("step:")
      ? overId.slice("step:".length)
      : overId.startsWith("slot:")
        ? overId.split(":")[1]
        : null;
    if (overStepId !== null) {
      if (overStepId === activeStepId) return null;
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
    // A `step:`/`slot:` id would have to be mapped back to its owning phase, which needs the
    // document. `dropCeiling` keeps those ids away from a phase drag instead, so the enclosing
    // `phase:` is what arrives here.
    return null;
  }

  return null;
}
