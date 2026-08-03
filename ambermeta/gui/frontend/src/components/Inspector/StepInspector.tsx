import { useState } from "react";
import { useDocument, useDeleteStep, useUpdateStep } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { Button, FileLabel } from "@/components/common";
import { useUndoOffer } from "@/lib/useUndoOffer";
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

/**
 * What a gap field's text means: a number to store, `null` to clear it, or "no opinion"
 * for text that is not a number at all (so a half-typed "1e" does not wipe the value).
 */
function parseGapField(raw: string): { value: number | null } | null {
  const trimmed = raw.trim();
  if (!trimmed) return { value: null };
  const n = Number(trimmed);
  return Number.isFinite(n) ? { value: n } : null;
}

export function StepInspector({ stepId }: { stepId: string }) {
  const { data: doc } = useDocument();
  const { select } = useSelection();
  const updateStep = useUpdateStep();
  const deleteStep = useDeleteStep();
  const offerUndo = useUndoOffer();
  // Which step the user has asked to chain but not yet given a producer for. Held here
  // rather than sent, because the server refuses a "continues from" that names nobody:
  // it resolves to no coordinates while the chain reads as intact. Keyed by step id so
  // the half-made choice does not follow the selection onto a different step — the
  // inspector is not remounted when the selection changes.
  const [chaining, setChaining] = useState<string | null>(null);

  const phases = doc?.simulation.phases ?? [];
  const found = findStep(phases, stepId);
  if (!doc || !found) {
    return <div className="p-3 text-sm text-ink-muted">That step is no longer in the document.</div>;
  }
  const { phase, step } = found;
  const base = doc.base_directory;
  const ic = step.input_coords;
  // Who would be affected by changing this step's restart — the other half of the link.
  const consumers = phases
    .flatMap((p) => p.steps)
    .filter((s) => s.input_coords.source === "step" && s.input_coords.ref === step.id);

  const patch = (body: Parameters<typeof updateStep.mutate>[0]["body"]) =>
    updateStep.mutate({ id: step.id, body });
  const setCoords = (next: InputCoordsModel) => patch({ input_coords: next });
  // The chooser is open once the source is "step", and also while the user is on the way
  // there — otherwise picking that source would have nothing to show and no way to commit.
  const choosing = ic.source === "step" || chaining === step.id;

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
            value={choosing ? "step" : ic.source}
            onChange={(e) => {
              const source = e.target.value as InputCoordsModel["source"];
              if (source === "step" && !ic.ref) {
                // Nothing to send yet: the link is written when the producer is picked.
                return setChaining(step.id);
              }
              setChaining(null);
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
        {choosing && (
          <Field label="Continues from">
            <select
              aria-label="Continues from"
              value={ic.ref ?? ""}
              onChange={(e) => {
                // The placeholder is not a choice. Unlinking is what the Source control
                // above is for; a link naming nobody is refused, not stored.
                if (!e.target.value) return;
                setChaining(null);
                setCoords({ source: "step", ref: e.target.value, path: null });
              }}
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
        {ic.source !== "path" && (
          // Resolved by the server, so the panel says which file the choice above actually
          // lands on rather than leaving the user to work it out from the chain.
          <div className="flex min-w-0 items-baseline gap-1 font-mono text-xs text-ink-muted">
            <span className="shrink-0">reads:</span>
            {step.resolved_input_coords
              ? <FileLabel path={step.resolved_input_coords} base={base} />
              : <span className="text-warning">nothing yet</span>}
          </div>
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
        <div className="text-xs text-ink-muted uppercase tracking-wide">Output restart</div>
        {/* Stored here, on the step that writes it, because this is the file the next step
            reads. Blank it to say this run produces no restart. */}
        <CommitField
          label="Restart written (rst)"
          placeholder="equil/02_nvt.rst"
          value={step.rst ?? ""}
          onCommit={(path) => patch({ files: { rst: path } })}
        />
        <div className="text-xs text-ink-muted">
          {consumers.length === 0
            ? "No step continues from this one."
            : `Read by ${consumers.map((s) => s.name).join(", ")}.`}
        </div>
      </div>

      <div className="p-3 border-b border-hairline space-y-3">
        <div className="text-xs text-ink-muted uppercase tracking-wide">Continuity</div>
        {/* Blanking a field clears it. It used to send nothing at all, so the box looked
            empty until the next document push put the old number back. */}
        <CommitField
          label="Expected gap (ps)"
          placeholder="none"
          value={step.expected_gap_ps === null ? "" : String(step.expected_gap_ps)}
          onCommit={(raw) => {
            const parsed = parseGapField(raw);
            if (parsed) patch({ expected_gap_ps: parsed.value });
          }}
        />
        <CommitField
          label="Gap tolerance (ps)"
          placeholder="none"
          value={step.gap_tolerance_ps === null ? "" : String(step.gap_tolerance_ps)}
          onCommit={(raw) => {
            const parsed = parseGapField(raw);
            if (parsed) patch({ gap_tolerance_ps: parsed.value });
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
        {/* Same bargain as the canvas trash button: no confirm, an Undo offer instead. */}
        <Button
          variant="danger"
          onClick={() =>
            deleteStep.mutate(step.id, {
              onSuccess: () => {
                select(null, null);
                offerUndo(`Deleted step “${step.name}”`);
              },
            })
          }
        >
          Delete this step
        </Button>
      </div>
    </div>
  );
}
