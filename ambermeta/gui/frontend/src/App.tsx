import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SelectionProvider } from "@/state/selection";
import { ResizeHandle, Toaster } from "@/components/common";
import { usePersistentSize } from "@/lib/usePersistentSize";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useDocument } from "@/api/hooks";
import { TopBar } from "@/components/TopBar/TopBar";
import { FilePanel } from "@/components/FilePanel/FilePanel";
import { Canvas } from "@/components/Canvas/Canvas";
import { Inspector } from "@/components/Inspector/Inspector";

export default function App() {
  const [filesW, setFilesW] = usePersistentSize("files-w", 280);
  const [inspW, setInspW] = usePersistentSize("insp-w", 360);
  const { data: doc } = useDocument();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  const onDragEnd = (_e: DragEndEvent) => { /* wired in C3 */ };
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
