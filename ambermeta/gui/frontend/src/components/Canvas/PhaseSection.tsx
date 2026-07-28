import { useState } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useSelection } from "@/state/selection";
import { useAssign, useCreateStep, useDeletePhase, useUpdatePhase } from "@/api/hooks";
import { ChevronDown, ChevronRight, GripVertical, Plus, Trash2 } from "@/components/common";
import { ROLE_OPTIONS } from "@/lib/roles";
import { useInlineRename } from "@/lib/useInlineRename";
import type { PhaseModel, StageRole, StepModel, Suggestion, TopologyModel } from "@/types";
import { StepNode } from "./StepNode";
import { ContinuityArrow, MissingRunGhost, parseGap } from "./ContinuityArrow";
import { useSuggestions } from "@/components/Suggestions/suggestionsContext";

const COLLAPSE_THRESHOLD = 6;

function numericBase(name: string): string {
  return name.replace(/[-_.]?\d+$/, "");
}

function stepNumber(name: string): number {
  const m = name.match(/(\d+)$/);
  return m ? parseInt(m[1], 10) : Number.POSITIVE_INFINITY;
}

/** Width (digit count) of the trailing numeric suffix, e.g. "prod_0001" -> 4. */
function numWidth(name: string): number {
  const m = name.match(/(\d+)$/);
  return m ? m[1].length : 0;
}

/**
 * Consecutive steps sharing a numeric base become one collapsible group. Each group carries the
 * id of its first step: `base` is not unique — two non-adjacent runs can share one ("step", "min",
 * "step") — so keying React children or the collapse set by it collides, and one group's toggle
 * would expand the other.
 */
function groupSteps(steps: StepModel[]): { id: string; base: string; steps: StepModel[] }[] {
  const groups: { id: string; base: string; steps: StepModel[] }[] = [];
  for (const step of steps) {
    const base = numericBase(step.name);
    const last = groups[groups.length - 1];
    if (last && last.base === base) {
      last.steps.push(step);
    } else {
      groups.push({ id: step.id, base, steps: [step] });
    }
  }
  return groups;
}

type GhostItem = { id: string; name: string; num: number };

/** Ghost nodes for a numbered-sequence group, derived from the structured
 * `base`/`missing` fields of missing_run suggestions (no free-text parsing). */
function ghostsForBase(base: string, width: number, suggestions: Suggestion[]): GhostItem[] {
  const out: GhostItem[] = [];
  for (const s of suggestions) {
    if (s.kind !== "missing_run" || s.base !== base || !s.missing) continue;
    for (const idx of s.missing) {
      out.push({ id: `${s.id}:${idx}`, name: `${base}_${String(idx).padStart(width, "0")}`, num: idx });
    }
  }
  return out;
}

/** The continuity-gap suggestion (if any) that precedes step `stepId`, and its
 * parsed magnitude label (e.g. "20 ps"). */
function gapForStep(stepId: string, suggestions: Suggestion[]): string | null {
  const s = suggestions.find((s) => s.kind === "continuity_gap" && s.step_id === stepId);
  if (!s) return null;
  return parseGap(s.evidence) ?? parseGap(s.title);
}

type SequenceItem =
  | { kind: "step"; num: number; step: StepModel }
  | { kind: "ghost"; num: number; id: string; name: string };

export function PhaseSection({
  phase,
  topologies,
  base,
}: {
  phase: PhaseModel;
  topologies: TopologyModel[];
  /** Document base directory, drilled down so step labels can relativize paths. */
  base: string | null;
}) {
  const { sel, select } = useSelection();
  const assign = useAssign();
  const updatePhase = useUpdatePhase();
  const createStep = useCreateStep();
  const deletePhase = useDeletePhase();
  // Drop target (files / steps land on it) AND drag source (grip) so phases can be reordered.
  const { setNodeRef, isOver } = useDroppable({ id: `phase:${phase.id}` });
  const drag = useDraggable({ id: `phase:${phase.id}` });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const rename = useInlineRename(phase.name, (name) => updatePhase.mutate({ id: phase.id, body: { name } }));
  const isSelected = sel.kind === "phase" && sel.id === phase.id;
  const groups = groupSteps(phase.steps);
  const suggestions = useSuggestions();

  return (
    // The droppable covers the whole section -- header AND step list -- so a file dropped
    // anywhere on the phase lands on it. The grip below keeps the section draggable.
    <section
      ref={setNodeRef}
      data-droppable-id={`phase:${phase.id}`}
      className={`border-l-4 rounded mb-3 ${isOver ? "border-accent bg-accent-subtle" : "border-hairline bg-surface"} ${
        drag.isDragging ? "opacity-50" : ""
      }`}
    >
      {/* Wraps rather than overflows: the header now carries a name, a role, a topology
          chooser and two actions. */}
      <header className={`flex flex-wrap items-center gap-2 px-3 py-2 ${isSelected ? "bg-accent-subtle" : ""}`}>
        <span
          ref={drag.setNodeRef}
          {...drag.attributes}
          {...drag.listeners}
          aria-label={`drag phase ${phase.name}`}
          className="cursor-grab text-ink-muted shrink-0"
        >
          <GripVertical size={14} />
        </span>
        {rename.editing ? (
          <input
            autoFocus
            aria-label={`rename phase ${phase.name}`}
            value={rename.value}
            onChange={(e) => rename.change(e.target.value)}
            onKeyDown={rename.keyDown}
            onBlur={rename.blur}
            className="min-w-0 px-1 py-0.5 border border-accent rounded bg-app text-sm font-medium text-ink"
          />
        ) : (
          // F2 as well as double-click: a double-click is unreachable from the keyboard, which
          // left renaming impossible without a mouse. Enter/Space still select, as for any button.
          <button
            type="button"
            onClick={() => select("phase", phase.id)}
            onDoubleClick={rename.start}
            onKeyDown={(e) => {
              if (e.key === "F2") {
                e.preventDefault();
                rename.start();
              }
            }}
            aria-keyshortcuts="F2"
            title="Press F2 or double-click to rename"
            className="text-sm font-medium text-ink hover:underline"
          >
            {phase.name}
          </button>
        )}
        {/* Controlled off the document, unlike the topology chooser below: this one
            reports the phase's current role and is the one place the role is shown --
            a Badge beside it would only repeat the value the select already displays. */}
        <label className="ml-auto text-xs text-ink-muted flex items-center gap-1">
          role
          <select
            aria-label={`set role for ${phase.name}`}
            value={phase.role}
            className="px-1 py-0.5 border border-hairline rounded bg-app text-xs text-ink"
            onChange={(e) => updatePhase.mutate({ id: phase.id, body: { role: e.target.value as StageRole } })}
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r.value || "none"} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-ink-muted flex items-center gap-1">
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
        <button
          type="button"
          aria-label={`add step to ${phase.name}`}
          title="Add a step"
          // Numbered, so two clicks do not leave two indistinguishable steps both called "step".
          onClick={() => createStep.mutate({ phaseId: phase.id, body: { name: `step ${phase.steps.length + 1}` } })}
          className="shrink-0 text-ink-muted hover:text-ink"
        >
          <Plus size={14} />
        </button>
        <button
          type="button"
          aria-label={`delete phase ${phase.name}`}
          title="Delete this phase"
          onClick={() => {
            if (window.confirm(`Delete phase "${phase.name}" and its ${phase.steps.length} step(s)?`)) {
              deletePhase.mutate({ id: phase.id });
            }
          }}
          className="shrink-0 text-ink-muted hover:text-error"
        >
          <Trash2 size={14} />
        </button>
      </header>
      <div className="px-3 pb-2 space-y-1.5">
        {groups.map((g) =>
          g.steps.length >= COLLAPSE_THRESHOLD && !expanded.has(g.id) ? (
            <div
              key={g.id}
              className="flex items-center gap-1 px-2 py-1.5 border border-dashed border-hairline rounded text-sm text-ink-muted"
            >
              <button
                type="button"
                onClick={() => setExpanded((s) => new Set(s).add(g.id))}
                className="flex items-center gap-1"
              >
                <ChevronRight size={14} />
                {g.base} × {g.steps.length} steps
              </button>
            </div>
          ) : (
            <div key={g.id} className="space-y-1.5">
              {g.steps.length >= COLLAPSE_THRESHOLD && (
                <button
                  type="button"
                  onClick={() =>
                    setExpanded((s) => {
                      const next = new Set(s);
                      next.delete(g.id);
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
                const width = Math.max(0, ...g.steps.map((s) => numWidth(s.name)));
                const ghosts = ghostsForBase(g.base, width, suggestions);
                const items: SequenceItem[] = [
                  ...g.steps.map((step): SequenceItem => ({ kind: "step", num: stepNumber(step.name), step })),
                  ...ghosts.map((gh): SequenceItem => ({ kind: "ghost", num: gh.num, id: gh.id, name: gh.name })),
                ].sort((a, b) => a.num - b.num);
                return items.map((item, i) => (
                  <div key={item.kind === "step" ? item.step.id : `ghost:${item.id}`}>
                    {i > 0 && (
                      <ContinuityArrow gap={item.kind === "step" ? gapForStep(item.step.id, suggestions) : null} />
                    )}
                    {item.kind === "step" ? (
                      <StepNode
                        step={item.step}
                        topology={topologies.find((t) => t.id === item.step.topology)}
                        base={base}
                      />
                    ) : (
                      <MissingRunGhost name={item.name} />
                    )}
                  </div>
                ));
              })()}
            </div>
          ),
        )}
        {/* Makes the section-wide drop target discoverable: the whole phase accepts the file,
            this row is just where the affordance is spelled out. */}
        <div className="px-2 py-1.5 rounded border border-dashed border-hairline text-center text-xs text-ink-muted">
          drop a file here to add a step
        </div>
      </div>
    </section>
  );
}
