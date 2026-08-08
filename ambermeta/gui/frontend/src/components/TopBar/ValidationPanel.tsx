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
  const coherence = report?.coherence ?? [];
  const coherenceErrors = coherence.filter((f) => f.severity === "error");
  const stageErrors = report?.stage_issues.filter((s) => !s.ok).length ?? 0;
  const noteCount = (report?.protocol_issues.length ?? 0)
    + coherence.filter((f) => f.severity === "warning").length;

  // A category error -- members holding different atom counts, or minimisation mixed with
  // dynamics -- is not attached to any one stage, so the old ladder (which read only
  // `stage_issues`) showed "All checks passed" for a document the CLI exits 1 on.
  let status: { tone: "valid" | "warning" | "error"; label: string } | null = null;
  if (report) {
    if (coherenceErrors.length > 0) {
      status = { tone: "error", label: `${coherenceErrors.length} lineage error(s)` };
    } else if (stageErrors > 0) {
      status = { tone: "error", label: `${stageErrors} stage(s) with errors` };
    } else if (noteCount > 0) {
      status = { tone: "warning", label: `Valid, with ${noteCount} note(s)` };
    } else {
      status = { tone: "valid", label: "All checks passed" };
    }
  }

  const toneOf = (severity: string) =>
    severity === "error" ? "text-error" : severity === "warning" ? "text-warning" : "text-ink-muted";

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
      {coherence.length ? (
        <section className="mb-3">
          <h3 className="text-sm font-semibold mb-1">Lineages</h3>
          <ul className="text-sm space-y-0.5">
            {coherence.map((f, i) => (
              <li key={i} className={toneOf(f.severity)}>{f.message}</li>
            ))}
          </ul>
        </section>
      ) : null}
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
      {report?.lineages ? (
        <section className="mb-3">
          <h3 className="text-sm font-semibold mb-1">Per lineage</h3>
          <ul className="text-sm space-y-0.5 font-mono">
            {Object.entries(report.lineages).map(([tag, t]) => (
              <li key={tag}>
                <span className="font-semibold">{tag}</span>
                {` · ${t.step_count} run(s) · ${t.time_ps.toFixed(3)} ps`}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {report && (
        <footer className="mt-3 text-xs text-ink-muted font-mono">
          {report.totals.stage_count ?? 0} step(s) · {(report.totals.time_ps ?? 0).toFixed(3)} ps total
        </footer>
      )}
    </Modal>
  );
}
