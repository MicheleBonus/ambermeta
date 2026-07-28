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
    <div className="fixed bottom-4 right-4 flex flex-col gap-2 z-50">
      {toasts.map((t) => (
        <div key={t.id} role="status"
          className={`flex items-center gap-2 px-3 py-2 rounded-full border bg-surface text-sm ${toneClass[t.tone]}`}>
          <span>{t.message}</span>
          {t.action && (
            <button type="button"
              onClick={() => { t.action?.run(); dismissToast(t.id); }}
              className="font-medium underline underline-offset-2 hover:opacity-80">
              {t.action.label}
            </button>
          )}
          <button type="button" aria-label="Dismiss" onClick={() => dismissToast(t.id)}
            className="ml-1 opacity-60 hover:opacity-100">×</button>
        </div>
      ))}
    </div>
  );
}
