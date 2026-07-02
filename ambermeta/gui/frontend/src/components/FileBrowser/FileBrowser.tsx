import { useMemo, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { useFiles, useFileMetadata } from "@/api/hooks";
import { useDocument } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { FileIcon, FileLabel, ChevronRight, ChevronDown } from "@/components/common";
import type { FileInfo } from "@/types";

// Prune the tree to files whose name matches q, keeping ancestor folders.
function filterTree(nodes: FileInfo[], q: string): FileInfo[] {
  if (!q) return nodes;
  const out: FileInfo[] = [];
  for (const n of nodes) {
    if (n.is_directory) {
      const kids = filterTree(n.children ?? [], q);
      if (kids.length) out.push({ ...n, children: kids });
    } else if (n.name.toLowerCase().includes(q)) {
      out.push(n);
    }
  }
  return out;
}

function FileRow({ file, base, depth }: { file: FileInfo; base: string | null; depth: number }) {
  const { attributes, listeners, setNodeRef } = useDraggable({ id: `file:${file.path}` });
  const { selectedFile, selectFile } = useSelection();
  const selected = selectedFile === file.path;
  return (
    <div ref={setNodeRef} {...listeners} {...attributes}
      onClick={() => selectFile(file.path)}
      style={{ paddingLeft: depth * 12 + 8 }}
      className={`flex items-center gap-2 w-full pr-2 py-1 text-sm rounded cursor-grab
        ${selected ? "bg-accent-subtle" : "hover:bg-app"}`}>
      <FileIcon type={file.file_type} size={14} />
      <span className="min-w-0 truncate"><FileLabel path={file.path} base={base} /></span>
    </div>
  );
}

function TreeNode({ node, base, depth, expanded, toggle, forceOpen }: {
  node: FileInfo; base: string | null; depth: number;
  expanded: Record<string, boolean>; toggle: (p: string) => void; forceOpen: boolean;
}) {
  if (!node.is_directory) return <FileRow file={node} base={base} depth={depth} />;
  const isOpen = forceOpen || expanded[node.path] || (expanded[node.path] === undefined && depth < 2);
  return (
    <div>
      <div onClick={() => toggle(node.path)} style={{ paddingLeft: depth * 12 }}
        className="flex items-center gap-1 py-1 text-sm cursor-pointer hover:bg-app rounded">
        {isOpen ? <ChevronDown size={14} className="text-ink-muted" />
                : <ChevronRight size={14} className="text-ink-muted" />}
        <FileIcon type="folder" size={14} isOpen={isOpen} />
        <span className="truncate">{node.name}</span>
      </div>
      {isOpen && node.children?.map((c) => (
        <TreeNode key={c.path} node={c} base={base} depth={depth + 1}
          expanded={expanded} toggle={toggle} forceOpen={forceOpen} />
      ))}
    </div>
  );
}

export function FileBrowser() {
  const [q, setQ] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const { data: tree = [], isPending, isError } = useFiles({ recursive: true, include_all: showAll });
  const { data: doc } = useDocument();
  const { selectedFile } = useSelection();
  const { data: meta, isPending: metaPending } = useFileMetadata(selectedFile);

  const query = q.toLowerCase();
  const shown = useMemo(() => filterTree(tree, query), [tree, query]);
  const toggle = (p: string) =>
    setExpanded((e) => ({ ...e, [p]: !(e[p] ?? true) })); // first click on a default-open folder collapses it

  return (
    <div className="flex flex-col h-full">
      <div className="p-2 border-b border-hairline space-y-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search files"
          className="w-full px-2 py-1 text-sm border border-hairline rounded bg-app" />
        <label className="flex items-center gap-2 text-xs text-ink-secondary">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
          Show all files
        </label>
      </div>
      <div className="flex-1 overflow-auto p-1">
        {isPending && <p className="p-2 text-xs text-ink-muted">Loading…</p>}
        {isError && <p className="p-2 text-xs text-error">Could not load files.</p>}
        {!isPending && !isError && shown.length === 0 && (
          <p className="p-2 text-xs text-ink-muted">No files found.</p>
        )}
        {shown.map((n) => (
          <TreeNode key={n.path} node={n} base={doc?.base_directory ?? null} depth={0}
            expanded={expanded} toggle={toggle} forceOpen={query.length > 0} />
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
