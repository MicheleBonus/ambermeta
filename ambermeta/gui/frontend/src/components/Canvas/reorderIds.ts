/** Moves `active` to the index currently occupied by `over` in `ids`, preserving the rest of the order. */
export function reorderIds(ids: string[], active: string, over: string): string[] {
  const from = ids.indexOf(active);
  const to = ids.indexOf(over);
  if (from === -1 || to === -1 || from === to) return ids;
  const next = ids.slice();
  next.splice(from, 1);
  next.splice(to, 0, active);
  return next;
}
