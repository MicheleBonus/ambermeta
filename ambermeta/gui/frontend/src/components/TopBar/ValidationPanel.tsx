import { useEffect } from "react";
import { Modal, Badge } from "@/components/common";
import { useValidate, useDocument } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import type { Suggestion } from "@/types";

export function ValidationPanel(
  { open, onClose, onSuggestions }:
  { open: boolean; onClose: () => void; onSuggestions?: (suggestions: Suggestion[]) => void }
) {
  const validate = useValidate();
  const { data: doc } = useDocument();
  const { select } = useSelection();
  const run = validate.mutate;

  useEffect(() => {
    if (!open) return;
    run(undefined, { onSuccess: (report) => onSuggestions?.(report.suggestions) });
    // Re-run every time the panel opens; onSuggestions/run are stable enough
    // that including them would just re-fire on identity churn, not intent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const report = validate.data;
  const errorCount = report?.stage_issues.filter((s) => !s.ok).length ?? 0;
  const noteCount = report?.protocol_issues.length ?? 0;

  let status: { tone: "valid" | "warning" | "error"; label: string } | null = null;
  if (report) {
    if (errorCount > 0) status = { tone: "error", label: `${errorCount} stage(s) with errors` };
    else if (noteCount > 0) status = { tone: "warning", label: `Valid, with ${noteCount} protocol note(s)` };
    else status = { tone: "valid", label: "All checks passed" };
  }

  const jump = (name: string) => {
    const step = doc?.simulation.phases.flatMap((p) => p.steps).find((s) => s.name === name);
    if (step) { select("step", step.id); onClose(); }
  };

  return (
    <Modal open={open} title="Validation" onClose={onClose}>
      {validate.isPending && <p className="text-ink-muted text-sm">Validating…</p>}
      {status && (
        <div className="mb-3"><Badge tone={status.tone}>{status.label}</Badge></div>
      )}
      {report?.protocol_issues.length ? (
        <section className="mb-3">
          <h3 className="text-sm font-semibold mb-1">Protocol notes</h3>
          <ul className="text-sm text-warning space-y-0.5">
            {report.protocol_issues.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </section>
      ) : null}
      <section className="space-y-2">
        {report?.stage_issues.map((s) => (
          <div key={s.name} className="border border-hairline rounded p-2">
            <button onClick={() => jump(s.name)}
              className="flex items-center gap-2 font-medium text-left">
              <Badge tone={s.ok ? "valid" : "error"}>{s.ok ? "ok" : "error"}</Badge>
              <span>{s.name}</span>
            </button>
            {s.errors.map((e, i) => <p key={`e${i}`} className="text-error text-sm">{e}</p>)}
            {s.warnings.map((w, i) => <p key={`w${i}`} className="text-warning text-sm">{w}</p>)}
            {s.info.map((n, i) => <p key={`i${i}`} className="text-ink-muted text-sm">{n}</p>)}
          </div>
        ))}
      </section>
      {report && (
        <footer className="mt-3 text-xs text-ink-muted font-mono">
          {report.totals.stage_count ?? 0} step(s) · {report.totals.time_ps ?? 0} ps total
        </footer>
      )}
    </Modal>
  );
}
