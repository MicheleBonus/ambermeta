import { useDroppable } from "@dnd-kit/core";
import { FileIcon } from "@/components/common";
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
  return (
    <div ref={setNodeRef}
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-xs font-mono
        ${isOver ? "border-accent bg-accent-subtle" : "border-hairline"}`}>
      <FileIcon type={KIND_TYPE[kind]} />
      <span className="text-ink-muted">{kind}</span>
      <span className="truncate text-ink">{current ?? "—"}</span>
    </div>
  );
}
