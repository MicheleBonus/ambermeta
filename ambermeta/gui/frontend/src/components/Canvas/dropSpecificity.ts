import { pointerWithin, rectIntersection, type CollisionDetection } from "@dnd-kit/core";

/**
 * Collision ranking for the Canvas' nested droppables (canvas > phase > step > slot).
 *
 * dnd-kit's default `rectIntersection` resolves ties by the LARGEST intersecting rectangle, so an
 * enclosing phase section would swallow a drop the user aimed at a step or at one of its slots.
 * Ranking by nesting depth instead makes the innermost target win.
 */

/** Higher is more specific: `slot:` > `step:` > `phase:` > `pool`/`starting` > `canvas` > anything else. */
export function dropRank(id: string): number {
  if (id.startsWith("slot:")) return 5;
  if (id.startsWith("step:")) return 4;
  if (id.startsWith("phase:")) return 3;
  if (id === "pool" || id === "starting") return 2;
  if (id === "canvas") return 1;
  return 0;
}

/** Picks the innermost of a set of dnd-kit collisions. First one wins on a tie; null when empty. */
export function mostSpecific<T extends { id: string | number }>(collisions: T[]): T | null {
  let best: T | null = null;
  let bestRank = -Infinity;
  for (const collision of collisions) {
    const rank = dropRank(String(collision.id));
    if (rank > bestRank) {
      best = collision;
      bestRank = rank;
    }
  }
  return best;
}

/**
 * The deepest droppable rank a given draggable can act on.
 *
 * Innermost-wins is only right for what the dragged thing can actually accept. A step card's slot
 * chips are a full-width strip across the bottom of the card, and a phase section is mostly step
 * cards — so ranking blind hands a step drag `slot:s0:mdin` and a phase drag `step:s0`, neither of
 * which `resolveDrop` can route, and the reorder dies with no mutation and no feedback. Capping the
 * rank first lets the enclosing target win: `pointerWithin` always reports every rect the pointer is
 * inside, so the phase under the step (and the step under the chip) is already in the list.
 */
export function dropCeiling(activeId: string): number {
  if (activeId.startsWith("phase:")) return 3; // a phase only reorders against another phase
  if (activeId.startsWith("step:")) return 4; // a step lands on another step, or on a phase
  return 5; // a file is the only thing that can fill a single slot
}

/**
 * The canvas' collision strategy: track the pointer first (what the user is actually aiming at),
 * fall back to the dragged rectangle when the pointer is inside no target at all (it can sit in a
 * gutter between two droppables mid-drag, where the dragged rect is the only signal left), and keep
 * the innermost hit the active draggable can accept.
 */
export const canvasCollisionDetection: CollisionDetection = (args) => {
  const ceiling = dropCeiling(String(args.active.id));
  const accepted = <T extends { id: string | number }>(collisions: T[]) =>
    collisions.filter((c) => dropRank(String(c.id)) <= ceiling);

  const underPointer = accepted(pointerWithin(args));
  const hit = mostSpecific(underPointer.length > 0 ? underPointer : accepted(rectIntersection(args)));
  return hit ? [hit] : [];
};
