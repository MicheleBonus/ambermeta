import { useState } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useSelection } from "@/state/selection";
import { useDeleteStep, useUpdateStep } from "@/api/hooks";
import { FilePicker } from "@/components/FilePicker";
import { Badge, FileLabel, GripVertical, Trash2, X } from "@/components/common";
import { useInlineRename } from "@/lib/useInlineRename";
import { useUndoOffer } from "@/lib/useUndoOffer";
import { producerOf, type StepIndex } from "@/lib/chain";
import { type SlotKind } from "./resolveDrop";
import type { StepFilesPatch, StepModel, TopologyModel } from "@/types";

/**
 * How this step gets its starting coordinates, in words.
 *
 * A chained step names the step it continues from. It used to print `input_coords.ref`
 * raw, which is an internal 8-hex-char id — so every discovered run claimed to read
 * something called "bd573ee9".
 */
function inputSourceLabel(step: StepModel, index: StepIndex): string | null {
  const ic = step.input_coords;
  if (ic.source === "starting_structure") return "starting structure";
  if (ic.source === "step") {
    // Not yet pointed at anything is a half-finished edit, not a loss — reporting a
    // missing step for both would claim data had vanished when none had.
    if (!ic.ref) return "no step chosen yet";
    const producer = producerOf(step, index);
    if (!producer) return "a step that is no longer here";
    return `restart of ${producer.name}`;
  }
  return null; // an explicit path renders as a FileLabel instead
}

const SLOT_KINDS: { kind: SlotKind; label: string; title: string }[] = [
  { kind: "mdin", label: "mdin", title: "the input script this run reads" },
  { kind: "mdout", label: "mdout", title: "the log this run writes" },
  { kind: "mdcrd", label: "mdcrd", title: "the trajectory this run writes" },
  { kind: "rst", label: "rst", title: "the restart this run writes — the next step reads it" },
];

/** A one-slot files patch. The backend clears a slot on the empty string. */
function slotPatch(kind: SlotKind, value: string): StepFilesPatch {
  const patch: StepFilesPatch = {};
  patch[kind] = value;
  return patch;
}

function FileSlot({
  stepId,
  kind,
  label,
  hint,
  value,
  base,
  onPick,
  onClear,
}: {
  stepId: string;
  kind: SlotKind;
  label: string;
  hint: string;
  value: string | null;
  base: string | null;
  onPick: () => void;
  onClear: () => void;
}) {
  // The most precise drop target on the canvas, so its hover state is the loudest one.
  const { setNodeRef, isOver } = useDroppable({ id: `slot:${stepId}:${kind}` });
  return (
    <span
      ref={setNodeRef}
      data-droppable-id={`slot:${stepId}:${kind}`}
      className={`inline-flex min-w-0 max-w-full items-baseline gap-1 px-1.5 py-0.5 rounded border text-xs font-mono text-ink-muted ${
        isOver ? "border-solid border-accent bg-accent-subtle" : "border-dashed border-hairline"
      }`}
    >
      {/* Dropping a file here still works; clicking is the no-drag way to do the same.
          An empty slot's visible text is "mdcrd: —", which tells a screen reader nothing about
          what activating it does, so the accessible name says it instead. */}
      <button
        type="button"
        onClick={onPick}
        aria-label={value ? `change ${kind}: ${value}` : `choose a ${kind} file`}
        title={hint}
        className="inline-flex min-w-0 items-baseline gap-1 text-left hover:underline"
      >
        {label}: <FileLabel path={value} base={base} />
      </button>
      {value && (
        // A sibling of the picker button, not a child of it, so clearing a slot cannot open the
        // picker on the way past — and the step's drag listeners sit on its grip, not on the body.
        <button
          type="button"
          aria-label={`clear ${kind}`}
          onClick={onClear}
          className="shrink-0 text-ink-muted hover:text-error"
        >
          <X size={10} />
        </button>
      )}
    </span>
  );
}

export function StepNode({
  step,
  topology,
  base,
  stepIndex,
}: {
  step: StepModel;
  topology?: TopologyModel;
  /** Document base directory, so file labels show a folder qualifier rather than a full path. */
  base: string | null;
  /** Every step in the document, so a chained step can name the one it continues from. */
  stepIndex: StepIndex;
}) {
  const { sel, select } = useSelection();
  // Same id in both registries: the node is a drop target (files / other steps land on it)
  // AND a drag source (grip handle) so it can be reordered or moved between phases.
  const { setNodeRef, isOver } = useDroppable({ id: `step:${step.id}` });
  const drag = useDraggable({ id: `step:${step.id}` });
  const updateStep = useUpdateStep();
  const deleteStep = useDeleteStep();
  const offerUndo = useUndoOffer();
  // Which slot's picker is open; mounting it lazily keeps the file tree unfetched
  // until someone actually asks for it.
  const [picking, setPicking] = useState<SlotKind | null>(null);
  const rename = useInlineRename(step.name, (name) => updateStep.mutate({ id: step.id, body: { name } }));
  const isSelected = sel.kind === "step" && sel.id === step.id;
  const isHmr = topology?.kind === "hmr";
  const source = inputSourceLabel(step, stepIndex);

  const setSlot = (kind: SlotKind, path: string) =>
    updateStep.mutate({ id: step.id, body: { files: slotPatch(kind, path) } });

  return (
    <div
      ref={setNodeRef}
      data-droppable-id={`step:${step.id}`}
      className={`rounded border border-hairline bg-surface px-2 py-1.5 space-y-1 ${
        isSelected ? "bg-accent-subtle" : ""
      } ${isOver ? "border-accent" : ""} ${drag.isDragging ? "opacity-50" : ""}`}
    >
      <div className="flex items-center gap-1.5">
        <span
          ref={drag.setNodeRef}
          {...drag.attributes}
          {...drag.listeners}
          aria-label={`drag step ${step.name}`}
          className="cursor-grab text-ink-muted shrink-0"
        >
          <GripVertical size={14} />
        </span>
        {rename.editing ? (
          <input
            autoFocus
            aria-label={`rename step ${step.name}`}
            value={rename.value}
            onChange={(e) => rename.change(e.target.value)}
            onKeyDown={rename.keyDown}
            onBlur={rename.blur}
            className="min-w-0 flex-1 px-1 py-0.5 border border-accent rounded bg-app text-sm text-ink"
          />
        ) : (
          // F2 as well as double-click: a double-click is unreachable from the keyboard, which
          // left renaming impossible without a mouse. Enter/Space still select, as for any button.
          <button
            type="button"
            onClick={() => select("step", step.id)}
            onDoubleClick={rename.start}
            onKeyDown={(e) => {
              if (e.key === "F2") {
                e.preventDefault();
                rename.start();
              }
            }}
            aria-keyshortcuts="F2"
            title="Press F2 or double-click to rename"
            className="text-left text-sm text-ink hover:underline"
          >
            {step.name}
          </button>
        )}
        {/* No confirm dialog: the removal is reported with an Undo offer instead, which is
            cheaper when the click was intended and just as recoverable when it was not. */}
        <button
          type="button"
          aria-label={`delete step ${step.name}`}
          title="Delete this step"
          onClick={() =>
            deleteStep.mutate(step.id, {
              onSuccess: () => {
                // Otherwise the inspector sits on a node that is gone, showing a dead end.
                if (isSelected) select(null, null);
                offerUndo(`Deleted step “${step.name}”`);
              },
            })
          }
          className="ml-auto shrink-0 text-ink-muted hover:text-error"
        >
          <Trash2 size={14} />
        </button>
      </div>
      {/* The topology was the one file on a step that could only be changed from the
          inspector — the three run-file slots below have carried a clear button all along. */}
      <div className="flex items-center gap-1 flex-wrap min-w-0">
        <span className={`inline-flex min-w-0 items-baseline gap-1 font-mono text-xs ${isHmr ? "text-accent" : "text-ink-secondary"}`}>
          <span className="shrink-0">▸</span>
          {topology ? <FileLabel path={topology.path} base={base} /> : <span>no topology</span>}
        </span>
        {topology && (
          <button
            type="button"
            aria-label="clear topology"
            title="Run this step against no topology"
            onClick={() => updateStep.mutate({ id: step.id, body: { topology: null } })}
            className="shrink-0 text-ink-muted hover:text-error"
          >
            <X size={10} />
          </button>
        )}
        {isHmr && <Badge tone="neutral">HMR</Badge>}
      </div>
      {/* What this run starts from. A dropped restart file puts an absolute path here, and a
          path has no break opportunities: rendered plainly it overflows the step card and the
          phase section around it. */}
      <div
        title="the coordinates this run starts from"
        className="flex min-w-0 flex-wrap items-baseline gap-x-1 font-mono text-xs text-ink-muted"
      >
        <span className="shrink-0">◂</span>
        {source === null ? (
          <FileLabel path={step.input_coords.path} base={base} />
        ) : (
          <>
            <span className="shrink-0">{source}</span>
            {step.resolved_input_coords ? (
              <>
                <span className="shrink-0">·</span>
                <FileLabel path={step.resolved_input_coords} base={base} />
              </>
            ) : (
              // The link is intact but points at a step that never named its restart, so
              // there is no file to hand over. Saying so beats an empty line.
              <span className="shrink-0 text-warning">· no file yet</span>
            )}
          </>
        )}
      </div>
      <div className="flex items-center gap-1.5 flex-wrap min-w-0">
        {SLOT_KINDS.map((s) => (
          <FileSlot
            key={s.kind}
            stepId={step.id}
            kind={s.kind}
            label={s.label}
            hint={s.title}
            value={step[s.kind]}
            base={base}
            onPick={() => setPicking(s.kind)}
            onClear={() => setSlot(s.kind, "")}
          />
        ))}
      </div>
      {picking && (
        <FilePicker
          open
          mode="open"
          // A restart is typed `inpcrd` by the file browser (.rst/.rst7/.ncrst/.restrt all
          // land there), so the picker filters on that rather than on the slot's own name.
          filterType={picking === "rst" ? "inpcrd" : picking}
          title={`Choose a ${picking} file for ${step.name}`}
          onPick={({ path }) => {
            setSlot(picking, path);
            setPicking(null);
          }}
          onClose={() => setPicking(null)}
        />
      )}
    </div>
  );
}
