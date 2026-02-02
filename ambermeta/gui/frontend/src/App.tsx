import { useEffect, useState, useCallback } from 'react';
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
import type { FileInfo, ExportFormat, StageCreate, StageFiles } from './types';
import { useProtocolStore } from './stores/protocolStore';
import { FileBrowser } from './components/FileBrowser/FileBrowser';
import { StageBuilder } from './components/StageBuilder/StageBuilder';
import { PropertiesPanel } from './components/PropertiesPanel/PropertiesPanel';
import {
  Download,
  Undo2,
  Redo2,
  Menu,
  Save,
  FolderOpen,
  Wand2,
} from './components/common/Icons';
import * as api from './api/client';

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

function SessionSaveModal({
  isOpen,
  onClose,
  onSave,
}: {
  isOpen: boolean;
  onClose: () => void;
  onSave: (filename: string) => void;
}) {
  const [filename, setFilename] = useState('protocol-session');

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-96 shadow-xl">
        <h3 className="text-lg font-semibold mb-4">Save Session</h3>
        <input
          type="text"
          value={filename}
          onChange={(e) => setFilename(e.target.value)}
          placeholder="Session filename"
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 mb-4"
          autoFocus
        />
        <p className="text-sm text-gray-500 mb-4">
          Session will be saved as <span className="font-mono">{filename}.json</span>
        </p>
        <div className="flex gap-2">
          <button
            className="flex-1 px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="flex-1 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
            onClick={() => {
              onSave(filename);
              onClose();
            }}
            disabled={!filename.trim()}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

function SessionLoadModal({
  isOpen,
  onClose,
  onLoad,
}: {
  isOpen: boolean;
  onClose: () => void;
  onLoad: (filename: string) => void;
}) {
  const [filename, setFilename] = useState('protocol-session.json');

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-96 shadow-xl">
        <h3 className="text-lg font-semibold mb-4">Load Session</h3>
        <input
          type="text"
          value={filename}
          onChange={(e) => setFilename(e.target.value)}
          placeholder="Session filename (e.g., protocol-session.json)"
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 mb-4"
          autoFocus
        />
        <p className="text-sm text-gray-500 mb-4">
          Enter the filename of a previously saved session
        </p>
        <div className="flex gap-2">
          <button
            className="flex-1 px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="flex-1 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
            onClick={() => {
              onLoad(filename);
              onClose();
            }}
            disabled={!filename.trim()}
          >
            Load
          </button>
        </div>
      </div>
    </div>
  );
}

interface FileGroup {
  stem: string;
  files: Record<string, string>;
  selected: boolean;
}

function AutoDiscoverModal({
  isOpen,
  onClose,
  files,
  onCreateStages,
}: {
  isOpen: boolean;
  onClose: () => void;
  files: FileInfo[];
  onCreateStages: (stages: StageCreate[]) => void;
}) {
  const [fileGroups, setFileGroups] = useState<FileGroup[]>([]);
  const [selectAll, setSelectAll] = useState(true);

  // Group files by stem when modal opens
  useEffect(() => {
    if (!isOpen || !files.length) return;

    const groups: Record<string, Record<string, string>> = {};

    const processFiles = (fileList: FileInfo[]) => {
      for (const file of fileList) {
        if (file.is_directory && file.children) {
          processFiles(file.children);
        } else if (!file.is_directory && file.file_type !== 'folder' && file.file_type !== 'other' && file.file_type !== 'prmtop') {
          // Extract stem (filename without extension)
          // Note: prmtop files are excluded from stage creation - they should be set as global prmtop instead
          const stem = file.name.replace(/\.[^/.]+$/, '');
          if (!groups[stem]) {
            groups[stem] = {};
          }
          groups[stem][file.file_type] = file.path;
        }
      }
    };

    processFiles(files);

    // Convert to array and sort by name
    const groupArray = Object.entries(groups)
      .map(([stem, files]) => ({ stem, files, selected: true }))
      .sort((a, b) => a.stem.localeCompare(b.stem, undefined, { numeric: true }));

    setFileGroups(groupArray);
    setSelectAll(true);
  }, [isOpen, files]);

  const toggleGroup = (index: number) => {
    setFileGroups(prev => {
      const next = [...prev];
      next[index] = { ...next[index], selected: !next[index].selected };
      return next;
    });
  };

  const toggleAll = () => {
    const newState = !selectAll;
    setSelectAll(newState);
    setFileGroups(prev => prev.map(g => ({ ...g, selected: newState })));
  };

  const handleCreate = () => {
    const stages: StageCreate[] = fileGroups
      .filter(g => g.selected)
      .map(g => ({
        name: g.stem,
        files: g.files as StageCreate['files'],
      }));

    onCreateStages(stages);
    onClose();
  };

  if (!isOpen) return null;

  const selectedCount = fileGroups.filter(g => g.selected).length;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-[600px] max-h-[80vh] flex flex-col shadow-xl">
        <h3 className="text-lg font-semibold mb-2">Auto-Discover Stages</h3>
        <p className="text-sm text-gray-600 mb-4">
          Found {fileGroups.length} file groups. Select the ones to create as stages.
        </p>

        {/* Select all toggle */}
        <div className="flex items-center gap-2 mb-3 pb-3 border-b border-gray-200">
          <input
            type="checkbox"
            checked={selectAll}
            onChange={toggleAll}
            className="rounded border-gray-300 text-blue-500 focus:ring-blue-500"
          />
          <span className="text-sm font-medium">
            Select All ({selectedCount}/{fileGroups.length})
          </span>
        </div>

        {/* File groups list */}
        <div className="flex-1 overflow-y-auto space-y-2 mb-4">
          {fileGroups.length === 0 ? (
            <p className="text-gray-500 text-center py-4">No file groups found</p>
          ) : (
            fileGroups.map((group, index) => (
              <div
                key={group.stem}
                className={`p-3 rounded-lg border-2 cursor-pointer transition-colors ${
                  group.selected
                    ? 'border-blue-200 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
                onClick={() => toggleGroup(index)}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={group.selected}
                    onChange={() => toggleGroup(index)}
                    onClick={(e) => e.stopPropagation()}
                    className="rounded border-gray-300 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="font-medium">{group.stem}</span>
                </div>
                <div className="ml-6 mt-1 flex flex-wrap gap-2">
                  {Object.entries(group.files).map(([type, path]) => (
                    <span
                      key={type}
                      className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600"
                      title={path}
                    >
                      {type}
                    </span>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          <button
            className="flex-1 px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="flex-1 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors disabled:opacity-50"
            onClick={handleCreate}
            disabled={selectedCount === 0}
          >
            Create {selectedCount} Stage{selectedCount !== 1 ? 's' : ''}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const {
    stages,
    files,
    loadFiles,
    loadStages,
    loadSettings,
    addStage,
    updateStage,
    reorderStages,
    exportProtocol,
    saveSession,
    loadSession,
    undo,
    redo,
    canUndo,
    canRedo,
    error,
    clearError,
  } = useProtocolStore();

  const [showExportModal, setShowExportModal] = useState(false);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showLoadModal, setShowLoadModal] = useState(false);
  const [showAutoDiscoverModal, setShowAutoDiscoverModal] = useState(false);
  const [activeDragItem, setActiveDragItem] = useState<FileInfo | null>(null);
  const [showMobileMenu, setShowMobileMenu] = useState(false);

  // Initialize data on mount
  useEffect(() => {
    loadFiles();
    loadStages();
    loadSettings();
  }, [loadFiles, loadStages, loadSettings]);

  // Handle session save
  const handleSaveSession = useCallback(async (filename: string) => {
    try {
      await saveSession(filename);
    } catch (err) {
      console.error('Save session failed:', err);
    }
  }, [saveSession]);

  // Handle session load
  const handleLoadSession = useCallback(async (filename: string) => {
    try {
      await loadSession(filename);
    } catch (err) {
      console.error('Load session failed:', err);
    }
  }, [loadSession]);

  // Handle auto-discover stage creation
  const handleCreateStagesFromDiscovery = useCallback(async (stagesToCreate: StageCreate[]) => {
    for (const stageData of stagesToCreate) {
      await addStage(stageData);
    }
  }, [addStage]);

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
          case 'y':
            e.preventDefault();
            redo();
            break;
          case 's':
            e.preventDefault();
            setShowSaveModal(true);
            break;
          case 'o':
            e.preventDefault();
            setShowLoadModal(true);
            break;
          case 'e':
            e.preventDefault();
            setShowExportModal(true);
            break;
          case 'a':
            // Only handle if no input is focused
            if (document.activeElement?.tagName !== 'INPUT' &&
                document.activeElement?.tagName !== 'TEXTAREA') {
              e.preventDefault();
              setShowAutoDiscoverModal(true);
            }
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
      // Prevent prmtop files from being used as stage bases - they should only be set as global/HMR prmtop
      if (file && !file.is_directory && file.file_type !== 'prmtop') {
        // Create a new stage with this file
        const stageName = file.name.replace(/\.[^/.]+$/, ''); // Remove extension

        // Try to auto-group related files (e.g., 01_min.mdin, 01_min.mdout, 01_min.nc)
        let stageFiles: StageFiles = { [file.file_type]: file.path };

        try {
          // Fetch related files from the backend
          const relatedFiles = await api.getRelatedFiles(file.path);
          if (relatedFiles && Object.keys(relatedFiles).length > 0) {
            // Merge the dragged file with related files
            stageFiles = {
              ...relatedFiles,
              [file.file_type]: file.path, // Ensure dragged file takes precedence
            } as StageFiles;
          }
        } catch (err) {
          // If fetching related files fails, just use the dragged file
          console.warn('Could not fetch related files:', err);
        }

        await addStage({
          name: stageName,
          files: stageFiles,
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
              title="Redo (Ctrl+Y)"
            >
              <Redo2 className={`w-5 h-5 ${canRedo() ? 'text-gray-600' : 'text-gray-300'}`} />
            </button>

            <div className="w-px h-6 bg-gray-200 mx-2" />

            <button
              className="flex items-center gap-2 px-3 py-2 hover:bg-gray-100 rounded-lg transition-colors text-gray-600"
              onClick={() => setShowSaveModal(true)}
              title="Save Session (Ctrl+S)"
            >
              <Save className="w-5 h-5" />
              <span className="text-sm">Save</span>
            </button>
            <button
              className="flex items-center gap-2 px-3 py-2 hover:bg-gray-100 rounded-lg transition-colors text-gray-600"
              onClick={() => setShowLoadModal(true)}
              title="Load Session (Ctrl+O)"
            >
              <FolderOpen className="w-5 h-5" />
              <span className="text-sm">Load</span>
            </button>

            <div className="w-px h-6 bg-gray-200 mx-2" />

            <button
              className="flex items-center gap-2 px-3 py-2 hover:bg-blue-50 rounded-lg transition-colors text-blue-600"
              onClick={() => setShowAutoDiscoverModal(true)}
              title="Auto-Discover Stages (Ctrl+A)"
            >
              <Wand2 className="w-5 h-5" />
              <span className="text-sm">Auto-Discover</span>
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
          <div className="md:hidden bg-white border-b border-gray-200 p-2 space-y-2">
            <div className="flex gap-2">
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
            </div>
            <div className="flex gap-2">
              <button
                className="flex-1 flex items-center justify-center gap-1 p-2 hover:bg-gray-100 rounded-lg"
                onClick={() => {
                  setShowSaveModal(true);
                  setShowMobileMenu(false);
                }}
              >
                <Save className="w-4 h-4" />
                <span className="text-sm">Save</span>
              </button>
              <button
                className="flex-1 flex items-center justify-center gap-1 p-2 hover:bg-gray-100 rounded-lg"
                onClick={() => {
                  setShowLoadModal(true);
                  setShowMobileMenu(false);
                }}
              >
                <FolderOpen className="w-4 h-4" />
                <span className="text-sm">Load</span>
              </button>
            </div>
            <div className="flex gap-2">
              <button
                className="flex-1 flex items-center justify-center gap-1 p-2 hover:bg-blue-50 text-blue-600 rounded-lg"
                onClick={() => {
                  setShowAutoDiscoverModal(true);
                  setShowMobileMenu(false);
                }}
              >
                <Wand2 className="w-4 h-4" />
                <span className="text-sm">Auto-Discover</span>
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

        {/* Session save modal */}
        <SessionSaveModal
          isOpen={showSaveModal}
          onClose={() => setShowSaveModal(false)}
          onSave={handleSaveSession}
        />

        {/* Session load modal */}
        <SessionLoadModal
          isOpen={showLoadModal}
          onClose={() => setShowLoadModal(false)}
          onLoad={handleLoadSession}
        />

        {/* Auto-discover modal */}
        <AutoDiscoverModal
          isOpen={showAutoDiscoverModal}
          onClose={() => setShowAutoDiscoverModal(false)}
          files={files}
          onCreateStages={handleCreateStagesFromDiscovery}
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
