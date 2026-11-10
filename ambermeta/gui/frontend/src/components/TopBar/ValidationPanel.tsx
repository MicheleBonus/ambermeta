import { useEffect } from "react";
import { Modal, Badge } from "@/components/common";
import { useValidate, useDocument } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { formatDuration } from "@/lib/format";
import type { Suggestion } from "@/types";

const FINDING_KINDS = new Set(["missing_run", "step_check", "unfinished_run", "input_mismatch"]);

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
  // The findings `--strict` fails on that are not already a protocol note: a sequence hole
  // and a run's own findings. `continuity_gap` is left out because each one is also in
  // `protocol_issues`, which is counted above. Without these the badge stayed green for a
  // document the CLI exits 1 on.
  // An acknowledged finding is settled: the manifest says why it stands, so it is listed
  // with its note below and counted apart, never as a note to review.
  const findingCount = (report?.suggestions ?? []).filter(
    (s) => s.severity === "needs_you" && FINDING_KINDS.has(s.kind) && !s.acknowledged,
  ).length;
  // A continuity gap is both a card and a protocol note, with the same text, so settling
  // the card settles the note.
  const settledText = new Set((report?.suggestions ?? [])
    .filter((s) => s.acknowledged).map((s) => s.evidence));
  const openText = new Set((report?.suggestions ?? [])
    .filter((s) => s.severity === "needs_you" && FINDING_KINDS.has(s.kind) && !s.acknowledged)
    .map((s) => s.evidence));
  const openIssues = (report?.protocol_issues ?? []).filter((p) => !settledText.has(p));
  const acknowledged = report?.acknowledged ?? [];
  const stale = report?.stale_acknowledgements ?? [];
  // The counted findings no step card shows: a sequence hole belongs to no step, so the
  // badge counted it while nothing in the panel listed it. A run's own findings are on
  // their step's card already (`stage_issues`), so only the unscoped ones are listed here.
  const unscopedFindings = (report?.suggestions ?? []).filter(
    (s) => s.severity === "needs_you" && FINDING_KINDS.has(s.kind) && !s.step_id
      && !s.acknowledged,
  );
  const noteCount = openIssues.length
    + coherence.filter((f) => f.severity === "warning" && !f.acknowledged).length
    + findingCount;
  const settled = acknowledged.length ? `, ${acknowledged.length} acknowledged` : "";

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
      status = { tone: "warning", label: `Valid, with ${noteCount} note(s)${settled}` };
    } else {
      status = { tone: "valid", label: `All checks passed${settled}` };
    }
  }

  // A run's own finding reaches its step as the bare message, and its card as
  // `<step name>: <message>`; a continuity note is the same text in both.
  const isSettled = (name: string, warning: string) =>
    settledText.has(`${name}: ${warning}`) || settledText.has(warning);
  // Only a finding marks a step 'check'. A stage warning that no finding carries ("No atom
  // counts available") is a remark: nothing counts it, so badging it contradicted the
  // panel's own "All checks passed".
  const isOpenFinding = (name: string, warning: string) =>
    openText.has(`${name}: ${warning}`) || openText.has(warning);

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
            {coherence.filter((f) => !f.acknowledged).map((f, i) => (
              <li key={i} className={toneOf(f.severity)}>{f.message}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {openIssues.length ? (
        <section className="mb-3">
          <h3 className="text-sm font-semibold mb-1">Protocol notes</h3>
          <ul className="text-sm text-warning space-y-0.5">
            {openIssues.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </section>
      ) : null}
      {acknowledged.length ? (
        <section className="mb-3">
          <h3 className="text-sm font-semibold mb-1">Acknowledged</h3>
          <ul className="text-sm space-y-1">
            {acknowledged.map((a, i) => (
              <li key={i}>
                <div className="text-ink-secondary">{a.finding}</div>
                <div className="text-ink-muted text-xs">Note: {a.note}</div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {stale.length ? (
        <section className="mb-3">
          <h3 className="text-sm font-semibold mb-1">Acknowledged, no longer found</h3>
          <p className="text-xs text-ink-muted mb-1">
            The manifest acknowledges these, but no finding reads this way any more.
          </p>
          <ul className="text-sm text-ink-secondary space-y-0.5">
            {stale.map((a, i) => <li key={i}>{a.finding}</li>)}
          </ul>
        </section>
      ) : null}
      {unscopedFindings.length ? (
        <section className="mb-3">
          <h3 className="text-sm font-semibold mb-1">Findings</h3>
          <ul className="text-sm text-warning space-y-0.5">
            {unscopedFindings.map((s, i) => <li key={i}>{s.title}</li>)}
          </ul>
        </section>
      ) : null}
      <section className="space-y-2">
        {report?.stage_issues.map((s) => (
          <div key={s.name} className="border border-hairline rounded p-2">
            <button onClick={() => jump(s.name)}
              className="flex items-center gap-2 font-medium text-left">
              {/* "ok" is about the step's files; a step that carries a finding is valid
                  and still worth a look, so it is not shown green. */}
              {!s.ok ? <Badge tone="error">error</Badge>
                : s.warnings.some((w) => isOpenFinding(s.name, w)) ? <Badge tone="warning">check</Badge>
                : <Badge tone="valid">ok</Badge>}
              <span>{s.name}</span>
            </button>
            {s.errors.map((e, i) => <p key={`e${i}`} className="text-error text-sm">{e}</p>)}
            {s.warnings.map((w, i) => isSettled(s.name, w)
              ? <p key={`w${i}`} className="text-ink-muted text-sm">{w} (acknowledged)</p>
              : <p key={`w${i}`} className={`${isOpenFinding(s.name, w) ? "text-warning"
                  : "text-ink-secondary"} text-sm`}>{w}</p>)}
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
                {` · ${t.step_count} run(s) · ${formatDuration(t.time_ps)}`}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {report && (
        <footer className="mt-3 text-xs text-ink-muted font-mono">
          {report.totals.stage_count ?? 0} step(s) · {formatDuration(report.totals.time_ps ?? 0)} total
        </footer>
      )}
    </Modal>
  );
}
