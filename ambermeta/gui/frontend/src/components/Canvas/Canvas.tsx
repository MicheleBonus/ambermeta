import { useMemo } from "react";
import { useDroppable } from "@dnd-kit/core";
import { useDocument } from "@/api/hooks";
import { buildStepIndex } from "@/lib/chain";
import { SimHeader } from "./SimHeader";
import { PhaseSection } from "./PhaseSection";

export function Canvas() {
  const { data: doc } = useDocument();
  // The scroll area is a drop target whether or not phases exist: an .mdin dropped on empty
  // space -- including below the last phase -- creates a phase to hold it.
  const { setNodeRef, isOver } = useDroppable({ id: "canvas" });
  const sim = doc?.simulation;
  // Read once here and drilled down: a second useDocument observer inside a step node would
  // refetch on mount and clobber a document that a mutation had just applied.
  const base = doc?.base_directory ?? null;
  // Built once here rather than per step: a chained step names the step it continues from,
  // and that step routinely lives in a different phase.
  const stepIndex = useMemo(() => buildStepIndex(sim), [sim]);

  if (!sim) return null;

  return (
    <div className="flex flex-col h-full">
      <SimHeader sim={sim} base={base} />
      <div
        ref={setNodeRef}
        data-droppable-id="canvas"
        className={`flex-1 overflow-auto p-3 border border-dashed ${
          isOver ? "border-accent bg-accent-subtle" : "border-transparent"
        }`}
      >
        {sim.phases.length === 0 ? (
          <div className="mt-8 text-center text-sm text-ink-muted">
            Drop an .mdin here to start a phase — or run Discover
          </div>
        ) : (
          sim.phases.map((phase) => (
            <PhaseSection key={phase.id} phase={phase} topologies={sim.topologies}
              base={base} stepIndex={stepIndex} />
          ))
        )}
      </div>
    </div>
  );
}
