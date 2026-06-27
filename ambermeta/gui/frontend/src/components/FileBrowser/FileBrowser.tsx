import { useMemo, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { useFiles, useFileMetadata } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { FileIcon } from "@/components/common";
import type { FileInfo } from "@/types";

function flatten(nodes: FileInfo[], q: string): FileInfo[] {
  const out: FileInfo[] = [];
  const walk = (n: FileInfo) => {
    if (!n.is_directory && n.name.toLowerCase().includes(q)) out.push(n);
    n.children?.forEach(walk);
  };
  nodes.forEach(walk);
  return out;
}

function DraggableFile({ file, onSelect, selected }:
  { file: FileInfo; onSelect: () => void; selected: boolean }) {
  const { attributes, listeners, setNodeRef } = useDraggable({ id: `file:${file.path}` });
  return (
    <div
      className={`flex items-center gap-2 w-full px-2 py-1 text-sm rounded
        ${selected ? "bg-accent-subtle" : "hover:bg-app"}`}
    >
      {/* drag handle — carries dnd-kit listeners; separate from click target */}
      <span ref={setNodeRef} {...listeners} {...attributes} className="shrink-0">
        <FileIcon type={file.file_type} />
      </span>
      <button onClick={onSelect} className="flex-1 text-left text-sm truncate">
        {file.name}
      </button>
    </div>
  );
}

export function FileBrowser() {
  const [q, setQ] = useState("");
  const { data: tree = [] } = useFiles({ recursive: true });
  const { selectedFile, selectFile } = useSelection();
  const { data: meta, isPending: metaPending } = useFileMetadata(selectedFile);

  const files = useMemo(() => flatten(tree, q.toLowerCase()), [tree, q]);

  return (
    <div className="flex flex-col h-full">
      <div className="p-2 border-b border-hairline">
        <input
          value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Search files"
          className="w-full px-2 py-1 text-sm border border-hairline rounded bg-app"
        />
      </div>
      <div className="flex-1 overflow-auto p-1">
        {files.map((f) => (
          <DraggableFile key={f.path} file={f}
            selected={selectedFile === f.path}
            onSelect={() => selectFile(f.path)} />
        ))}
      </div>
      {selectedFile && (
        <div data-testid="file-metadata" className="border-t border-hairline p-2 text-xs font-mono">
          {metaPending && <span className="text-ink-muted">Reading…</span>}
          {meta?.metadata.details && (
            <dl className="grid grid-cols-2 gap-x-2 gap-y-0.5">
              {Object.entries(meta.metadata.details)
                .filter(([, v]) => v !== null && typeof v !== "object")
                .slice(0, 8)
                .map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-ink-muted">{k}</dt>
                    <dd className="text-ink truncate">{String(v)}</dd>
                  </div>
                ))}
            </dl>
          )}
          {meta?.metadata.warnings?.map((w, i) => (
            <p key={i} className="text-warning mt-1">{w}</p>
          ))}
        </div>
      )}
    </div>
  );
}
