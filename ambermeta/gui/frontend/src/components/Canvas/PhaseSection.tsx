import { useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import { useSelection } from "@/state/selection";
import { useAssign } from "@/api/hooks";
import { Badge, ChevronDown, ChevronRight } from "@/components/common";
import type { PhaseModel, StepModel, TopologyModel } from "@/types";
import { StepNode } from "./StepNode";

const COLLAPSE_THRESHOLD = 6;

function numericBase(name: string): string {
  return name.replace(/[-_.]?\d+$/, "");
}

function groupSteps(steps: StepModel[]): { base: string; steps: StepModel[] }[] {
  const groups: { base: string; steps: StepModel[] }[] = [];
  for (const step of steps) {
    const base = numericBase(step.name);
    const last = groups[groups.length - 1];
    if (last && last.base === base) {
      last.steps.push(step);
    } else {
      groups.push({ base, steps: [step] });
    }
  }
  return groups;
}

export function PhaseSection({ phase, topologies }: { phase: PhaseModel; topologies: TopologyModel[] }) {
  const { sel, select } = useSelection();
  const assign = useAssign();
  const { setNodeRef, isOver } = useDroppable({ id: `phase:${phase.id}` });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const isSelected = sel.kind === "phase" && sel.id === phase.id;
  const groups = groupSteps(phase.steps);

  return (
    <section className={`border-l-4 rounded mb-3 bg-surface ${isOver ? "border-accent" : "border-hairline"}`}>
      <header
        ref={setNodeRef}
        className={`flex items-center gap-2 px-3 py-2 ${isSelected ? "bg-accent-subtle" : ""}`}
      >
        <button
          type="button"
          onClick={() => select("phase", phase.id)}
          className="text-sm font-medium text-ink hover:underline"
        >
          {phase.name}
        </button>
        {phase.role && <Badge tone="neutral">{phase.role}</Badge>}
        <label className="ml-auto text-xs text-ink-muted flex items-center gap-1">
          set topology ▾
          <select
            aria-label={`set topology for ${phase.name}`}
            defaultValue=""
            className="px-1 py-0.5 border border-hairline rounded bg-app text-xs text-ink"
            onChange={(e) => {
              const topoId = e.target.value;
              e.target.value = "";
              const topo = topologies.find((t) => t.id === topoId);
              if (topo) assign.mutate({ path: topo.path, target_type: "phase_topology", target_id: phase.id });
            }}
          >
            <option value="" disabled>
              Choose…
            </option>
            {topologies.map((t) => (
              <option key={t.id} value={t.id}>
                {t.path}
              </option>
            ))}
          </select>
        </label>
      </header>
      <div className="px-3 pb-2 space-y-1.5">
        {groups.map((g) =>
          g.steps.length >= COLLAPSE_THRESHOLD && !expanded.has(g.base) ? (
            <div
              key={g.base}
              className="flex items-center gap-1 px-2 py-1.5 border border-dashed border-hairline rounded text-sm text-ink-muted"
            >
              <button
                type="button"
                onClick={() => setExpanded((s) => new Set(s).add(g.base))}
                className="flex items-center gap-1"
              >
                <ChevronRight size={14} />
                {g.base} × {g.steps.length} steps
              </button>
            </div>
          ) : (
            <div key={g.base} className="space-y-1.5">
              {g.steps.length >= COLLAPSE_THRESHOLD && (
                <button
                  type="button"
                  onClick={() =>
                    setExpanded((s) => {
                      const next = new Set(s);
                      next.delete(g.base);
                      return next;
                    })
                  }
                  className="flex items-center gap-1 text-xs text-ink-muted"
                >
                  <ChevronDown size={14} />
                  {g.base} × {g.steps.length} steps
                </button>
              )}
              {g.steps.map((step) => (
                <StepNode key={step.id} step={step} topology={topologies.find((t) => t.id === step.topology)} />
              ))}
            </div>
          ),
        )}
      </div>
    </section>
  );
}
