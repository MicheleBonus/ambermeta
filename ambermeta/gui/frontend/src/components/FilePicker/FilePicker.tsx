import { useMemo, useState } from "react";
import { Modal, Button, FileIcon } from "@/components/common";
import { useFiles } from "@/api/hooks";
import type { FileInfo, ExportFormat } from "@/types";

interface Props {
  open: boolean;
  mode: "open" | "save";
  title: string;
  onPick: (result: { path: string; format?: ExportFormat }) => void;
  onClose: () => void;
}

function flatten(nodes: FileInfo[], q: string): FileInfo[] {
  const out: FileInfo[] = [];
  const walk = (n: FileInfo) => {
    if (!n.is_directory && n.name.toLowerCase().includes(q)) out.push(n);
    n.children?.forEach(walk);
  };
  nodes.forEach(walk);
  return out;
}

export function FilePicker({ open, mode, title, onPick, onClose }: Props) {
  const { data: tree = [] } = useFiles({ recursive: true, include_all: true });
  const [q, setQ] = useState("");
  const [path, setPath] = useState("");
  const [format, setFormat] = useState<ExportFormat>("yaml");
  const files = useMemo(() => flatten(tree, q.toLowerCase()), [tree, q]);

  return (
    <Modal open={open} title={title} onClose={onClose}>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search files"
        className="w-full px-2 py-1 mb-2 text-sm border border-hairline rounded bg-app" />
      <div className="max-h-64 overflow-auto border border-hairline rounded">
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
