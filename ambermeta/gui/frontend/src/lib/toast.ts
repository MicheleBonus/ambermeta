export type ToastTone = "error" | "warning" | "info";
/** An offer to reverse what the toast is reporting, e.g. "Undo" after a delete. */
export interface ToastAction { label: string; run: () => void; }
export interface Toast { id: number; message: string; tone: ToastTone; action?: ToastAction; }
let toasts: Toast[] = [];
const listeners = new Set<() => void>();
let nextId = 1;
const emit = () => listeners.forEach((l) => l());
export function pushToast(message: string, tone: ToastTone = "info", action?: ToastAction): void {
  const id = nextId++;
  toasts = [...toasts, { id, message, tone, action }];
  emit();
}
export function dismissToast(id: number): void {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}
/**
 * Drop every toast still offering to reverse something.
 *
 * Called whenever a document mutation lands. Undo pops the newest snapshot, so an offer
 * that outlived the edit it belongs to would quietly reverse somebody else's work — the
 * offer has to disappear the moment it stops meaning what it says.
 */
export function expireToastActions(): void {
  if (!toasts.some((t) => t.action)) return;
  toasts = toasts.filter((t) => !t.action);
  emit();
}
export function getToasts(): Toast[] { return toasts; }
export function subscribeToasts(l: () => void): () => void {
  listeners.add(l);
  return () => { listeners.delete(l); };
}
export function _resetToasts(): void { toasts = []; emit(); } // test helper
