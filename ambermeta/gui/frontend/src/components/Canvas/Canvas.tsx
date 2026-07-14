import { useDocument } from "@/api/hooks";
import { SimHeader } from "./SimHeader";
import { PhaseSection } from "./PhaseSection";

export function Canvas() {
  const { data: doc } = useDocument();
  const sim = doc?.simulation;

  if (!sim) return null;

  return (
    <div className="flex flex-col h-full">
      <SimHeader sim={sim} />
      <div className="flex-1 overflow-auto p-3">
        {sim.phases.length === 0 ? (
          <div className="mt-8 text-center text-sm text-ink-muted">Discover or drop files to start</div>
        ) : (
          sim.phases.map((phase) => <PhaseSection key={phase.id} phase={phase} topologies={sim.topologies} />)
        )}
      </div>
    </div>
  );
}
