import { useState } from "react";
import { useDocument, useDeletePhase, useUpdatePhase } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { Button } from "@/components/common";
import { ROLE_OPTIONS } from "@/lib/roles";
import type { StageRole } from "@/types";
import { CommitField, CONTROL, Field } from "./NodeFields";

export function PhaseInspector({ phaseId }: { phaseId: string }) {
  const { data: doc } = useDocument();
  const { select } = useSelection();
  const updatePhase = useUpdatePhase();
  const deletePhase = useDeletePhase();
  // Where this phase's steps go when it is deleted. "" means delete them with the phase.
  const [reassignTo, setReassignTo] = useState("");

  const phases = doc?.simulation.phases ?? [];
  const phase = phases.find((p) => p.id === phaseId);
  if (!doc || !phase) {
    return <div className="p-3 text-sm text-ink-muted">That phase is no longer in the document.</div>;
  }
  const others = phases.filter((p) => p.id !== phase.id);

  return (
    <div className="flex flex-col h-full overflow-auto">
      <div className="p-3 border-b border-hairline space-y-3">
        <div className="text-xs text-ink-muted uppercase tracking-wide">
          Phase — {phase.steps.length} step{phase.steps.length === 1 ? "" : "s"}
        </div>
        <CommitField
          label="Name"
          value={phase.name}
          onCommit={(name) => updatePhase.mutate({ id: phase.id, body: { name } })}
        />
        <Field label="Role">
          <select
            aria-label="Role"
            value={phase.role}
            onChange={(e) => updatePhase.mutate({ id: phase.id, body: { role: e.target.value as StageRole } })}
            className={CONTROL}
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r.value || "none"} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div className="p-3 space-y-3">
        {/* The canvas' delete button always takes the steps down with the phase. This is the
            only place that offers the backend's reassign_to, so the steps can be kept. */}
        {phase.steps.length > 0 && others.length > 0 && (
          <Field label="On delete, move its steps to">
            <select
              aria-label="On delete, move its steps to"
              value={reassignTo}
              onChange={(e) => setReassignTo(e.target.value)}
              className={CONTROL}
            >
              <option value="">Delete them too</option>
              {others.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Button
          variant="danger"
          onClick={() => {
            const fate = reassignTo
              ? `move its ${phase.steps.length} step(s) to another phase`
              : `and its ${phase.steps.length} step(s)`;
            if (window.confirm(`Delete phase "${phase.name}" ${fate}?`)) {
              deletePhase.mutate({ id: phase.id, reassignTo: reassignTo || undefined });
              select(null, null);
            }
          }}
        >
          Delete this phase
        </Button>
      </div>
    </div>
  );
}
