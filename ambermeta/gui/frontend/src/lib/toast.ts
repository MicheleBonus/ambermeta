export type ToastTone = "error" | "warning" | "info";
export interface Toast { id: number; message: string; tone: ToastTone; }
let toasts: Toast[] = [];
const listeners = new Set<() => void>();
let nextId = 1;
const emit = () => listeners.forEach((l) => l());
export function pushToast(message: string, tone: ToastTone = "info"): void {
  const id = nextId++;
  toasts = [...toasts, { id, message, tone }];
  emit();
}
export function dismissToast(id: number): void {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}
export function getToasts(): Toast[] { return toasts; }
export function subscribeToasts(l: () => void): () => void {
  listeners.add(l);
  return () => { listeners.delete(l); };
}
export function _resetToasts(): void { toasts = []; emit(); } // test helper
