import { useState } from "react";
import { SelectionProvider } from "@/state/selection";
import { DragChip, ResizeHandle, Toaster } from "@/components/common";
import { usePersistentSize } from "@/lib/usePersistentSize";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { TopBar } from "@/components/TopBar/TopBar";
import { DiscoverModal } from "@/components/TopBar/DiscoverModal";
import { ExportModal } from "@/components/TopBar/ExportModal";
import { FileBrowser } from "@/components/FileBrowser/FileBrowser";
import { StageList } from "@/components/StageList/StageList";
import { PropertiesPanel } from "@/components/PropertiesPanel/PropertiesPanel";
import { FilePicker } from "@/components/FilePicker/FilePicker";
import { ValidationPanel } from "@/components/ValidationPanel/ValidationPanel";
import {
  DndContext, DragOverlay, PointerSensor, useSensor, useSensors,
  type DragEndEvent, type DragStartEvent,
} from "@dnd-kit/core";
import { reorderIds, resolveDrop } from "@/components/StageList/reorder";
import { relativizePath, fileLabel } from "@/lib/format";
import {
  useDocument, useOpen, useSave, useDiscover, useLinkRestarts, useReorder, useUpdateStage,
  useCreateStage,
} from "@/api/hooks";

export default function App() {
  const [filesW, setFilesW] = usePersistentSize("files-w", 280, { min: 200, max: 480 });
  const [propsW, setPropsW] = usePersistentSize("props-w", 340, { min: 260, max: 520 });
  const { data: doc } = useDocument();
  const open = useOpen(); const save = useSave(); const discover = useDiscover();
  const relink = useLinkRestarts();
  const reorder = useReorder(); const updateStage = useUpdateStage();
  const createStage = useCreateStage();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  const [activeId, setActiveId] = useState<string | null>(null);
  const handleDragEnd = (e: DragEndEvent) => {
    setActiveId(null);
    const drop = resolveDrop(String(e.active.id), e.over ? String(e.over.id) : null);
    if (!drop) return;
    if (drop.type === "assign") {
      updateStage.mutate({ id: drop.stageId, update: { files: { [drop.kind]: relativizePath(drop.path, doc?.base_directory ?? null) } } });
    } else if (drop.type === "create") {
      const { name } = fileLabel(drop.path, doc?.base_directory ?? null);
      createStage.mutate({ name: name.replace(/\.[^.]+$/, "") });
    } else {
      reorder.mutate(reorderIds((doc?.stages ?? []).map((s) => s.id), drop.activeId, drop.overId));
    }
  };
  const [picker, setPicker] = useState<"open" | "save" | null>(null);
  const [discoverOpen, setDiscoverOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [validateOpen, setValidateOpen] = useState(false);

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
      <DndContext sensors={sensors} onDragEnd={handleDragEnd}
        onDragStart={(e: DragStartEvent) => setActiveId(String(e.active.id))}>
      <div className="flex flex-col h-full">
        <TopBar onOpen={onOpen} onSave={onSave} onDiscover={onDiscover}
          onRelink={() => relink.mutate()}
          onExport={() => setExportOpen(true)} onValidate={() => setValidateOpen(true)} />
        <div className="flex flex-1 min-h-0">
          <div data-testid="pane-files" style={{ width: filesW }}
            className="shrink-0 border-r border-hairline overflow-auto bg-surface"><FileBrowser /></div>
          <ResizeHandle direction="left" currentWidth={filesW} onResize={setFilesW} minWidth={200} maxWidth={480} />
          <div data-testid="pane-stages" className="flex-1 min-w-0 overflow-hidden"><StageList /></div>
          <ResizeHandle direction="right" currentWidth={propsW} onResize={setPropsW} minWidth={260} maxWidth={520} />
          <div data-testid="pane-properties" style={{ width: propsW }}
            className="shrink-0 border-l border-hairline overflow-auto bg-surface"><PropertiesPanel /></div>
        </div>
      </div>

      <FilePicker open={picker === "open"} mode="open" title="Open manifest"
        onClose={() => setPicker(null)}
        onPick={({ path }) => { setPicker(null); open.mutate(path); }} />
      <FilePicker open={picker === "save"} mode="save" title="Save manifest as"
        onClose={() => setPicker(null)}
        onPick={({ path, format }) => { setPicker(null); save.mutate({ path, format }); }} />
      <DiscoverModal open={discoverOpen} onClose={() => setDiscoverOpen(false)}
        onRun={(a) => discover.mutate(a)} />
      <ExportModal open={exportOpen} onClose={() => setExportOpen(false)} />
      <ValidationPanel open={validateOpen} onClose={() => setValidateOpen(false)} />
      <Toaster />
      <DragOverlay><DragChip activeId={activeId} base={doc?.base_directory ?? null} /></DragOverlay>
      </DndContext>
    </SelectionProvider>
  );
}
