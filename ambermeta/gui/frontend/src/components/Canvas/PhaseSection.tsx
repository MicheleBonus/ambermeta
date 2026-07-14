import { useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import { useSelection } from "@/state/selection";
import { useAssign } from "@/api/hooks";
import { Badge, ChevronDown, ChevronRight } from "@/components/common";
import type { PhaseModel, StepModel, Suggestion, TopologyModel } from "@/types";
import { StepNode } from "./StepNode";
import { ContinuityArrow, MissingRunGhost, parseGap } from "./ContinuityArrow";
import { useSuggestions } from "./Canvas";

const COLLAPSE_THRESHOLD = 6;

function numericBase(name: string): string {
  return name.replace(/[-_.]?\d+$/, "");
}

function stepNumber(name: string): number {
  const m = name.match(/(\d+)$/);
  return m ? parseInt(m[1], 10) : Number.POSITIVE_INFINITY;
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

/** Best-effort extraction of a run/step name (e.g. "prod_0002") from suggestion text. */
function extractRunName(text: string): string | null {
  const m = text.match(/\b([A-Za-z][\w.-]*\d)\b/);
  return m ? m[1] : null;
}

type GhostItem = { id: string; name: string; num: number };

function ghostsForBase(base: string, suggestions: Suggestion[]): GhostItem[] {
  const out: GhostItem[] = [];
  for (const s of suggestions) {
    if (s.kind !== "missing_run") continue;
    const name = extractRunName(s.title) ?? extractRunName(s.evidence);
    if (!name || numericBase(name) !== base) continue;
    out.push({ id: s.id, name, num: stepNumber(name) });
  }
  return out;
}

type SequenceItem =
  | { kind: "step"; num: number; step: StepModel }
  | { kind: "ghost"; num: number; id: string; name: string };

export function PhaseSection({ phase, topologies }: { phase: PhaseModel; topologies: TopologyModel[] }) {
  const { sel, select } = useSelection();
  const assign = useAssign();
  const { setNodeRef, isOver } = useDroppable({ id: `phase:${phase.id}` });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const isSelected = sel.kind === "phase" && sel.id === phase.id;
  const groups = groupSteps(phase.steps);
  const suggestions = useSuggestions();
  const gapSuggestion = suggestions.find((s) => s.kind === "continuity_gap");
  const gapLabel = gapSuggestion ? (parseGap(gapSuggestion.evidence) ?? parseGap(gapSuggestion.title)) : null;

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
              {(() => {
                const ghosts = ghostsForBase(g.base, suggestions);
                const items: SequenceItem[] = [
                  ...g.steps.map((step): SequenceItem => ({ kind: "step", num: stepNumber(step.name), step })),
                  ...ghosts.map((gh): SequenceItem => ({ kind: "ghost", num: gh.num, id: gh.id, name: gh.name })),
                ].sort((a, b) => a.num - b.num);
                return items.map((item, i) => (
                  <div key={item.kind === "step" ? item.step.id : `ghost:${item.id}`}>
                    {i > 0 && <ContinuityArrow gap={gapLabel} />}
                    {item.kind === "step" ? (
                      <StepNode step={item.step} topology={topologies.find((t) => t.id === item.step.topology)} />
                    ) : (
                      <MissingRunGhost name={item.name} />
                    )}
                  </div>
                ));
              })()}
            </div>
          ),
        )}
      </div>
    </section>
  );
}
