import { useEffect, useState } from 'react';
import {
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import { arrayMove } from '@dnd-kit/sortable';
import type { FileInfo, ExportFormat } from './types';
import { useProtocolStore } from './stores/protocolStore';
import { FileBrowser } from './components/FileBrowser/FileBrowser';
import { StageBuilder } from './components/StageBuilder/StageBuilder';
import { PropertiesPanel } from './components/PropertiesPanel/PropertiesPanel';
import {
  Download,
  Undo2,
  Redo2,
  Menu,
} from './components/common/Icons';

function ExportModal({
  isOpen,
  onClose,
  onExport,
}: {
  isOpen: boolean;
  onClose: () => void;
  onExport: (format: ExportFormat) => void;
}) {
  if (!isOpen) return null;

  const formats: { format: ExportFormat; label: string; ext: string }[] = [
    { format: 'yaml', label: 'YAML', ext: '.yaml' },
    { format: 'json', label: 'JSON', ext: '.json' },
    { format: 'toml', label: 'TOML', ext: '.toml' },
    { format: 'csv', label: 'CSV', ext: '.csv' },
  ];

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-80 shadow-xl">
        <h3 className="text-lg font-semibold mb-4">Export Protocol</h3>
        <div className="space-y-2">
          {formats.map(({ format, label, ext }) => (
            <button
              key={format}
              className="w-full px-4 py-3 text-left hover:bg-gray-100 rounded-lg transition-colors flex justify-between items-center"
              onClick={() => {
                onExport(format);
                onClose();
              }}
            >
              <span className="font-medium">{label}</span>
              <span className="text-gray-400 text-sm">{ext}</span>
            </button>
          ))}
        </div>
        <button
          className="w-full mt-4 px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
          onClick={onClose}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const {
    stages,
    loadFiles,
    loadStages,
    loadSettings,
    addStage,
    updateStage,
    reorderStages,
    exportProtocol,
    undo,
    redo,
    canUndo,
    canRedo,
    error,
    clearError,
  } = useProtocolStore();

  const [showExportModal, setShowExportModal] = useState(false);
  const [activeDragItem, setActiveDragItem] = useState<FileInfo | null>(null);
  const [showMobileMenu, setShowMobileMenu] = useState(false);

  // Initialize data on mount
  useEffect(() => {
    loadFiles();
    loadStages();
    loadSettings();
  }, [loadFiles, loadStages, loadSettings]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey) {
        switch (e.key.toLowerCase()) {
          case 'z':
            e.preventDefault();
            if (e.shiftKey) {
              redo();
            } else {
              undo();
            }
            break;
          case 'e':
            e.preventDefault();
            setShowExportModal(true);
            break;
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [undo, redo]);

  // DnD sensors
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    })
  );

  const handleDragStart = (event: DragStartEvent) => {
    const { active } = event;
    if (active.data.current?.type === 'file') {
      setActiveDragItem(active.data.current.file);
    }
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    setActiveDragItem(null);

    const { active, over } = event;
    if (!over) return;

    const activeId = String(active.id);
    const overId = String(over.id);

    // Handle file drop on stage
    if (activeId.startsWith('file-') && over.data.current?.stageId) {
      const { stageId, fileType } = over.data.current;
      const file = active.data.current?.file as FileInfo;

      if (file && fileType) {
        await updateStage(stageId, {
          files: { [fileType]: file.path },
        });
      }
      return;
    }

    // Handle file drop to create new stage
    if (activeId.startsWith('file-') && overId === 'stage-builder') {
      const file = active.data.current?.file as FileInfo;
      if (file && !file.is_directory) {
        // Create a new stage with this file
        const stageName = file.name.replace(/\.[^/.]+$/, ''); // Remove extension
        await addStage({
          name: stageName,
          files: { [file.file_type]: file.path },
        });
      }
      return;
    }

    // Handle stage reordering
    if (!activeId.startsWith('file-') && !overId.startsWith('file-')) {
      const oldIndex = stages.findIndex((s) => s.id === activeId);
      const newIndex = stages.findIndex((s) => s.id === overId);

      if (oldIndex !== -1 && newIndex !== -1 && oldIndex !== newIndex) {
        const newOrder = arrayMove(
          stages.map((s) => s.id),
          oldIndex,
          newIndex
        );
        await reorderStages(newOrder);
      }
    }
  };

  const handleExport = async (format: ExportFormat) => {
    try {
      const content = await exportProtocol(format);
      // Create download
      const blob = new Blob([content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `protocol.${format}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export failed:', err);
    }
  };

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="h-screen flex flex-col bg-gray-100">
        {/* Toolbar */}
        <header className="bg-white border-b border-gray-200 px-4 py-2 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-bold bg-gradient-to-r from-blue-600 to-emerald-500 bg-clip-text text-transparent">
              AmberMeta Protocol Builder
            </h1>
          </div>

          {/* Desktop toolbar */}
          <div className="hidden md:flex items-center gap-2">
            <button
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              onClick={() => undo()}
              disabled={!canUndo()}
              title="Undo (Ctrl+Z)"
            >
              <Undo2 className={`w-5 h-5 ${canUndo() ? 'text-gray-600' : 'text-gray-300'}`} />
            </button>
            <button
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              onClick={() => redo()}
              disabled={!canRedo()}
              title="Redo (Ctrl+Shift+Z)"
            >
              <Redo2 className={`w-5 h-5 ${canRedo() ? 'text-gray-600' : 'text-gray-300'}`} />
            </button>

            <div className="w-px h-6 bg-gray-200 mx-2" />

            <button
              className="flex items-center gap-2 px-3 py-2 hover:bg-gray-100 rounded-lg transition-colors text-gray-600"
              onClick={() => setShowExportModal(true)}
              title="Export (Ctrl+E)"
            >
              <Download className="w-5 h-5" />
              <span className="text-sm">Export</span>
            </button>
          </div>

          {/* Mobile menu button */}
          <button
            className="md:hidden p-2 hover:bg-gray-100 rounded-lg transition-colors"
            onClick={() => setShowMobileMenu(!showMobileMenu)}
          >
            <Menu className="w-5 h-5 text-gray-600" />
          </button>
        </header>

        {/* Mobile menu */}
        {showMobileMenu && (
          <div className="md:hidden bg-white border-b border-gray-200 p-2 flex gap-2">
            <button
              className="flex-1 flex items-center justify-center gap-1 p-2 hover:bg-gray-100 rounded-lg"
              onClick={() => {
                undo();
                setShowMobileMenu(false);
              }}
              disabled={!canUndo()}
            >
              <Undo2 className="w-4 h-4" />
              <span className="text-sm">Undo</span>
            </button>
            <button
              className="flex-1 flex items-center justify-center gap-1 p-2 hover:bg-gray-100 rounded-lg"
              onClick={() => {
                redo();
                setShowMobileMenu(false);
              }}
              disabled={!canRedo()}
            >
              <Redo2 className="w-4 h-4" />
              <span className="text-sm">Redo</span>
            </button>
            <button
              className="flex-1 flex items-center justify-center gap-1 p-2 hover:bg-gray-100 rounded-lg"
              onClick={() => {
                setShowExportModal(true);
                setShowMobileMenu(false);
              }}
            >
              <Download className="w-4 h-4" />
              <span className="text-sm">Export</span>
            </button>
          </div>
        )}

        {/* Main content */}
        <main className="flex-1 flex overflow-hidden">
          {/* File Browser - Left panel */}
          <aside className="hidden md:block w-72 flex-shrink-0">
            <FileBrowser />
          </aside>

          {/* Stage Builder - Center */}
          <section className="flex-1 min-w-0">
            <StageBuilder />
          </section>

          {/* Properties Panel - Right */}
          <aside className="hidden lg:block w-80 flex-shrink-0">
            <PropertiesPanel />
          </aside>
        </main>

        {/* Error toast */}
        {error && (
          <div className="fixed bottom-4 right-4 bg-red-500 text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-3">
            <span>{error}</span>
            <button
              className="text-white hover:text-red-200"
              onClick={clearError}
            >
              &times;
            </button>
          </div>
        )}

        {/* Export modal */}
        <ExportModal
          isOpen={showExportModal}
          onClose={() => setShowExportModal(false)}
          onExport={handleExport}
        />

        {/* Drag overlay */}
        <DragOverlay>
          {activeDragItem && (
            <div className="px-3 py-2 bg-white rounded-lg shadow-lg border border-blue-200 flex items-center gap-2">
              <span className="text-sm font-mono">{activeDragItem.name}</span>
            </div>
          )}
        </DragOverlay>
      </div>
    </DndContext>
  );
}
