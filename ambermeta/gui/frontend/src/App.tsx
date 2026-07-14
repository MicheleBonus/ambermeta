import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SelectionProvider } from "@/state/selection";
import { ResizeHandle, Toaster } from "@/components/common";
import { usePersistentSize } from "@/lib/usePersistentSize";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useDocument, useAssign, useReorderSteps, useMoveStep, useReorderPhases } from "@/api/hooks";
import { TopBar } from "@/components/TopBar/TopBar";
import { FilePanel } from "@/components/FilePanel/FilePanel";
import { Canvas } from "@/components/Canvas/Canvas";
import { Inspector } from "@/components/Inspector/Inspector";
import { resolveDrop } from "@/components/Canvas/resolveDrop";
import { reorderIds } from "@/components/Canvas/reorderIds";

export default function App() {
  const [filesW, setFilesW] = usePersistentSize("files-w", 280);
  const [inspW, setInspW] = usePersistentSize("insp-w", 360);
  const { data: doc } = useDocument();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  const assign = useAssign();
  const reorderSteps = useReorderSteps();
  const moveStep = useMoveStep();
  const reorderPhases = useReorderPhases();
  const onDragEnd = (e: DragEndEvent) => {
    const a = resolveDrop(String(e.active.id), e.over ? String(e.over.id) : null);
    if (!a || !doc) return;
    switch (a.type) {
      case "pool":
        return void assign.mutate({ path: a.path, target_type: "pool", kind: a.path.includes("hmr") ? "hmr" : "normal" });
      case "starting":
        return void assign.mutate({ path: a.path, target_type: "starting_structure" });
      case "step_slot":
        return void assign.mutate({ path: a.path, target_type: "step_slot", target_id: a.stepId, slot: a.kind });
      case "step_topology":
        return void assign.mutate({ path: a.path, target_type: "step_topology", target_id: a.stepId });
      case "phase_topology":
        return void assign.mutate({ path: a.path, target_type: "phase_topology", target_id: a.phaseId });
      case "move_step":
        return void moveStep.mutate({ id: a.stepId, body: { phase_id: a.phaseId, index: -1 } });
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

  return (
    <SelectionProvider>
      <DndContext sensors={sensors} onDragEnd={onDragEnd}>
        <div className="flex flex-col h-full">
          <TopBar />
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
        <Toaster />
      </DndContext>
    </SelectionProvider>
  );
}
