import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SelectionProvider } from "@/state/selection";
import { ResizeHandle } from "@/components/common";
import { usePersistentSize } from "@/lib/usePersistentSize";
import { TopBar } from "@/components/TopBar/TopBar";
import { FileBrowser } from "@/components/FileBrowser/FileBrowser";
import { StageList } from "@/components/StageList/StageList";
import { PropertiesPanel } from "@/components/PropertiesPanel/PropertiesPanel";
import { useDocument, useReorder, useUpdateStage } from "@/api/hooks";
import { reorderIds, resolveDrop } from "@/components/StageList/reorder";

export default function App() {
  const [filesW, setFilesW] = usePersistentSize("files-w", 280);
  const [propsW, setPropsW] = usePersistentSize("props-w", 340);
  const { data: doc } = useDocument();
  const reorder = useReorder();
  const updateStage = useUpdateStage();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  const handleDragEnd = (e: DragEndEvent) => {
    const drop = resolveDrop(String(e.active.id), e.over ? String(e.over.id) : null);
    if (!drop) return;
    if (drop.type === "assign") {
      updateStage.mutate({ id: drop.stageId, update: { files: { [drop.kind]: drop.path } } });
    } else {
      reorder.mutate(reorderIds((doc?.stages ?? []).map((s) => s.id), drop.activeId, drop.overId));
    }
  };
  const noop = () => {};
  return (
    <SelectionProvider>
      <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
        <div className="flex flex-col h-full">
          <TopBar onOpen={noop} onSave={noop} onDiscover={noop} onRelink={noop} onExport={noop} onValidate={noop} />
          <div className="flex flex-1 min-h-0">
            <div data-testid="pane-files" style={{ width: filesW }}
                 className="shrink-0 border-r border-hairline overflow-auto bg-surface">
              <FileBrowser />
            </div>
            <ResizeHandle direction="left" currentWidth={filesW} onResize={setFilesW} minWidth={200} maxWidth={480} />
            <div data-testid="pane-stages" className="flex-1 min-w-0 overflow-hidden">
              <StageList />
            </div>
            <ResizeHandle direction="right" currentWidth={propsW} onResize={setPropsW} minWidth={260} maxWidth={520} />
            <div data-testid="pane-properties" style={{ width: propsW }}
                 className="shrink-0 border-l border-hairline overflow-auto bg-surface">
              <PropertiesPanel />
            </div>
          </div>
        </div>
      </DndContext>
    </SelectionProvider>
  );
}
