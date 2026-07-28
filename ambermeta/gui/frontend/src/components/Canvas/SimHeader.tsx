import { useDroppable } from "@dnd-kit/core";
import { useSelection } from "@/state/selection";
import { Badge, FileLabel, Plus } from "@/components/common";
import type { SimulationModel } from "@/types";

export function SimHeader({
  sim,
  base,
}: {
  sim: SimulationModel;
  /** Document base directory, so pooled topologies read as labels rather than absolute paths. */
  base: string | null;
}) {
  const { sel, select } = useSelection();
  const { setNodeRef: setPoolRef, isOver: poolOver } = useDroppable({ id: "pool" });
  const { setNodeRef: setStartRef, isOver: startOver } = useDroppable({ id: "starting" });
  const isSimSelected = sel.kind === "sim";

  return (
    <div className="bg-surface border-b border-hairline p-3 space-y-2">
      <button
        type="button"
        onClick={() => select("sim", null)}
        className={`text-sm font-medium ${isSimSelected ? "text-accent" : "text-ink"}`}
      >
        Simulation
      </button>

      <div
        ref={setPoolRef}
        className={`flex flex-wrap gap-2 items-center p-2 rounded border border-dashed border-hairline ${
          poolOver ? "bg-accent-subtle" : ""
        }`}
      >
        {sim.topologies.map((t) => (
          // min-w-0 + max-w-full: this header sits outside the canvas' scroll container, so an
          // absolute path — one unbreakable token — would spill straight out of the pane.
          <span
            key={t.id}
            className={`inline-flex min-w-0 max-w-full items-center gap-1 px-2 py-1 rounded bg-app border border-hairline font-mono text-xs ${
              t.kind === "hmr" ? "text-accent" : "text-ink"
            }`}
          >
            <FileLabel path={t.path} base={base} />
            <Badge tone="neutral">{t.kind === "hmr" ? "HMR" : "normal"}</Badge>
          </span>
        ))}
        <span className="inline-flex items-center gap-1 text-xs text-ink-muted">
          <Plus size={12} /> add prmtop
        </span>
      </div>

      <div
        ref={setStartRef}
        className={`flex min-w-0 items-baseline gap-1 p-2 rounded border border-dashed border-hairline font-mono text-xs text-ink-secondary ${
          startOver ? "bg-accent-subtle" : ""
        }`}
      >
        {sim.starting_structure ? (
          <>
            <span className="shrink-0">starting structure:</span>
            <FileLabel path={sim.starting_structure} base={base} />
          </>
        ) : (
          "drop starting structure here"
        )}
      </div>
    </div>
  );
}
