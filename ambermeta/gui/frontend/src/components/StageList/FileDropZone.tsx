import { useDroppable } from "@dnd-kit/core";
import { FileIcon, FileLabel } from "@/components/common";
import { useDocument } from "@/api/hooks";
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
  return (
    <div ref={setNodeRef}
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-xs font-mono max-w-[16rem] min-w-0
        ${isOver ? "border-accent bg-accent-subtle" : "border-hairline"}`}>
      <FileIcon type={KIND_TYPE[kind]} size={14} />
      <span className="text-ink-muted shrink-0">{kind}</span>
      <span className="min-w-0 truncate">
        <FileLabel path={current} base={doc?.base_directory ?? null} />
      </span>
    </div>
  );
}
