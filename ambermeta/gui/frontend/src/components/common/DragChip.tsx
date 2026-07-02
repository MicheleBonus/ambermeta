import { fileLabel } from "@/lib/format";

export function DragChip({ activeId, base }: { activeId: string | null; base: string | null }) {
  if (!activeId || !activeId.startsWith("file:")) return null;
  const { name } = fileLabel(activeId.slice("file:".length), base);
  return (
    <div className="px-2 py-1 rounded border border-accent bg-surface text-xs font-mono shadow">
      {name}
    </div>
  );
}
