import type { TopologyKind } from "@/types";

/**
 * First guess at whether a prmtop is the mass-repartitioned one, from its name.
 *
 * Only a guess — the pool chip carries a control to correct it — but it is the same guess
 * everywhere a topology can enter the pool, so dragging a file in and picking it from the
 * file browser cannot disagree about what was just added.
 */
export function guessTopologyKind(path: string): TopologyKind {
  return /hmr/i.test(path) ? "hmr" : "normal";
}
