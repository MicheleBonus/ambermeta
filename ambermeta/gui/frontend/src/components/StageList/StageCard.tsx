import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Badge } from "@/components/common";
import { FileDropZone } from "./FileDropZone";
import { roleLabel, formatPs } from "@/lib/format";
import type { StageModel } from "@/types";

const KINDS = ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"] as const;

export function StageCard(
  { stage, index, isSelected, onSelect }:
  { stage: StageModel; index: number; isSelected: boolean; onSelect: (e: React.MouseEvent) => void }
) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: stage.id });
  const style = { transform: CSS.Transform.toString(transform), transition };
  const hasGap = stage.expected_gap_ps != null && stage.expected_gap_ps > 0;
  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}
      onClick={onSelect}
      className={`border-b border-hairline px-3 py-2 cursor-pointer
        ${isSelected ? "bg-accent-subtle" : "hover:bg-app"}`}>
      <div className="flex items-center gap-2">
        <span className="text-xs text-ink-muted w-6 tabular-nums">{index + 1}</span>
        <span className="font-medium truncate flex-1">{stage.name}</span>
        <Badge>{roleLabel(stage.role)}</Badge>
        {hasGap && (
          <span className="text-warning text-xs">+{formatPs(stage.expected_gap_ps)} gap</span>
        )}
      </div>
      <div className="flex flex-wrap gap-1 mt-1 pl-8">
        {KINDS.map((k) => (
          <FileDropZone key={k} stageId={stage.id} kind={k} current={stage[k]} />
        ))}
      </div>
    </div>
  );
}
