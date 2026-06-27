import { useEffect, useRef, type ReactNode } from "react";

export function Modal(
  { open, title, onClose, children }:
  { open: boolean; title: string; onClose: () => void; children: ReactNode }
) {
  const ref = useRef<HTMLDivElement>(null);
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
