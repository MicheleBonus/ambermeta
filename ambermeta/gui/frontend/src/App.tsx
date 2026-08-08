import { useEffect, useState } from "react";
import {
  DndContext, DragOverlay, PointerSensor, useSensor, useSensors,
  type DragEndEvent, type DragStartEvent,
} from "@dnd-kit/core";
import { SelectionProvider } from "@/state/selection";
import { ResizeHandle, Toaster, useAnyModalOpen } from "@/components/common";
import { usePersistentSize } from "@/lib/usePersistentSize";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useUndoShortcuts } from "@/lib/useUndoShortcuts";
import { guessTopologyKind } from "@/lib/topology";
import { stemName } from "@/lib/format";
import { pushToast } from "@/lib/toast";
import {
  useDocument, useAssign, useReorderSteps, useMoveStep, useReorderPhases,
  useCreatePhase, useCreateStep, useUpdateStep,
  useOpen, useSave, useDiscover, useValidate, useUndo, useRedo, useInferLineages,
} from "@/api/hooks";
import { TopBar } from "@/components/TopBar/TopBar";
import { DiscoverModal } from "@/components/TopBar/DiscoverModal";
import { ExportModal } from "@/components/TopBar/ExportModal";
import { PlanModal } from "@/components/TopBar/PlanModal";
import { ValidationPanel } from "@/components/TopBar/ValidationPanel";
import { FilePicker } from "@/components/FilePicker/FilePicker";
import { FilePanel } from "@/components/FilePanel/FilePanel";
import { Canvas } from "@/components/Canvas/Canvas";
import { ProposalStrip } from "@/components/Canvas/ProposalStrip";
import { SuggestionsContext } from "@/components/Suggestions/suggestionsContext";
import { Inspector } from "@/components/Inspector/Inspector";
import { resolveDrop, type SlotKind } from "@/components/Canvas/resolveDrop";
import { canvasCollisionDetection } from "@/components/Canvas/dropSpecificity";
import { DragChip, type ActiveDrag } from "@/components/Canvas/DragChip";
import { reorderIds } from "@/components/Canvas/reorderIds";
import type { FileType, LineageProposal, StepCreatePayload, Suggestion } from "@/types";

/** A create-step body naming the step after the file that fills one of its slots. */
function stepFromFile(path: string, slot: SlotKind): StepCreatePayload {
  const body: StepCreatePayload = { name: stemName(path) };
  body[slot] = path;
  return body;
}

export default function App() {
  const [filesW, setFilesW] = usePersistentSize("files-w", 280);
  const [inspW, setInspW] = usePersistentSize("insp-w", 360);
  const { data: doc } = useDocument();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  const assign = useAssign();
  const reorderSteps = useReorderSteps();
  const moveStep = useMoveStep();
  const reorderPhases = useReorderPhases();
  const createPhase = useCreatePhase();
  const createStep = useCreateStep();
  const updateStep = useUpdateStep();
  const undo = useUndo();
  const redo = useRedo();
  const open = useOpen();
  const save = useSave();
  const discover = useDiscover();
  const validate = useValidate();
  const inferLineages = useInferLineages();

  const [picker, setPicker] = useState<"open" | "save" | null>(null);
  const [discoverOpen, setDiscoverOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [validateOpen, setValidateOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  // One field, not two booleans (`proposal` + `mode` held apart): the strip needs both or
  // neither, and a pair of independent setState calls invites a render where one has
  // updated and the other has not -- ProposalStrip would then either mount without a
  // proposal (its prop is non-nullable, so this misrenders rather than type-checks) or
  // stay closed with a proposal already sitting in state.
  const [strip, setStrip] = useState<{ proposal: LineageProposal; mode: "proposed" | "manual" } | null>(null);
  const [drag, setDrag] = useState<ActiveDrag | null>(null);
  const modalOpen = useAnyModalOpen();

  useEffect(() => {
    if (!doc) return;
    validate.mutate(undefined, { onSuccess: (report) => setSuggestions(report.suggestions) });
    // Re-validate whenever the document identity changes: on load and after every mutation
    // (setDocument writes a new object into the one ["document"] cache entry). This is the
    // single shared source of truth for suggestions -- both the canvas and the tray read it
    // via SuggestionsContext.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc]);

  const onDragStart = (e: DragStartEvent) => {
    const data = e.active.data.current as { fileType?: FileType; path?: string } | undefined;
    setDrag({ id: String(e.active.id), fileType: data?.fileType, path: data?.path });
  };

  const onDragEnd = (e: DragEndEvent) => {
    setDrag(null);
    // The dragged file's type decides where it lands: an .mdin dropped on a step fills that
    // step's mdin slot rather than becoming its topology (see resolveDrop).
    const fileType = e.active.data.current?.fileType as FileType | undefined;
    const a = resolveDrop(String(e.active.id), e.over ? String(e.over.id) : null, fileType);
    if (!a) return;
    // The target lit up under the pointer, so a drop it cannot use owes the user a reason
    // rather than the silence of an early return.
    if (a.type === "rejected") return void pushToast(a.reason, "warning");
    if (!doc) return;
    switch (a.type) {
      case "pool":
        return void assign.mutate({ path: a.path, target_type: "pool", kind: guessTopologyKind(a.path) });
      case "starting":
        return void assign.mutate({ path: a.path, target_type: "starting_structure" });
      case "step_slot":
        return void assign.mutate({ path: a.path, target_type: "step_slot", target_id: a.stepId, slot: a.kind });
      case "step_topology":
        return void assign.mutate({ path: a.path, target_type: "step_topology", target_id: a.stepId });
      case "phase_topology":
        return void assign.mutate({ path: a.path, target_type: "phase_topology", target_id: a.phaseId });
      case "step_input_coords":
        return void updateStep.mutate({
          id: a.stepId,
          body: { input_coords: { source: "path", ref: null, path: a.path } },
        });
      case "create_step_in_phase":
        return void createStep.mutate({ phaseId: a.phaseId, body: stepFromFile(a.path, a.slot) });
      case "create_step_with_coords":
        return void createStep.mutate({
          phaseId: a.phaseId,
          body: { name: stemName(a.path), input_coords: { source: "path", ref: null, path: a.path } },
        });
      case "create_phase_with_step": {
        // Two round trips: the phase id only exists once the backend has answered. Failures are
        // already surfaced as a toast by the shared mutation cache, so the promise is swallowed.
        // Each call snapshots separately on the backend, so undoing this gesture takes two
        // presses — the first leaves the (now empty) phase behind. Collapsing it into one undo
        // unit needs a create-phase-with-first-step endpoint that does not exist yet.
        void (async () => {
          const created = await createPhase.mutateAsync({
            name: `Phase ${doc.simulation.phases.length + 1}`,
            role: "",
          });
          const phases = created.simulation.phases;
          const phaseId = phases[phases.length - 1]?.id;
          if (!phaseId) return;
          await createStep.mutateAsync({ phaseId, body: stepFromFile(a.path, a.slot) });
        })().catch(() => {});
        return;
      }
      case "move_step": {
        // The phase droppable covers the whole section, so the gaps between steps resolve to the
        // phase. Moving a step into the phase it already lives in is a remove+append on the
        // backend, which would silently send a mid-list reorder to the end of the list (and dirty
        // the document for a no-op). Aiming at a gap does nothing instead.
        const owner = doc.simulation.phases.find((p) => p.id === a.phaseId);
        if (owner?.steps.some((s) => s.id === a.stepId)) return;
        return void moveStep.mutate({ id: a.stepId, body: { phase_id: a.phaseId, index: -1 } });
      }
      case "reorder_phases": {
        const ids = doc.simulation.phases.map((p) => p.id);
        return void reorderPhases.mutate(reorderIds(ids, a.activePhaseId, a.overPhaseId));
      }
      case "reorder_or_move_step": {
        const src = doc.simulation.phases.find((p) => p.steps.some((s) => s.id === a.activeStepId));
        const dst = doc.simulation.phases.find((p) => p.steps.some((s) => s.id === a.overStepId));
        if (!src || !dst) return;
        if (src.id === dst.id) {
          const ids = src.steps.map((s) => s.id);
          return void reorderSteps.mutate({ phaseId: src.id, ids: reorderIds(ids, a.activeStepId, a.overStepId) });
        }
        const idx = dst.steps.findIndex((s) => s.id === a.overStepId);
        return void moveStep.mutate({ id: a.activeStepId, body: { phase_id: dst.id, index: idx } });
      }
    }
  };
  useUnsavedGuard(!!doc?.dirty);
  // Suspended while ANY modal owns the screen — including the file pickers raised by step
  // cards and the simulation header, which this component knows nothing about. Rewinding
  // the document behind an open picker would leave it writing into a document that no
  // longer has the step it was opened for.
  useUndoShortcuts({
    onUndo: () => undo.mutate(),
    onRedo: () => redo.mutate(),
    canUndo: !!doc?.can_undo,
    canRedo: !!doc?.can_redo,
    enabled: !modalOpen,
  });
  const confirmIfDirty = () => !doc?.dirty || window.confirm("Discard unsaved changes?");

  const onOpen = () => { if (confirmIfDirty()) setPicker("open"); };
  const onSave = () => {
    if (doc?.manifest_path) save.mutate({});
    else setPicker("save");
  };
  const onDiscover = () => { if (confirmIfDirty()) setDiscoverOpen(true); };
  const onDefineReplicas = () => {
    // The bare call runs the same cohort/nesting inference Discover's own proposal uses,
    // and it refuses on purpose for exactly the trees this button exists for -- a nested
    // sweep, or a flat chain with no directory segment at all (see
    // build_lineage_proposal's docstring). Reusing it first is not wasted work, though:
    // when the document DOES have a clean cohort structure (a reopened manifest, steps
    // built by hand since the last scan), this gives a correctly-pre-selected segment
    // instead of the crude one below.
    inferLineages.mutate(undefined, {
      onSuccess: (res) => {
        if (res.proposal) return void setStrip({ proposal: res.proposal, mode: "manual" });
        // Declined. An explicit segment_index never refuses the way the bare call just
        // did: it tags every run by its OWN value at that index, with no cohort
        // reconciliation, so index 0 -- a run's first path part, or its whole name where
        // there is no "/" at all -- always seeds a real, editable picker as long as the
        // document holds at least one step. Skipping this second call is the one thing
        // the pre-audit draft of this button got wrong: it left "Define replicas..." dead
        // on precisely the trees it was built to rescue, which is what turned that draft
        // into a blocker rather than a nice-to-have.
        inferLineages.mutate(0, {
          onSuccess: (res2) => {
            if (res2.proposal) setStrip({ proposal: res2.proposal, mode: "manual" });
            // else: truly nothing to group (the document has no steps at all). The
            // hook's own onSuccess (hooks.ts) has already toasted res2.warnings, so
            // there is nothing left to say here.
          },
        });
      },
    });
  };

  return (
    <SelectionProvider>
      <SuggestionsContext.Provider value={suggestions}>
        <DndContext
          sensors={sensors}
          collisionDetection={canvasCollisionDetection}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
          onDragCancel={() => setDrag(null)}
        >
          <div className="flex flex-col h-full">
            <TopBar onOpen={onOpen} onSave={onSave} onDiscover={onDiscover}
              onExport={() => setExportOpen(true)} onValidate={() => setValidateOpen(true)}
              onPlan={() => setPlanOpen(true)} onDefineReplicas={onDefineReplicas} />
            <div className="flex flex-1 min-h-0">
              <div data-testid="pane-files" style={{ width: filesW }}
                className="shrink-0 border-r border-hairline overflow-auto bg-surface"><FilePanel /></div>
              <ResizeHandle direction="left" currentWidth={filesW} onResize={setFilesW} minWidth={200} maxWidth={480} />
              <div data-testid="pane-canvas" className="flex-1 min-w-0 overflow-auto"><Canvas /></div>
              <ResizeHandle direction="right" currentWidth={inspW} onResize={setInspW} minWidth={280} maxWidth={560} />
              <div data-testid="pane-inspector" style={{ width: inspW }}
                className="shrink-0 border-l border-hairline overflow-auto bg-surface"><Inspector /></div>
            </div>
          </div>

          <FilePicker open={picker === "open"} mode="open" title="Open manifest"
            onClose={() => setPicker(null)}
            onPick={({ path }) => { setPicker(null); open.mutate(path); }} />
          <FilePicker open={picker === "save"} mode="save" title="Save manifest as"
            onClose={() => setPicker(null)}
            onPick={({ path, format }) => { setPicker(null); save.mutate({ path, format }); }} />
          <DiscoverModal open={discoverOpen} onClose={() => setDiscoverOpen(false)}
            onRun={(a) => discover.mutate(a, {
              onSuccess: (res) => {
                setSuggestions(res.suggestions);
                // `discover_draft` runs with `apply_tags=False` from this route (see its
                // own docstring): a fresh scan of someone else's tree is a claim about
                // THEIR data the tool has not been told to make, so nothing here is
                // written to any step yet -- only proposed, in "proposed" mode, and the
                // user accepts or corrects it through ProposalStrip itself.
                if (res.proposal) setStrip({ proposal: res.proposal, mode: "proposed" });
              },
            })} />
          <ExportModal open={exportOpen} onClose={() => setExportOpen(false)} />
          <PlanModal open={planOpen} onClose={() => setPlanOpen(false)} />
          <ValidationPanel open={validateOpen} onClose={() => setValidateOpen(false)}
            onSuggestions={setSuggestions} />
          {strip && (
            <ProposalStrip proposal={strip.proposal} mode={strip.mode} onClose={() => setStrip(null)} />
          )}

          <DragOverlay dropAnimation={null}>
            {drag && <DragChip drag={drag} sim={doc?.simulation} base={doc?.base_directory ?? null} />}
          </DragOverlay>

          <Toaster />
        </DndContext>
      </SuggestionsContext.Provider>
    </SelectionProvider>
  );
}
