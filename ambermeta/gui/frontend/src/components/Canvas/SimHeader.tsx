import { useDroppable } from "@dnd-kit/core";
import { useSelection } from "@/state/selection";
import { Badge, Plus } from "@/components/common";
import type { SimulationModel } from "@/types";

export function SimHeader({ sim }: { sim: SimulationModel }) {
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
          <span
            key={t.id}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded bg-app border border-hairline font-mono text-xs ${
              t.kind === "hmr" ? "text-accent" : "text-ink"
            }`}
          >
            {t.path}
            <Badge tone="neutral">{t.kind === "hmr" ? "HMR" : "normal"}</Badge>
          </span>
        ))}
        <span className="inline-flex items-center gap-1 text-xs text-ink-muted">
          <Plus size={12} /> add prmtop
        </span>
      </div>

      <div
        ref={setStartRef}
        className={`p-2 rounded border border-dashed border-hairline font-mono text-xs text-ink-secondary ${
          startOver ? "bg-accent-subtle" : ""
        }`}
      >
        {sim.starting_structure ? `starting structure: ${sim.starting_structure}` : "drop starting structure here"}
      </div>
    </div>
  );
}
