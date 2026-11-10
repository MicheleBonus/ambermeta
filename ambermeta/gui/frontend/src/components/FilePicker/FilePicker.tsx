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
  /** List only manifests (.yaml/.yml/.json). Save always does; Open asks for it, because
   *  the same picker also fills step slots, where run files are the point. */
  manifests?: boolean;
  /** The name the Save field starts with, as Plan's dialog does. */
  defaultPath?: string;
  onPick: (result: { path: string; format?: ExportFormat }) => void;
  onClose: () => void;
}

/** The names Open reads a manifest back from, and so the only files Save may replace.
 *  The server refuses any other target too; this keeps the list from offering them. */
const MANIFEST_NAME = /\.(ya?ml|json)$/i;

const slashes = (p: string) => p.replace(/\\/g, "/");

function flatten(nodes: FileInfo[], q: string, type?: FileType): FileInfo[] {
  const out: FileInfo[] = [];
  const walk = (n: FileInfo) => {
    if (!n.is_directory && n.name.toLowerCase().includes(q) && (!type || n.file_type === type)) out.push(n);
    n.children?.forEach(walk);
  };
  nodes.forEach(walk);
  return out;
}

export function FilePicker({ open, mode, title, filterType, manifests, defaultPath, onPick, onClose }: Props) {
  // Only while it is on screen: a closed picker was walking the whole tree anyway.
  const { data: tree = [] } = useFiles({ recursive: true, include_all: true, enabled: open });
  const [q, setQ] = useState("");
  const [path, setPath] = useState(defaultPath ?? "");
  const [format, setFormat] = useState<ExportFormat>("yaml");
  // The backend types anything it does not recognise as `other`, so a .log output or a .crd
  // restart is invisible in a slot-filtered picker. Relaxing the filter is the way out that
  // does not involve going back to the file tree and dragging.
  const [ignoreFilter, setIgnoreFilter] = useState(false);
  const type = ignoreFilter ? undefined : filterType;
  // Save lists only manifests: it used to offer every file under the launch directory
  // "to overwrite", and picking a run's own .mdin replaced the input with YAML.
  const files = useMemo(() => {
    const all = flatten(tree, q.toLowerCase(), type);
    return mode === "save" || manifests ? all.filter((f) => MANIFEST_NAME.test(f.name)) : all;
  }, [tree, q, type, mode, manifests]);
  // A name that is not a manifest name is refused by the server; say so here, before Save.
  const manifestName = MANIFEST_NAME.test(path.trim());
  // Whether the target names a file already on disk, whatever the search box holds. A
  // typed name is relative to the launch directory, the parent of the tree's top level.
  const replaces = useMemo(() => {
    const target = slashes(path.trim());
    if (mode !== "save" || !target || !MANIFEST_NAME.test(target)) return false;
    const base = tree[0]?.parent ? slashes(tree[0].parent).replace(/\/$/, "") : "";
    const full = /^([A-Za-z]:)?\//.test(target) ? target : `${base}/${target}`;
    return flatten(tree, "", undefined).some((f) => slashes(f.path) === full);
  }, [tree, path, mode]);

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
        {mode === "save" && files.length > 0 && (
          // Without this the list reads as "choose a file to open", and the field that
          // actually names the new file sits below it looking optional.
          <p className="px-2 py-1 text-xs text-ink-muted border-b border-hairline">
            Existing manifests — pick one to overwrite, or name a new one below.
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
            <span className="text-ink-secondary">Save as</span>
            <input aria-label="Path" value={path} onChange={(e) => setPath(e.target.value)}
              placeholder="manifest.yaml"
              className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
            <span className="block mt-1 text-xs text-ink-muted">
              A new name writes a new file; pick one above to overwrite it.
            </span>
            {replaces && (
              <span className="block mt-1 text-xs text-warning">
                This file exists and will be replaced.
              </span>
            )}
            {path.trim() && !manifestName && (
              <span className="block mt-1 text-xs text-warning">
                A manifest is saved as .yaml, .yml or .json.
              </span>
            )}
          </label>
          <label className="block text-sm">
            <span className="text-ink-secondary">Format</span>
            {/* yaml/json only: the v2 manifest writer rejects toml and csv, so offering
                them here produced a 400 for a choice the dialog itself had presented.
                Export covers the lossy flat views. */}
            <select aria-label="Format" value={format}
              onChange={(e) => setFormat(e.target.value as ExportFormat)}
              className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app">
              <option value="yaml">yaml</option>
              <option value="json">json</option>
            </select>
          </label>
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!path.trim() || !manifestName}
              onClick={() => onPick({ path: path.trim(), format })}>Save</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
