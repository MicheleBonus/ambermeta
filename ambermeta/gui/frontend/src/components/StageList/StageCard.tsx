import { useState } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { FileDropZone } from "./FileDropZone";
import { roleLabel, formatPs } from "@/lib/format";
import { useUpdateStage } from "@/api/hooks";
import { STAGE_ROLE_CONFIG } from "@/types";
import type { StageModel, StageRole } from "@/types";

const KINDS = ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"] as const;
const ROLE_OPTIONS: StageRole[] = ["", "minimization", "heating", "equilibration", "production"];

export function StageCard(
  { stage, index, isSelected, onSelect }:
  { stage: StageModel; index: number; isSelected: boolean; onSelect: (e: React.MouseEvent) => void }
) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: stage.id });
  const style = { transform: CSS.Transform.toString(transform), transition };
  const hasGap = stage.expected_gap_ps != null && stage.expected_gap_ps > 0;
  const update = useUpdateStage();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(stage.name);

  const commitName = () => {
    setEditing(false);
    if (name !== stage.name) update.mutate({ id: stage.id, update: { name } });
  };

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}
      onClick={onSelect}
      className={`border-b border-hairline px-3 py-2 cursor-pointer
        ${isSelected ? "bg-accent-subtle" : "hover:bg-app"}`}>
      <div className="flex items-center gap-2">
        <span className="text-xs text-ink-muted w-6 tabular-nums">{index + 1}</span>
        {editing ? (
          <input autoFocus aria-label="Rename stage" value={name}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setName(e.target.value)}
            onBlur={commitName}
            onKeyDown={(e) => { if (e.key === "Enter") commitName(); if (e.key === "Escape") { setName(stage.name); setEditing(false); } }}
            className="font-medium flex-1 min-w-0 px-1 border border-hairline rounded bg-app" />
        ) : (
          <span className="font-medium truncate flex-1"
            onDoubleClick={(e) => { e.stopPropagation(); setName(stage.name); setEditing(true); }}>
            {stage.name}
          </span>
        )}
        <select aria-label="stage role" value={stage.role}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => update.mutate({ id: stage.id, update: { role: e.target.value as StageRole } })}
          className="text-xs border border-hairline rounded bg-surface px-1 py-0.5">
          {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{STAGE_ROLE_CONFIG[r]?.label ?? roleLabel(r)}</option>)}
        </select>
        {hasGap && (
          <span className="text-warning text-xs">+{formatPs(stage.expected_gap_ps)} gap</span>
        )}
      </div>
      <div className="flex flex-wrap gap-1 mt-1 pl-8" onClick={(e) => e.stopPropagation()}>
        {KINDS.map((k) => (
          <FileDropZone key={k} stageId={stage.id} kind={k} current={stage[k]} />
        ))}
      </div>
    </div>
  );
}
