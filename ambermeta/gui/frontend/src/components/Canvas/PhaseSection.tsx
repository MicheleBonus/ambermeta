import { useState, type ReactNode } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useSelection } from "@/state/selection";
import { useCreateStep, useDeletePhase, useUpdatePhase } from "@/api/hooks";
import { ChevronDown, ChevronRight, GripVertical, Plus, Trash2 } from "@/components/common";
import { ROLE_OPTIONS } from "@/lib/roles";
import { linkBetween, producerOf, type StepIndex } from "@/lib/chain";
import { FanOutNote, LineageBand } from "./LineageBand";
import { useInlineRename } from "@/lib/useInlineRename";
import { useUndoOffer } from "@/lib/useUndoOffer";
import type { PhaseModel, StageRole, StepModel, Suggestion, TopologyModel } from "@/types";
import { StepNode } from "./StepNode";
import { ContinuityArrow, MissingRunGhost, parseGap } from "./ContinuityArrow";
import { useSuggestions } from "@/components/Suggestions/suggestionsContext";

const COLLAPSE_THRESHOLD = 6;

function numericBase(name: string): string {
  return name.replace(/[-_.]?\d+$/, "");
}

/**
 * The base as the server spells it. `protocol.detect_sequence_gaps` drops the directory
 * before it counts a numbered family, because two members of one experiment number their
 * runs on the same scale wherever they live; a group's base keeps the directory so two
 * members are never drawn as one band. Both are right, and until they were reconciled
 * every missing-run ghost in a multi-directory tree was silently dropped on the mismatch.
 */
function serverBase(base: string): string {
  return base.slice(base.lastIndexOf("/") + 1);
}

function stepNumber(name: string): number {
  const m = name.match(/(\d+)$/);
  return m ? parseInt(m[1], 10) : Number.POSITIVE_INFINITY;
}

/** Width (digit count) of the trailing numeric suffix, e.g. "prod_0001" -> 4. */
function numWidth(name: string): number {
  const m = name.match(/(\d+)$/);
  return m ? m[1].length : 0;
}

/**
 * The character this band puts between a base and its index — "_" for `prod_0001`, "." for
 * `prod.0001`, "" for `prod0001`.
 *
 * A ghost is a filename the user is being told to go and look for, so spelling it the way
 * the runs beside it are spelled is the whole of its usefulness. It was hardcoded to "_",
 * which was invisible until the server learned to detect dot-numbered families at all;
 * before that a dot-numbered band produced no findings and so no ghosts to misspell.
 */
function numSeparator(names: string[]): string {
  for (const name of names) {
    const m = name.match(/([-_.]?)\d+$/);
    if (m) return m[1];
  }
  return "_";
}

type StepGroup = { id: string; base: string; lineage: string | null; steps: StepModel[] };

/**
 * Consecutive steps sharing a numeric base AND a lineage become one collapsible group. Each
 * group carries the id of its first step: `base` is not unique — two non-adjacent runs can share
 * one ("step", "min", "step") — so keying React children or the collapse set by it collides, and
 * one group's toggle would expand the other.
 *
 * The lineage is part of the break so a group always belongs to exactly one member, which is what
 * lets its missing-run ghosts be matched: a finding is scoped to `(lineage, base)` and a band that
 * straddled two members could not be matched against either.
 */
function groupSteps(steps: StepModel[]): StepGroup[] {
  const groups: StepGroup[] = [];
  for (const step of steps) {
    const base = numericBase(step.name);
    const last = groups[groups.length - 1];
    if (last && last.base === base && last.lineage === step.lineage) {
      last.steps.push(step);
    } else {
      groups.push({ id: step.id, base, lineage: step.lineage, steps: [step] });
    }
  }
  return groups;
}

type GhostItem = { id: string; name: string; num: number };

/** Ghost nodes for a numbered-sequence group, derived from the structured
 * `lineage`/`base`/`missing` fields of missing_run suggestions (no free-text parsing).
 * Matched on the server's base, drawn with the group's, so the ghost sits in one member's
 * band and reads like the runs beside it. */
function ghostsForGroup(group: StepGroup, width: number, suggestions: Suggestion[]): GhostItem[] {
  const out: GhostItem[] = [];
  const sep = numSeparator(group.steps.map((s) => s.name));
  for (const s of suggestions) {
    if (s.kind !== "missing_run" || s.base !== serverBase(group.base) || !s.missing) continue;
    if ((s.lineage ?? null) !== group.lineage) continue;
    for (const idx of s.missing) {
      out.push({
        id: `${s.id}:${idx}`,
        name: `${group.base}${sep}${String(idx).padStart(width, "0")}`,
        num: idx,
      });
    }
  }
  return out;
}

/** The continuity-gap suggestion (if any) that precedes step `stepId`, and its
 * parsed magnitude label (e.g. "20 ps"). */
function gapForStep(stepId: string, suggestions: Suggestion[]): string | null {
  const s = suggestions.find((s) => s.kind === "continuity_gap" && s.step_id === stepId);
  if (!s) return null;
  return parseGap(s.evidence) ?? parseGap(s.title);
}

type SequenceItem =
  | { kind: "step"; num: number; step: StepModel }
  | { kind: "ghost"; num: number; id: string; name: string };

/** One group's render list, with the step that precedes each item anywhere in the phase. */
interface RenderedGroup {
  group: StepGroup;
  items: { item: SequenceItem; above: StepModel | null }[];
}

/**
 * Lay the phase out as one sequence, then hand each item the step above it.
 *
 * `above` is threaded ACROSS group boundaries on purpose. Groups are formed by a shared
 * numeric base, so `01_min`, `02_nvt`, `03_npt` are three groups of one — exactly what an
 * equilibration folder looks like — and an arrow drawn only within a group would never
 * appear there at all. A collapsed group still advances the sequence, so the arrow that
 * follows it points at the right step.
 */
function layOutPhase(groups: StepGroup[], suggestions: Suggestion[]): RenderedGroup[] {
  let previous: StepModel | null = null;
  let previousLineage: string | null | undefined = undefined;
  // One finding, one set of ghosts. `serverBase` drops the directory, so two bands in
  // different directories that share a base and a lineage both match the same suggestion —
  // reachable whenever the layout was too ambiguous to tag, since untagged bands all carry
  // `lineage: null`. Drawing it in each would show more missing runs than core reported,
  // which is the one thing this view must never do.
  const drawn = new Set<string>();
  return groups.map((group) => {
    const width = Math.max(0, ...group.steps.map((s) => numWidth(s.name)));
    const ghosts = ghostsForGroup(group, width, suggestions).filter((gh) => {
      if (drawn.has(gh.id)) return false;
      drawn.add(gh.id);
      return true;
    });
    const ordered: SequenceItem[] = [
      ...group.steps.map((step): SequenceItem => ({ kind: "step", num: stepNumber(step.name), step })),
      ...ghosts.map((gh): SequenceItem => ({ kind: "ghost", num: gh.num, id: gh.id, name: gh.name })),
    ].sort((a, b) => a.num - b.num);
    // The one place a lineage boundary breaks the thread. Keyed on the LINEAGE changing,
    // not on the group changing: `01_min`, `02_nvt`, `03_npt` are three groups of one --
    // an equilibration folder -- and an arrow drawn only within a group would vanish
    // there entirely. Between two members there is no arrow to draw, because there is no
    // claim to make: what precedes a member's first run in document order is another
    // member's last run, and that adjacency means nothing.
    if (previousLineage !== undefined && previousLineage !== group.lineage) previous = null;
    previousLineage = group.lineage;
    const items = ordered.map((item) => {
      const above = previous;
      if (item.kind === "step") previous = item.step;
      return { item, above };
    });
    return { group, items };
  });
}

/** Consecutive groups that belong to one member, in document order. */
interface Band { lineage: string | null; groups: RenderedGroup[] }

/**
 * Fold the laid-out groups into bands, one per contiguous run of a member.
 *
 * Contiguous rather than gathered: `discover` emits phase-major documents, so a phase
 * holds each member's same-role runs in turn and one pass produces one band per member.
 * A hand-built document that interleaves members would show a member twice, which is what
 * its own order says and is not this view's to silently rearrange.
 */
function bandsOf(rendered: RenderedGroup[]): Band[] {
  const bands: Band[] = [];
  for (const entry of rendered) {
    const last = bands[bands.length - 1];
    if (last && last.lineage === entry.group.lineage) last.groups.push(entry);
    else bands.push({ lineage: entry.group.lineage, groups: [entry] });
  }
  return bands;
}

/**
 * The one step every band in this phase branches from, when they all branch from one.
 *
 * Read off the bands' first steps rather than off the whole phase: the claim being made is
 * "these members share an origin", and a producer that only some of them read is not that.
 * Silent unless at least two bands agree, and silent for an untagged phase, where a single
 * band's producer is just the step before it.
 */
function fanOutOf(bands: Band[], stepIndex: StepIndex): { name: string; count: number } | null {
  const heads = bands
    .filter((b) => b.lineage !== null)
    .map((b) => b.groups[0]?.group.steps[0])
    .filter((s): s is StepModel => Boolean(s));
  if (heads.length < 2) return null;
  const producers = heads.map((s) => producerOf(s, stepIndex));
  const first = producers[0];
  if (!first || !producers.every((p) => p && p.id === first.id)) return null;
  return { name: first.name, count: heads.length };
}

/** A band with its header, or the steps bare when nothing in the phase is tagged. */
function MaybeBand({ show, lineage, steps, children }: {
  show: boolean; lineage: string | null; steps: StepModel[]; children: ReactNode;
}) {
  if (!show) return <div className="space-y-1.5">{children}</div>;
  return <LineageBand lineage={lineage} steps={steps}>{children}</LineageBand>;
}

/** Sentinel for "the steps of this phase do not agree on a topology".
 *  Topology ids are hex slices of a uuid4, so this can never collide with one. */
const MIXED = "__mixed__";

/**
 * The topology every step of the phase holds, `null` if they all hold none, or MIXED if
 * they disagree. A phase has no topology of its own — it is a way of setting all of its
 * steps at once — so this is the only honest thing the phase-level control can display.
 */
function effectiveTopologyOf(phase: PhaseModel): string | null | typeof MIXED {
  if (phase.steps.length === 0) return null;
  const first = phase.steps[0].topology;
  return phase.steps.every((s) => s.topology === first) ? first : MIXED;
}

export function PhaseSection({
  phase,
  topologies,
  base,
  stepIndex,
}: {
  phase: PhaseModel;
  topologies: TopologyModel[];
  /** Document base directory, drilled down so step labels can relativize paths. */
  base: string | null;
  /** Every step in the document: the restart chain crosses phase boundaries. */
  stepIndex: StepIndex;
}) {
  const { sel, select } = useSelection();
  const updatePhase = useUpdatePhase();
  const createStep = useCreateStep();
  const deletePhase = useDeletePhase();
  const offerUndo = useUndoOffer();
  // Drop target (files / steps land on it) AND drag source (grip) so phases can be reordered.
  const { setNodeRef, isOver } = useDroppable({ id: `phase:${phase.id}` });
  const drag = useDraggable({ id: `phase:${phase.id}` });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const rename = useInlineRename(phase.name, (name) => updatePhase.mutate({ id: phase.id, body: { name } }));
  const isSelected = sel.kind === "phase" && sel.id === phase.id;
  const suggestions = useSuggestions();
  const effectiveTopology = effectiveTopologyOf(phase);
  const bands = bandsOf(layOutPhase(groupSteps(phase.steps), suggestions));
  // No band chrome for a document that declares nothing: an untagged phase renders exactly
  // as it did before members existed, which is the guarantee every path in this feature
  // owes the manifests that came before it.
  const showBands = bands.some((b) => b.lineage !== null);
  const fanOut = fanOutOf(bands, stepIndex);

  return (
    // The droppable covers the whole section -- header AND step list -- so a file dropped
    // anywhere on the phase lands on it. The grip below keeps the section draggable.
    <section
      ref={setNodeRef}
      data-droppable-id={`phase:${phase.id}`}
      className={`border-l-4 rounded mb-3 ${isOver ? "border-accent bg-accent-subtle" : "border-hairline bg-surface"} ${
        drag.isDragging ? "opacity-50" : ""
      }`}
    >
      {/* Wraps rather than overflows: the header now carries a name, a role, a topology
          chooser and two actions. */}
      <header className={`flex flex-wrap items-center gap-2 px-3 py-2 ${isSelected ? "bg-accent-subtle" : ""}`}>
        <span
          ref={drag.setNodeRef}
          {...drag.attributes}
          {...drag.listeners}
          aria-label={`drag phase ${phase.name}`}
          className="cursor-grab text-ink-muted shrink-0"
        >
          <GripVertical size={14} />
        </span>
        {rename.editing ? (
          <input
            autoFocus
            aria-label={`rename phase ${phase.name}`}
            value={rename.value}
            onChange={(e) => rename.change(e.target.value)}
            onKeyDown={rename.keyDown}
            onBlur={rename.blur}
            className="min-w-0 px-1 py-0.5 border border-accent rounded bg-app text-sm font-medium text-ink"
          />
        ) : (
          // F2 as well as double-click: a double-click is unreachable from the keyboard, which
          // left renaming impossible without a mouse. Enter/Space still select, as for any button.
          <button
            type="button"
            onClick={() => select("phase", phase.id)}
            onDoubleClick={rename.start}
            onKeyDown={(e) => {
              if (e.key === "F2") {
                e.preventDefault();
                rename.start();
              }
            }}
            aria-keyshortcuts="F2"
            title="Press F2 or double-click to rename"
            className="text-sm font-medium text-ink hover:underline"
          >
            {phase.name}
          </button>
        )}
        {/* Controlled off the document, unlike the topology chooser below: this one
            reports the phase's current role and is the one place the role is shown --
            a Badge beside it would only repeat the value the select already displays. */}
        <label className="ml-auto text-xs text-ink-muted flex items-center gap-1">
          role
          <select
            aria-label={`set role for ${phase.name}`}
            value={phase.role}
            className="px-1 py-0.5 border border-hairline rounded bg-app text-xs text-ink"
            onChange={(e) => updatePhase.mutate({ id: phase.id, body: { role: e.target.value as StageRole } })}
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r.value || "none"} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        {/* Controlled off the document, like the role select beside it. It used to be a
            write-only action menu that reset itself to "Choose…" on every change, so the one
            control that reports a phase's topology never showed the value it had just
            applied. It now reads back what its steps hold, and clears them too. */}
        <label className="text-xs text-ink-muted flex items-center gap-1">
          topology
          <select
            aria-label={`set topology for ${phase.name}`}
            value={effectiveTopology === MIXED ? MIXED : (effectiveTopology ?? "")}
            // The control writes through to the steps, so with none to write to it would
            // accept a choice, change nothing, and snap back — the same flicker in a new
            // place. Saying why up front beats appearing to work.
            disabled={phase.steps.length === 0}
            title={phase.steps.length === 0
              ? "Add a step first — a phase sets the topology of its steps"
              : "Sets the topology of every step in this phase"}
            className="max-w-[14rem] px-1 py-0.5 border border-hairline rounded bg-app text-xs text-ink disabled:opacity-50"
            onChange={(e) =>
              updatePhase.mutate({ id: phase.id, body: { topology: e.target.value || null } })
            }
          >
            <option value="">— none —</option>
            {effectiveTopology === MIXED && (
              // Only reachable as a report, never as a choice: picking any real entry is what
              // resolves the mix, and re-picking "Mixed" would mean nothing.
              <option value={MIXED} disabled>
                Mixed
              </option>
            )}
            {topologies.map((t) => (
              <option key={t.id} value={t.id}>
                {t.path}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          aria-label={`add step to ${phase.name}`}
          title="Add a step"
          // Numbered, so two clicks do not leave two indistinguishable steps both called "step".
          onClick={() => createStep.mutate({ phaseId: phase.id, body: { name: `step ${phase.steps.length + 1}` } })}
          className="shrink-0 text-ink-muted hover:text-ink"
        >
          <Plus size={14} />
        </button>
        <button
          type="button"
          aria-label={`delete phase ${phase.name}`}
          title="Delete this phase"
          // A phase takes its steps down with it, so an occupied one still asks first —
          // that is a lot of work to lose to a stray click. An empty phase just goes, with
          // the same Undo offer every other removal gets.
          onClick={() => {
            if (phase.steps.length > 0 &&
                !window.confirm(`Delete phase “${phase.name}” and its ${phase.steps.length} step(s)?`)) {
              return;
            }
            deletePhase.mutate({ id: phase.id }, {
              onSuccess: () => {
                if (isSelected) select(null, null);
                offerUndo(`Deleted phase “${phase.name}”`);
              },
            });
          }}
          className="shrink-0 text-ink-muted hover:text-error"
        >
          <Trash2 size={14} />
        </button>
      </header>
      <div className="px-3 pb-2 space-y-1.5">
        {fanOut && <FanOutNote producerName={fanOut.name} count={fanOut.count} />}
        {bands.map((band, bandIndex) => (
          <MaybeBand
            key={`${band.lineage ?? "untagged"}:${bandIndex}`}
            show={showBands}
            lineage={band.lineage}
            steps={band.groups.flatMap((entry) => entry.group.steps)}
          >
            {band.groups.map(({ group: g, items }) =>
          g.steps.length >= COLLAPSE_THRESHOLD && !expanded.has(g.id) ? (
            <div
              key={g.id}
              className="flex items-center gap-1 px-2 py-1.5 border border-dashed border-hairline rounded text-sm text-ink-muted"
            >
              <button
                type="button"
                onClick={() => setExpanded((s) => new Set(s).add(g.id))}
                className="flex items-center gap-1"
              >
                <ChevronRight size={14} />
                {g.base} × {g.steps.length} steps
              </button>
            </div>
          ) : (
            <div key={g.id} className="space-y-1.5">
              {g.steps.length >= COLLAPSE_THRESHOLD && (
                <button
                  type="button"
                  onClick={() =>
                    setExpanded((s) => {
                      const next = new Set(s);
                      next.delete(g.id);
                      return next;
                    })
                  }
                  className="flex items-center gap-1 text-xs text-ink-muted"
                >
                  <ChevronDown size={14} />
                  {g.base} × {g.steps.length} steps
                </button>
              )}
              {items.map(({ item, above }) => (
                <div key={item.kind === "step" ? item.step.id : `ghost:${item.id}`}>
                  {above && (
                    <ContinuityArrow
                      gap={item.kind === "step" ? gapForStep(item.step.id, suggestions) : null}
                      // Labelled only when these two really are the producer and consumer of
                      // one restart; a ghost or an unrelated neighbour gets a bare arrow.
                      link={item.kind === "step" ? linkBetween(above, item.step, stepIndex) : null}
                      base={base}
                    />
                  )}
                  {item.kind === "step" ? (
                    <StepNode
                      step={item.step}
                      topology={topologies.find((t) => t.id === item.step.topology)}
                      base={base}
                      stepIndex={stepIndex}
                    />
                  ) : (
                    <MissingRunGhost name={item.name} />
                  )}
                </div>
              ))}
            </div>
          ),
        )}
          </MaybeBand>
        ))}
        {/* Makes the section-wide drop target discoverable: the whole phase accepts the file,
            this row is just where the affordance is spelled out. */}
        <div className="px-2 py-1.5 rounded border border-dashed border-hairline text-center text-xs text-ink-muted">
          drop a file here to add a step
        </div>
      </div>
    </section>
  );
}
