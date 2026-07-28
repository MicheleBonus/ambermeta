import { useState } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useSelection } from "@/state/selection";
import { useDeleteStep, useUpdateStep } from "@/api/hooks";
import { FilePicker } from "@/components/FilePicker";
import { Badge, FileLabel, GripVertical, Trash2, X } from "@/components/common";
import { useInlineRename } from "@/lib/useInlineRename";
import { type SlotKind } from "./resolveDrop";
import type { StepFilesPatch, StepModel, TopologyModel } from "@/types";

/** The plain-text input-coordinates label, for the two sources that are not a path. */
function inputSourceLabel(step: StepModel): string | null {
  const ic = step.input_coords;
  if (ic.source === "starting_structure") return "starting structure";
  if (ic.source === "step") return ic.ref ?? "?";
  return null; // a path renders as a FileLabel instead
}

const SLOT_KINDS: { kind: SlotKind; label: string }[] = [
  { kind: "mdin", label: "mdin" },
  { kind: "mdout", label: "mdout" },
  { kind: "mdcrd", label: "mdcrd" },
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
  value,
  base,
  onPick,
  onClear,
}: {
  stepId: string;
  kind: SlotKind;
  label: string;
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
        title={`Choose a ${kind} file`}
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
}: {
  step: StepModel;
  topology?: TopologyModel;
  /** Document base directory, so file labels show a folder qualifier rather than a full path. */
  base: string | null;
}) {
  const { sel, select } = useSelection();
  // Same id in both registries: the node is a drop target (files / other steps land on it)
  // AND a drag source (grip handle) so it can be reordered or moved between phases.
  const { setNodeRef, isOver } = useDroppable({ id: `step:${step.id}` });
  const drag = useDraggable({ id: `step:${step.id}` });
  const updateStep = useUpdateStep();
  const deleteStep = useDeleteStep();
  // Which slot's picker is open; mounting it lazily keeps the file tree unfetched
  // until someone actually asks for it.
  const [picking, setPicking] = useState<SlotKind | null>(null);
  const rename = useInlineRename(step.name, (name) => updateStep.mutate({ id: step.id, body: { name } }));
  const isSelected = sel.kind === "step" && sel.id === step.id;
  const isHmr = topology?.kind === "hmr";

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
        <button
          type="button"
          aria-label={`delete step ${step.name}`}
          onClick={() => {
            if (window.confirm(`Delete step "${step.name}"?`)) deleteStep.mutate(step.id);
          }}
          className="ml-auto shrink-0 text-ink-muted hover:text-error"
        >
          <Trash2 size={14} />
        </button>
      </div>
      <div className="flex items-center gap-1 flex-wrap min-w-0">
        <span className={`inline-flex min-w-0 items-baseline gap-1 font-mono text-xs ${isHmr ? "text-accent" : "text-ink-secondary"}`}>
          ▸ {topology ? <FileLabel path={topology.path} base={base} /> : "no topology"}
        </span>
        {isHmr && <Badge tone="neutral">HMR</Badge>}
      </div>
      {/* A dropped restart file puts an absolute path here, and a path has no break opportunities:
          rendered plainly it overflows the step card and the phase section around it. */}
      <div className="flex min-w-0 items-baseline gap-1 font-mono text-xs text-ink-muted">
        <span className="shrink-0">◂</span>
        {inputSourceLabel(step) ?? <FileLabel path={step.input_coords.path} base={base} />}
      </div>
      <div className="flex items-center gap-1.5 flex-wrap min-w-0">
        {SLOT_KINDS.map((s) => (
          <FileSlot
            key={s.kind}
            stepId={step.id}
            kind={s.kind}
            label={s.label}
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
          filterType={picking}
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
