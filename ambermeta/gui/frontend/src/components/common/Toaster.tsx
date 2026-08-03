import { useSyncExternalStore } from "react";
import { subscribeToasts, getToasts, dismissToast } from "@/lib/toast";
import type { Toast } from "@/lib/toast";

const toneClass: Record<Toast["tone"], string> = {
  error: "text-error border-error/30",
  warning: "text-warning border-warning/30",
  info: "text-ink border-hairline",
};

export function Toaster() {
  const toasts = useSyncExternalStore(subscribeToasts, getToasts);
  if (toasts.length === 0) return null;
  return (
    // items-end so each toast is as wide as its own message: the column stretches its
    // children, and one wrapped warning would otherwise blow every short toast up with it.
    <div className="fixed bottom-4 right-4 flex flex-col items-end gap-2 z-50">
      {toasts.map((t) => (
        // Capped and squared off rather than an uncapped pill. A chain warning is whole
        // sentences, and at a 9999px radius the first and last lines of a wrapped message
        // run into the curve; on the one-line toasts that were the only kind before, the
        // two radii differ by 3px. items-start keeps the buttons on the first line.
        <div key={t.id} role="status"
          className={`flex items-start gap-2 max-w-sm px-3 py-2 rounded-2xl border bg-surface text-sm ${toneClass[t.tone]}`}>
          <span>{t.message}</span>
          {t.action && (
            <button type="button"
              onClick={() => { t.action?.run(); dismissToast(t.id); }}
              className="shrink-0 font-medium underline underline-offset-2 hover:opacity-80">
              {t.action.label}
            </button>
          )}
          <button type="button" aria-label="Dismiss" onClick={() => dismissToast(t.id)}
            className="ml-1 shrink-0 opacity-60 hover:opacity-100">×</button>
        </div>
      ))}
    </div>
  );
}
