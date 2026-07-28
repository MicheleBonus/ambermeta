import { FileIcon, FileLabel } from "@/components/common";
import type { FileType, SimulationModel } from "@/types";

/** What is currently being dragged, as read off the draggable's dnd-kit data. */
export interface ActiveDrag {
  id: string;
  fileType?: FileType;
  path?: string;
}

/** The name of a dragged `step:`/`phase:` node, for the drag overlay. */
function nodeName(id: string, sim?: SimulationModel): string {
  if (id.startsWith("phase:")) {
    const phaseId = id.slice("phase:".length);
    return sim?.phases.find((p) => p.id === phaseId)?.name ?? "phase";
  }
  const stepId = id.slice("step:".length);
  for (const phase of sim?.phases ?? []) {
    const step = phase.steps.find((s) => s.id === stepId);
    if (step) return step.name;
  }
  return "step";
}

/** The chip that follows the cursor during a drag, so a drag never feels dead. */
export function DragChip({
  drag,
  sim,
  base,
}: {
  drag: ActiveDrag;
  sim?: SimulationModel;
  base: string | null;
}) {
  const chip =
    "inline-flex items-center gap-1.5 px-2 py-1 rounded border border-accent bg-surface shadow-lg text-sm";
  if (!drag.id.startsWith("file:")) {
    return <div className={`${chip} text-ink`}>{nodeName(drag.id, sim)}</div>;
  }
  return (
    <div className={`${chip} font-mono text-ink`}>
      <FileIcon type={drag.fileType ?? "other"} className="w-4 h-4 shrink-0" />
      <FileLabel path={drag.path ?? drag.id.slice("file:".length)} base={base} />
    </div>
  );
}
