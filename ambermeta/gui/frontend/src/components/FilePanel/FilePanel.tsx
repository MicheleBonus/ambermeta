import { useMemo, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { useFiles } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { FileIcon, Search, GripVertical } from "@/components/common";
import type { FileInfo } from "@/types";

const KIND_LABELS: Record<FileInfo["file_type"], string> = {
  prmtop: "topology",
  mdin: "input script",
  mdout: "output log",
  mdcrd: "trajectory",
  inpcrd: "coordinates",
  folder: "folder",
  other: "file",
};

function flatten(files: FileInfo[]): FileInfo[] {
  const out: FileInfo[] = [];
  for (const f of files) {
    if (!f.is_directory) out.push(f);
    if (f.children) out.push(...flatten(f.children));
  }
  return out;
}

function hint(file: FileInfo): string | null {
  if (file.name.includes("hmr")) return "looks like your HMR topology";
  if (file.file_type === "inpcrd") return "looks like the starting structure";
  return null;
}

function DraggableFile({ file }: { file: FileInfo }) {
  const { select, sel } = useSelection();
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: "file:" + file.path });
  const isSelected = sel.kind === "file" && sel.id === file.path;
  const h = hint(file);

  return (
    <div
      ref={setNodeRef}
      className={`flex items-start gap-2 px-2 py-1.5 rounded ${isSelected ? "bg-accent-subtle" : ""} ${isDragging ? "opacity-50" : ""}`}
    >
      <span {...attributes} {...listeners} className="cursor-grab pt-0.5 text-ink-muted">
        <GripVertical size={14} />
      </span>
      <FileIcon type={file.file_type} className="w-4 h-4 mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <button
          type="button"
          onClick={() => select("file", file.path)}
          className="block w-full text-left truncate font-mono text-sm text-ink hover:underline"
        >
          {file.name}
        </button>
        <div className="text-xs text-ink-muted">{KIND_LABELS[file.file_type] ?? file.file_type}</div>
        {h && <div className="text-xs text-valid">{h}</div>}
      </div>
    </div>
  );
}

export function FilePanel() {
  const [query, setQuery] = useState("");
  const { data: files } = useFiles({});
  const flat = useMemo(() => flatten(files ?? []), [files]);
  const filtered = useMemo(
    () => (query ? flat.filter((f) => f.name.toLowerCase().includes(query.toLowerCase())) : flat),
    [flat, query],
  );

  return (
    <div className="flex flex-col h-full">
      <div className="p-2 border-b border-hairline">
        <div className="flex items-center gap-1.5 px-2 py-1 rounded border border-hairline bg-app">
          <Search size={14} className="text-ink-muted shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search files…"
            className="w-full bg-transparent text-sm text-ink outline-none"
          />
        </div>
      </div>
      <div className="flex-1 overflow-auto p-1">
        {filtered.map((f) => (
          <DraggableFile key={f.path} file={f} />
        ))}
      </div>
    </div>
  );
}
