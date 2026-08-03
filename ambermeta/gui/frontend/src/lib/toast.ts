export type ToastTone = "error" | "warning" | "info";
/** An offer to reverse what the toast is reporting, e.g. "Undo" after a delete. */
export interface ToastAction { label: string; run: () => void; }
export interface Toast {
  id: number; message: string; tone: ToastTone; action?: ToastAction;
  /** Speaks about one particular edit, so the next one retires it — see `expireEditToasts`. */
  aboutLastEdit?: boolean;
}
let toasts: Toast[] = [];
const listeners = new Set<() => void>();
let nextId = 1;
const emit = () => listeners.forEach((l) => l());
function push(t: Omit<Toast, "id">): void {
  toasts = [...toasts, { id: nextId++, ...t }];
  emit();
}
export function pushToast(message: string, tone: ToastTone = "info", action?: ToastAction): void {
  // An offer to reverse something is a statement about the last edit by construction:
  // there is nothing else it could be offering to reverse.
  push({ message, tone, action, aboutLastEdit: !!action });
}
/**
 * Report what the edit that just landed had to warn about — a shared parent deleted out
 * from under several lineages, a link across two of them.
 *
 * Its own function rather than a flag on `pushToast`, because the lifetime is the point:
 * this is the second kind of toast that stops being true the moment another edit lands,
 * and the caller has to say which kind it is pushing.
 */
export function pushEditWarning(message: string): void {
  push({ message, tone: "warning", aboutLastEdit: true });
}
export function dismissToast(id: number): void {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}
/**
 * Drop every toast that was speaking about the previous edit.
 *
 * Called whenever a document mutation lands. An outstanding "Undo" offer has to go because
 * Undo pops the newest snapshot: an offer that outlived the edit it belongs to would
 * quietly reverse somebody else's work. A warning about what an edit did has to go for a
 * milder reason — it is simply no longer about what just happened, and the server stopped
 * sending it at the same moment (`DocumentStore._snapshot` clears the warnings on every
 * mutation, so a note left on screen would outlive its own source).
 */
export function expireEditToasts(): void {
  if (!toasts.some((t) => t.aboutLastEdit)) return;
  toasts = toasts.filter((t) => !t.aboutLastEdit);
  emit();
}
export function getToasts(): Toast[] { return toasts; }
export function subscribeToasts(l: () => void): () => void {
  listeners.add(l);
  return () => { listeners.delete(l); };
}
export function _resetToasts(): void { toasts = []; emit(); } // test helper
