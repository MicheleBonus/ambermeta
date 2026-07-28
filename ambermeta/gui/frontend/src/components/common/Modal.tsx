import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";

/**
 * How many modals are on screen.
 *
 * Every dialog in the app is a Modal, so counting here is the one place that knows a modal
 * owns the screen. Enumerating the flags of the modals one component happens to own missed
 * the pickers raised by step cards and the simulation header, and a document-wide Ctrl+Z
 * would then rewind the document behind an open dialog.
 */
let openModals = 0;
const modalListeners = new Set<() => void>();
function setOpenModals(n: number) {
  openModals = n;
  modalListeners.forEach((l) => l());
}
export function anyModalOpen(): boolean {
  return openModals > 0;
}
export function subscribeModals(l: () => void): () => void {
  modalListeners.add(l);
  return () => { modalListeners.delete(l); };
}
export function useAnyModalOpen(): boolean {
  return useSyncExternalStore(subscribeModals, anyModalOpen, () => false);
}

export function Modal(
  { open, title, onClose, children }:
  { open: boolean; title: string; onClose: () => void; children: ReactNode }
) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    setOpenModals(openModals + 1);
    return () => setOpenModals(openModals - 1);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key !== "Tab" || !ref.current) return;
      // Trap Tab focus within the dialog (a11y for modal dialogs).
      const f = ref.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (f.length === 0) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/20"
         onMouseDown={onClose}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-label={title}
           onMouseDown={(e) => e.stopPropagation()}
           className="bg-surface border border-hairline rounded-lg shadow-lg w-[min(560px,92vw)] max-h-[85vh] overflow-auto outline-none">
        <header className="px-4 py-3 border-b border-hairline font-semibold">{title}</header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}
