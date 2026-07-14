import { useEffect, useState } from "react";
import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SelectionProvider } from "@/state/selection";
import { ResizeHandle, Toaster } from "@/components/common";
import { usePersistentSize } from "@/lib/usePersistentSize";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import {
  useDocument, useAssign, useReorderSteps, useMoveStep, useReorderPhases,
  useOpen, useSave, useDiscover, useValidate,
} from "@/api/hooks";
import { TopBar } from "@/components/TopBar/TopBar";
import { DiscoverModal } from "@/components/TopBar/DiscoverModal";
import { ExportModal } from "@/components/TopBar/ExportModal";
import { ValidationPanel } from "@/components/TopBar/ValidationPanel";
import { FilePicker } from "@/components/FilePicker/FilePicker";
import { FilePanel } from "@/components/FilePanel/FilePanel";
import { Canvas } from "@/components/Canvas/Canvas";
import { SuggestionsContext } from "@/components/Suggestions/suggestionsContext";
import { Inspector } from "@/components/Inspector/Inspector";
import { resolveDrop } from "@/components/Canvas/resolveDrop";
import { reorderIds } from "@/components/Canvas/reorderIds";
import type { Suggestion } from "@/types";

export default function App() {
  const [filesW, setFilesW] = usePersistentSize("files-w", 280);
  const [inspW, setInspW] = usePersistentSize("insp-w", 360);
  const { data: doc } = useDocument();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  const assign = useAssign();
  const reorderSteps = useReorderSteps();
  const moveStep = useMoveStep();
  const reorderPhases = useReorderPhases();
  const open = useOpen();
  const save = useSave();
  const discover = useDiscover();
  const validate = useValidate();

  const [picker, setPicker] = useState<"open" | "save" | null>(null);
  const [discoverOpen, setDiscoverOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [validateOpen, setValidateOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);

  useEffect(() => {
    if (!doc) return;
    validate.mutate(undefined, { onSuccess: (report) => setSuggestions(report.suggestions) });
    // Re-validate whenever the document identity changes: on load and after every mutation
    // (setDocument writes a new object into the one ["document"] cache entry). This is the
    // single shared source of truth for suggestions -- both the canvas and the tray read it
    // via SuggestionsContext.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc]);

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
  const confirmIfDirty = () => !doc?.dirty || window.confirm("Discard unsaved changes?");

  const onOpen = () => { if (confirmIfDirty()) setPicker("open"); };
  const onSave = () => {
    if (doc?.manifest_path) save.mutate({});
    else setPicker("save");
  };
  const onDiscover = () => { if (confirmIfDirty()) setDiscoverOpen(true); };

  return (
    <SelectionProvider>
      <SuggestionsContext.Provider value={suggestions}>
        <DndContext sensors={sensors} onDragEnd={onDragEnd}>
          <div className="flex flex-col h-full">
            <TopBar onOpen={onOpen} onSave={onSave} onDiscover={onDiscover}
              onExport={() => setExportOpen(true)} onValidate={() => setValidateOpen(true)} />
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
            onRun={(a) => discover.mutate(a, { onSuccess: (res) => setSuggestions(res.suggestions) })} />
          <ExportModal open={exportOpen} onClose={() => setExportOpen(false)} />
          <ValidationPanel open={validateOpen} onClose={() => setValidateOpen(false)}
            onSuggestions={setSuggestions} />

          <Toaster />
        </DndContext>
      </SuggestionsContext.Provider>
    </SelectionProvider>
  );
}
