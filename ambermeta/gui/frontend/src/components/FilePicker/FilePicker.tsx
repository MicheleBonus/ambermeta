import { useMemo, useState } from "react";
import { Modal, Button, FileIcon } from "@/components/common";
import { useFiles } from "@/api/hooks";
import type { FileInfo, FileType, ExportFormat } from "@/types";

interface Props {
  open: boolean;
  mode: "open" | "save";
  title: string;
  /** Show only files of this kind — a picker whose title names a slot must not
   *  offer everything else on disk. Omit it to list the whole tree. */
  filterType?: FileType;
  onPick: (result: { path: string; format?: ExportFormat }) => void;
  onClose: () => void;
}

function flatten(nodes: FileInfo[], q: string, type?: FileType): FileInfo[] {
  const out: FileInfo[] = [];
  const walk = (n: FileInfo) => {
    if (!n.is_directory && n.name.toLowerCase().includes(q) && (!type || n.file_type === type)) out.push(n);
    n.children?.forEach(walk);
  };
  nodes.forEach(walk);
  return out;
}

export function FilePicker({ open, mode, title, filterType, onPick, onClose }: Props) {
  const { data: tree = [] } = useFiles({ recursive: true, include_all: true });
  const [q, setQ] = useState("");
  const [path, setPath] = useState("");
  const [format, setFormat] = useState<ExportFormat>("yaml");
  // The backend types anything it does not recognise as `other`, so a .log output or a .crd
  // restart is invisible in a slot-filtered picker. Relaxing the filter is the way out that
  // does not involve going back to the file tree and dragging.
  const [ignoreFilter, setIgnoreFilter] = useState(false);
  const type = ignoreFilter ? undefined : filterType;
  const files = useMemo(() => flatten(tree, q.toLowerCase(), type), [tree, q, type]);

  return (
    <Modal open={open} title={title} onClose={onClose}>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search files"
        className="w-full px-2 py-1 mb-2 text-sm border border-hairline rounded bg-app" />
      {filterType && (
        <label className="flex items-center gap-2 mb-2 text-xs text-ink-secondary">
          <input type="checkbox" checked={ignoreFilter} className="accent-current"
            onChange={(e) => setIgnoreFilter(e.target.checked)} />
          Show all file types
        </label>
      )}
      <div className="max-h-64 overflow-auto border border-hairline rounded">
        {files.length === 0 && (
          <p className="p-2 text-xs text-ink-muted">
            {type ? `No ${type} files found.` : "No files found."}
          </p>
        )}
        {files.map((f) => (
          <button key={f.path}
            onClick={() => (mode === "open" ? onPick({ path: f.path }) : setPath(f.path))}
            className="flex items-center gap-2 w-full px-2 py-1 text-left text-sm hover:bg-app">
            <FileIcon type={f.file_type} />
            <span className="font-mono text-sm">{f.name}</span>
            <span className="font-mono text-xs text-ink-muted truncate">{f.path}</span>
          </button>
        ))}
      </div>
      {mode === "save" && (
        <div className="mt-3 space-y-2">
          <label className="block text-sm">
            <span className="text-ink-secondary">Path</span>
            <input aria-label="Path" value={path} onChange={(e) => setPath(e.target.value)}
              className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
          </label>
          <label className="block text-sm">
            <span className="text-ink-secondary">Format</span>
            <select aria-label="Format" value={format}
              onChange={(e) => setFormat(e.target.value as ExportFormat)}
              className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app">
              <option value="yaml">yaml</option>
              <option value="json">json</option>
              <option value="toml">toml</option>
              <option value="csv">csv</option>
            </select>
          </label>
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!path}
              onClick={() => onPick({ path, format })}>Save</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
