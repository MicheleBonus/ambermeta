import { useMemo, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { useFiles } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import {
  FileIcon, Search, GripVertical, ChevronRight, ChevronDown,
} from "@/components/common";
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

/** Folders shallower than this are open on first render. */
const AUTO_OPEN_DEPTH = 2;
const INDENT_PX = 12;
const GUTTER_PX = 8;

/**
 * Prune the tree to files whose name matches `q`, keeping their ancestor folders.
 * A folder whose own name matches is kept whole — searching for a directory that is
 * plainly on screen must not answer "No files found."
 */
export function filterTree(nodes: FileInfo[], q: string): FileInfo[] {
  if (!q) return nodes;
  const out: FileInfo[] = [];
  for (const n of nodes) {
    if (n.name.toLowerCase().includes(q)) {
      out.push(n);
    } else if (n.is_directory) {
      const kids = filterTree(n.children ?? [], q);
      if (kids.length) out.push({ ...n, children: kids });
    }
  }
  return out;
}

function hint(file: FileInfo): string | null {
  if (file.name.includes("hmr")) return "looks like your HMR topology";
  if (file.file_type === "inpcrd") return "looks like the starting structure";
  return null;
}

function FileRow({ file, depth }: { file: FileInfo; depth: number }) {
  const { select, sel } = useSelection();
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, isDragging } = useDraggable({
    id: "file:" + file.path,
    data: { fileType: file.file_type, path: file.path },
  });
  const isSelected = sel.kind === "file" && sel.id === file.path;
  const h = hint(file);

  return (
    // The listeners live on the whole row, not on the 14px grip: the grip is about 10% of the
    // row's surface, and a user who presses on the filename and drags expects to be dragging.
    // The 5px activation distance in App's PointerSensor keeps the click-to-select below intact.
    <div
      ref={setNodeRef}
      {...listeners}
      data-testid={"row:" + file.path}
      style={{ paddingLeft: depth * INDENT_PX + GUTTER_PX }}
      className={`flex items-start gap-2 pr-2 py-1.5 rounded ${isSelected ? "bg-accent-subtle" : ""} ${isDragging ? "opacity-50" : ""}`}
    >
      {/* The grip keeps `attributes` (role=button, tabIndex) so it stays the row's one named,
          focusable drag affordance rather than an anonymous button in the tab order. */}
      <span
        ref={setActivatorNodeRef}
        {...attributes}
        aria-label={`drag ${file.name}`}
        className="cursor-grab pt-0.5 text-ink-muted"
      >
        <GripVertical size={14} />
      </span>
      <FileIcon type={file.file_type} className="w-4 h-4 mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        {/* The folder qualifier FileLabel adds is already the parent row here, so the tree shows
            the bare name and keeps the full path on the tooltip. */}
        <button
          type="button"
          onClick={() => select("file", file.path)}
          title={file.path}
          className="block w-full min-w-0 text-left truncate font-mono text-sm text-ink hover:underline"
        >
          {file.name}
        </button>
        <div className="text-xs text-ink-muted">{KIND_LABELS[file.file_type] ?? file.file_type}</div>
        {h && <div className="text-xs text-valid">{h}</div>}
      </div>
    </div>
  );
}

interface TreeNodeProps {
  node: FileInfo;
  depth: number;
  expanded: Record<string, boolean>;
  toggle: (path: string, isOpen: boolean) => void;
  forceOpen: boolean;
}

function TreeNode({ node, depth, expanded, toggle, forceOpen }: TreeNodeProps) {
  if (!node.is_directory) return <FileRow file={node} depth={depth} />;

  const remembered = expanded[node.path];
  const isOpen = forceOpen || (remembered === undefined ? depth < AUTO_OPEN_DEPTH : remembered);
  const Chevron = isOpen ? ChevronDown : ChevronRight;

  return (
    <div>
      {/* While a search pins every folder open, the chevron is disabled rather than live-but-inert:
          clicking it used to change nothing on screen yet still record a collapse, which then
          sprang shut the moment the search box was cleared. */}
      <button
        type="button"
        data-testid={"row:" + node.path}
        aria-expanded={isOpen}
        disabled={forceOpen}
        title={forceOpen ? "Clear the search to collapse folders" : undefined}
        onClick={() => toggle(node.path, isOpen)}
        style={{ paddingLeft: depth * INDENT_PX + GUTTER_PX }}
        className="flex w-full items-center gap-1.5 pr-2 py-1 rounded text-left text-sm text-ink hover:bg-app disabled:cursor-default disabled:hover:bg-transparent"
      >
        <Chevron size={14} className="shrink-0 text-ink-muted" />
        <FileIcon type="folder" isOpen={isOpen} className="w-4 h-4 shrink-0" />
        <span className="truncate font-mono">{node.name}</span>
      </button>
      {isOpen &&
        node.children?.map((child) => (
          <TreeNode
            key={child.path}
            node={child}
            depth={depth + 1}
            expanded={expanded}
            toggle={toggle}
            forceOpen={forceOpen}
          />
        ))}
    </div>
  );
}

export function FilePanel() {
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const { data: files, isPending, isError } = useFiles({ recursive: true, include_all: showAll });

  const q = query.trim().toLowerCase();
  const shown = useMemo(() => filterTree(files ?? [], q), [files, q]);
  // Invert what is actually on screen, so one click always flips the row the
  // user sees — at any depth, whether or not it was opened by the default.
  const toggle = (path: string, isOpen: boolean) =>
    setExpanded((prev) => ({ ...prev, [path]: !isOpen }));

  return (
    <div className="flex flex-col h-full">
      <div className="p-2 border-b border-hairline space-y-2">
        <div className="flex items-center gap-1.5 px-2 py-1 rounded border border-hairline bg-app">
          <Search size={14} className="text-ink-muted shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search files…"
            className="w-full bg-transparent text-sm text-ink outline-none"
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-secondary">
          <input
            type="checkbox"
            checked={showAll}
            onChange={(e) => setShowAll(e.target.checked)}
            className="accent-current"
          />
          Show all files
        </label>
      </div>
      <div className="flex-1 overflow-auto p-1">
        {isPending && <p className="p-2 text-xs text-ink-muted">Loading…</p>}
        {isError && <p className="p-2 text-xs text-error">Could not load files.</p>}
        {!isPending && !isError && shown.length === 0 && (
          <p className="p-2 text-xs text-ink-muted">No files found.</p>
        )}
        {shown.map((node) => (
          <TreeNode
            key={node.path}
            node={node}
            depth={0}
            expanded={expanded}
            toggle={toggle}
            forceOpen={q.length > 0}
          />
        ))}
      </div>
    </div>
  );
}
