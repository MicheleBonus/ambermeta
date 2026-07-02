export function reorderIds(ids: string[], activeId: string, overId: string): string[] {
  if (activeId === overId) return ids;
  const from = ids.indexOf(activeId);
  const to = ids.indexOf(overId);
  if (from === -1 || to === -1) return ids;
  const next = ids.slice();
  next.splice(from, 1);
  next.splice(to, 0, activeId);
  return next;
}

// Pure router for the single app-level DndContext onDragEnd. Draggable ids are
// `file:<path>` (path may contain ':'); droppable slot ids are `slot:<stageId>:<kind>`;
// stage rows are sortable by their plain stage id.
export type DropResult =
  | { type: "assign"; stageId: string; kind: string; path: string }
  | { type: "reorder"; activeId: string; overId: string }
  | { type: "create"; path: string };

export function resolveDrop(activeId: string, overId: string | null): DropResult | null {
  if (!overId) return null;
  if (activeId.startsWith("file:") && overId.startsWith("slot:")) {
    const path = activeId.slice("file:".length);
    const rest = overId.slice("slot:".length);
    const sep = rest.indexOf(":");
    if (sep === -1) return null;
    return { type: "assign", stageId: rest.slice(0, sep), kind: rest.slice(sep + 1), path };
  }
  if (activeId.startsWith("file:") && overId === "new-stage") {
    return { type: "create", path: activeId.slice("file:".length) };
  }
  if (!activeId.startsWith("file:") && !overId.startsWith("slot:") && activeId !== overId) {
    return { type: "reorder", activeId, overId };
  }
  return null;
}
