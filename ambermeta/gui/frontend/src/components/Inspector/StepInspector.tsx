import { useDocument, useDeleteStep, useUpdateStep } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { Button, FileLabel } from "@/components/common";
import type { InputCoordsModel, PhaseModel, StepModel } from "@/types";
import { CommitField, CONTROL, Field } from "./NodeFields";

function findStep(phases: PhaseModel[], stepId: string): { phase: PhaseModel; step: StepModel } | null {
  for (const phase of phases) {
    const step = phase.steps.find((s) => s.id === stepId);
    if (step) return { phase, step };
  }
  return null;
}

/** Every step in the document, labelled "<phase> / <step>", for the input-coords ref chooser. */
function allSteps(phases: PhaseModel[]): { id: string; label: string }[] {
  return phases.flatMap((p) => p.steps.map((s) => ({ id: s.id, label: `${p.name} / ${s.name}` })));
}

/** The parsed value of a gap field, or null when it is blank or not a number. */
function parseGapField(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

export function StepInspector({ stepId }: { stepId: string }) {
  const { data: doc } = useDocument();
  const { select } = useSelection();
  const updateStep = useUpdateStep();
  const deleteStep = useDeleteStep();

  const phases = doc?.simulation.phases ?? [];
  const found = findStep(phases, stepId);
  if (!doc || !found) {
    return <div className="p-3 text-sm text-ink-muted">That step is no longer in the document.</div>;
  }
  const { phase, step } = found;
  const base = doc.base_directory;
  const ic = step.input_coords;

  const patch = (body: Parameters<typeof updateStep.mutate>[0]["body"]) =>
    updateStep.mutate({ id: step.id, body });
  const setCoords = (next: InputCoordsModel) => patch({ input_coords: next });

  return (
    <div className="flex flex-col h-full overflow-auto">
      <div className="p-3 border-b border-hairline space-y-3">
        <div className="text-xs text-ink-muted uppercase tracking-wide">Step in {phase.name}</div>
        <CommitField label="Name" value={step.name} onCommit={(name) => patch({ name })} />
        <Field label="Topology">
          <select
            aria-label="Topology"
            value={step.topology ?? ""}
            onChange={(e) => patch({ topology: e.target.value || null })}
            className={CONTROL}
          >
            <option value="">Inherit / none</option>
            {doc.simulation.topologies.map((t) => (
              <option key={t.id} value={t.id}>
                {t.path}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div className="p-3 border-b border-hairline space-y-3">
        <div className="text-xs text-ink-muted uppercase tracking-wide">Input coordinates</div>
        <Field label="Source">
          <select
            aria-label="Source"
            value={ic.source}
            onChange={(e) => {
              const source = e.target.value as InputCoordsModel["source"];
              if (source === "starting_structure") return setCoords({ source, ref: null, path: null });
              if (source === "step") return setCoords({ source, ref: ic.ref, path: null });
              setCoords({ source, ref: null, path: ic.path });
            }}
            className={CONTROL}
          >
            <option value="starting_structure">The simulation's starting structure</option>
            <option value="step">The restart of another step</option>
            <option value="path">A file on disk</option>
          </select>
        </Field>
        {ic.source === "step" && (
          <Field label="Continues from">
            <select
              aria-label="Continues from"
              value={ic.ref ?? ""}
              onChange={(e) => setCoords({ source: "step", ref: e.target.value || null, path: null })}
              className={CONTROL}
            >
              <option value="">Choose a step…</option>
              {allSteps(phases)
                .filter((s) => s.id !== step.id)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
            </select>
          </Field>
        )}
        {ic.source === "path" && (
          <>
            <CommitField
              label="Coordinates file"
              value={ic.path ?? ""}
              placeholder="/path/to/restart.rst"
              onCommit={(path) => setCoords({ source: "path", ref: null, path: path || null })}
            />
            <div className="flex min-w-0 font-mono text-xs text-ink-muted">
              <FileLabel path={ic.path} base={base} />
            </div>
          </>
        )}
      </div>

      <div className="p-3 border-b border-hairline space-y-3">
        <div className="text-xs text-ink-muted uppercase tracking-wide">Continuity</div>
        {/* The backend reads a null gap as "leave as it was", so a blank field means unchanged
            rather than cleared — the only way to drop a gap is to set it to 0. */}
        <CommitField
          label="Expected gap (ps)"
          value={step.expected_gap_ps === null ? "" : String(step.expected_gap_ps)}
          onCommit={(raw) => {
            const n = parseGapField(raw);
            if (n !== null) patch({ expected_gap_ps: n });
          }}
        />
        <CommitField
          label="Gap tolerance (ps)"
          value={step.gap_tolerance_ps === null ? "" : String(step.gap_tolerance_ps)}
          onCommit={(raw) => {
            const n = parseGapField(raw);
            if (n !== null) patch({ gap_tolerance_ps: n });
          }}
        />
        <CommitField
          label="Notes"
          multiline
          value={step.notes.join("\n")}
          onCommit={(text) => patch({ notes: text.split("\n").filter((line) => line.trim()) })}
        />
      </div>

      <div className="p-3">
        <Button
          variant="danger"
          onClick={() => {
            if (window.confirm(`Delete step "${step.name}"?`)) {
              deleteStep.mutate(step.id);
              select(null, null);
            }
          }}
        >
          Delete this step
        </Button>
      </div>
    </div>
  );
}
