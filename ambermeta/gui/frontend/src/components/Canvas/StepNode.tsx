import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useSelection } from "@/state/selection";
import { Badge, GripVertical } from "@/components/common";
import type { StepModel, TopologyModel } from "@/types";

function inputSourceLabel(step: StepModel): string {
  const ic = step.input_coords;
  if (ic.source === "starting_structure") return "◂ starting structure";
  if (ic.source === "step") return `◂ ${ic.ref ?? "?"}`;
  return `◂ ${ic.path ?? "?"}`;
}

const SLOT_KINDS: { kind: "mdin" | "mdout" | "mdcrd"; label: string }[] = [
  { kind: "mdin", label: "mdin" },
  { kind: "mdout", label: "mdout" },
  { kind: "mdcrd", label: "mdcrd" },
];

function FileSlot({ stepId, kind, label, value }: { stepId: string; kind: "mdin" | "mdout" | "mdcrd"; label: string; value: string | null }) {
  const { setNodeRef, isOver } = useDroppable({ id: `slot:${stepId}:${kind}` });
  return (
    <span
      ref={setNodeRef}
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-dashed border-hairline text-xs font-mono text-ink-muted ${
        isOver ? "bg-accent-subtle" : ""
      }`}
    >
      {label}: {value ? value.split("/").pop() : "—"}
    </span>
  );
}

export function StepNode({ step, topology }: { step: StepModel; topology?: TopologyModel }) {
  const { sel, select } = useSelection();
  // Same id in both registries: the node is a drop target (files / other steps land on it)
  // AND a drag source (grip handle) so it can be reordered or moved between phases.
  const { setNodeRef, isOver } = useDroppable({ id: `step:${step.id}` });
  const drag = useDraggable({ id: `step:${step.id}` });
  const isSelected = sel.kind === "step" && sel.id === step.id;
  const isHmr = topology?.kind === "hmr";

  return (
    <div
      ref={setNodeRef}
      className={`rounded border border-hairline bg-surface px-2 py-1.5 space-y-1 ${
        isSelected ? "bg-accent-subtle" : ""
      } ${isOver ? "border-accent" : ""} ${drag.isDragging ? "opacity-50" : ""}`}
    >
      <div className="flex items-center gap-1.5">
        <span
          ref={drag.setNodeRef}
          {...drag.attributes}
          {...drag.listeners}
          aria-label={`drag step ${step.name}`}
          className="cursor-grab text-ink-muted shrink-0"
        >
          <GripVertical size={14} />
        </span>
        <button
          type="button"
          onClick={() => select("step", step.id)}
          className="text-left text-sm text-ink hover:underline"
        >
          {step.name}
        </button>
      </div>
      <div className="flex items-center gap-1 flex-wrap">
        <span className={`font-mono text-xs ${isHmr ? "text-accent" : "text-ink-secondary"}`}>
          ▸ {topology ? topology.path : "no topology"}
        </span>
        {isHmr && <Badge tone="neutral">HMR</Badge>}
      </div>
      <div className="font-mono text-xs text-ink-muted">{inputSourceLabel(step)}</div>
      <div className="flex items-center gap-1.5 flex-wrap">
        {SLOT_KINDS.map((s) => (
          <FileSlot key={s.kind} stepId={step.id} kind={s.kind} label={s.label} value={step[s.kind]} />
        ))}
      </div>
    </div>
  );
}
