import { useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import { FileIcon, FileLabel } from "@/components/common";
import { FilePicker } from "@/components/FilePicker";
import { useDocument, useUpdateStage } from "@/api/hooks";
import { relativizePath } from "@/lib/format";
import type { FileType } from "@/types";

interface Props {
  stageId: string;
  kind: "prmtop" | "mdin" | "mdout" | "mdcrd" | "inpcrd";
  current: string | null;
}
const KIND_TYPE: Record<Props["kind"], FileType> = {
  prmtop: "prmtop", mdin: "mdin", mdout: "mdout", mdcrd: "mdcrd", inpcrd: "inpcrd",
};

export function FileDropZone({ stageId, kind, current }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: `slot:${stageId}:${kind}` });
  const { data: doc } = useDocument();
  const update = useUpdateStage();
  const [open, setOpen] = useState(false);
  const base = doc?.base_directory ?? null;
  const commit = (path: string | null) =>
    update.mutate({ id: stageId, update: { files: { [kind]: path === null ? "" : relativizePath(path, base) } } });
  return (
    <div ref={setNodeRef}
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-xs font-mono max-w-[16rem] min-w-0
        ${isOver ? "border-accent bg-accent-subtle" : "border-hairline"}`}>
      <FileIcon type={KIND_TYPE[kind]} size={14} />
      <button type="button" aria-label={`assign ${kind}`} onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        className="flex items-center gap-1 min-w-0">
        <span className="text-ink-muted shrink-0">{kind}</span>
        <span className="min-w-0 truncate"><FileLabel path={current} base={base} /></span>
      </button>
      {current && (
        <button type="button" aria-label={`clear ${kind}`} className="text-ink-muted shrink-0"
          onClick={(e) => { e.stopPropagation(); commit(null); }}>×</button>
      )}
      {open && (
        <FilePicker open={open} mode="open" title={`Pick ${kind} file`}
          onClose={() => setOpen(false)}
          onPick={({ path }) => { commit(path); setOpen(false); }} />
      )}
    </div>
  );
}
