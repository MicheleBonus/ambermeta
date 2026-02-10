import { create } from 'zustand';
import type {
  Stage,
  StageCreate,
  StageUpdate,
  GlobalSettings,
  FileInfo,
  ExportFormat,
} from '../types';
import * as api from '../api/client';

interface ProtocolStore {
  // State
  baseDirectory: string;
  stages: Stage[];
  settings: GlobalSettings;
  selectedStageId: string | null;
  selectedStageIds: string[];
  files: FileInfo[];
  isLoading: boolean;
  error: string | null;

  // History for undo/redo
  history: Stage[][];
  historyIndex: number;

  // Actions
  setSelectedStage: (id: string | null) => void;
  toggleStageSelection: (id: string, shiftKey: boolean) => void;
  clearSelection: () => void;

  // File actions
  loadFiles: (path?: string) => Promise<void>;

  // Stage actions
  loadStages: () => Promise<void>;
  addStage: (stage: StageCreate) => Promise<void>;
  updateStage: (id: string, update: StageUpdate) => Promise<void>;
  bulkUpdateStages: (ids: string[], update: StageUpdate) => Promise<void>;
  deleteStage: (id: string) => Promise<void>;
  reorderStages: (stageIds: string[]) => Promise<void>;

  // Settings actions
  loadSettings: () => Promise<void>;
  updateSettings: (settings: GlobalSettings) => Promise<void>;

  // Export actions
  exportProtocol: (format: ExportFormat) => Promise<string>;

  // Session actions
  saveSession: (filename: string) => Promise<void>;
  loadSession: (filename: string) => Promise<void>;

  // Validation
  validate: () => Promise<void>;

  // Undo/Redo
  undo: () => void;
  redo: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;

  // Error handling
  clearError: () => void;
}

const DEFAULT_SETTINGS: GlobalSettings = {
  auto_link_restarts: true,
  validate_on_export: true,
  use_relative_paths: false,
};

export const useProtocolStore = create<ProtocolStore>((set, get) => ({
  // Initial state
  baseDirectory: '.',
  stages: [],
  settings: DEFAULT_SETTINGS,
  selectedStageId: null,
  selectedStageIds: [],
  files: [],
  isLoading: false,
  error: null,
  history: [],
  historyIndex: -1,

  setSelectedStage: (id) => set({
    selectedStageId: id,
    selectedStageIds: id ? [id] : [],
  }),

  toggleStageSelection: (id, shiftKey) => {
    const { selectedStageIds, stages } = get();

    if (shiftKey && selectedStageIds.length > 0) {
      // Shift+click: select range from last selected to this one
      const lastSelected = selectedStageIds[selectedStageIds.length - 1];
      const lastIndex = stages.findIndex(s => s.id === lastSelected);
      const currentIndex = stages.findIndex(s => s.id === id);
      if (lastIndex !== -1 && currentIndex !== -1) {
        const start = Math.min(lastIndex, currentIndex);
        const end = Math.max(lastIndex, currentIndex);
        const rangeIds = stages.slice(start, end + 1).map(s => s.id);
        // Merge with existing selection
        const merged = new Set([...selectedStageIds, ...rangeIds]);
        set({
          selectedStageIds: Array.from(merged),
          selectedStageId: id,
        });
      }
    } else {
      // Regular click: toggle this one in selection
      const isSelected = selectedStageIds.includes(id);
      if (isSelected) {
        const newIds = selectedStageIds.filter(sid => sid !== id);
        set({
          selectedStageIds: newIds,
          selectedStageId: newIds.length > 0 ? newIds[newIds.length - 1] : null,
        });
      } else {
        set({
          selectedStageIds: [...selectedStageIds, id],
          selectedStageId: id,
        });
      }
    }
  },

  clearSelection: () => set({ selectedStageIds: [], selectedStageId: null }),

  loadFiles: async (path) => {
    set({ isLoading: true, error: null });
    try {
      const files = await api.listFiles(path);
      set({ files, isLoading: false });
    } catch (err) {
      set({ error: String(err), isLoading: false });
    }
  },

  loadStages: async () => {
    set({ isLoading: true, error: null });
    try {
      const stages = await api.listStages();
      set({ stages, isLoading: false });
    } catch (err) {
      set({ error: String(err), isLoading: false });
    }
  },

  addStage: async (stage) => {
    set({ isLoading: true, error: null });
    try {
      const newStage = await api.createStage(stage);
      const { stages, history, historyIndex } = get();

      // Save current state to history
      const newHistory = history.slice(0, historyIndex + 1);
      newHistory.push([...stages]);

      set({
        stages: [...stages, newStage],
        history: newHistory,
        historyIndex: newHistory.length - 1,
        selectedStageId: newStage.id,
        selectedStageIds: [newStage.id],
        isLoading: false,
      });
    } catch (err) {
      set({ error: String(err), isLoading: false });
    }
  },

  updateStage: async (id, update) => {
    set({ isLoading: true, error: null });
    try {
      const updatedStage = await api.updateStage(id, update);
      const { stages, history, historyIndex } = get();

      // Save current state to history
      const newHistory = history.slice(0, historyIndex + 1);
      newHistory.push([...stages]);

      set({
        stages: stages.map(s => s.id === id ? updatedStage : s),
        history: newHistory,
        historyIndex: newHistory.length - 1,
        isLoading: false,
      });
    } catch (err) {
      set({ error: String(err), isLoading: false });
    }
  },

  bulkUpdateStages: async (ids, update) => {
    set({ isLoading: true, error: null });
    try {
      const updatedStages = await api.bulkUpdateStages(ids, update);
      const { stages, history, historyIndex } = get();

      // Save current state to history
      const newHistory = history.slice(0, historyIndex + 1);
      newHistory.push([...stages]);

      // Merge updated stages back into the list
      const updatedMap = new Map(updatedStages.map(s => [s.id, s]));
      const newStages = stages.map(s => updatedMap.get(s.id) || s);

      set({
        stages: newStages,
        history: newHistory,
        historyIndex: newHistory.length - 1,
        isLoading: false,
      });
    } catch (err) {
      set({ error: String(err), isLoading: false });
    }
  },

  deleteStage: async (id) => {
    set({ isLoading: true, error: null });
    try {
      await api.deleteStage(id);
      const { stages, selectedStageId, selectedStageIds, history, historyIndex } = get();

      // Save current state to history
      const newHistory = history.slice(0, historyIndex + 1);
      newHistory.push([...stages]);

      set({
        stages: stages.filter(s => s.id !== id),
        selectedStageId: selectedStageId === id ? null : selectedStageId,
        selectedStageIds: selectedStageIds.filter(sid => sid !== id),
        history: newHistory,
        historyIndex: newHistory.length - 1,
        isLoading: false,
      });
    } catch (err) {
      set({ error: String(err), isLoading: false });
    }
  },

  reorderStages: async (stageIds) => {
    set({ isLoading: true, error: null });
    try {
      const reorderedStages = await api.reorderStages(stageIds);
      const { stages, history, historyIndex } = get();

      // Save current state to history
      const newHistory = history.slice(0, historyIndex + 1);
      newHistory.push([...stages]);

      set({
        stages: reorderedStages,
        history: newHistory,
        historyIndex: newHistory.length - 1,
        isLoading: false,
      });
    } catch (err) {
      set({ error: String(err), isLoading: false });
    }
  },

  loadSettings: async () => {
    try {
      const settings = await api.getSettings();
      set({ settings });
    } catch (err) {
      set({ error: String(err) });
    }
  },

  updateSettings: async (settings) => {
    set({ isLoading: true, error: null });
    try {
      const updatedSettings = await api.updateSettings(settings);
      set({ settings: updatedSettings, isLoading: false });
    } catch (err) {
      set({ error: String(err), isLoading: false });
    }
  },

  exportProtocol: async (format) => {
    set({ isLoading: true, error: null });
    try {
      const { settings } = get();
      const result = await api.exportProtocol({
        format,
        include_validation: true,
        use_relative_paths: settings.use_relative_paths,
      });
      set({ isLoading: false });
      return result.content;
    } catch (err) {
      set({ error: String(err), isLoading: false });
      throw err;
    }
  },

  saveSession: async (filename) => {
    set({ isLoading: true, error: null });
    try {
      await api.saveSession(filename);
      set({ isLoading: false });
    } catch (err) {
      set({ error: String(err), isLoading: false });
    }
  },

  loadSession: async (filename) => {
    set({ isLoading: true, error: null });
    try {
      const protocol = await api.loadSession(filename);
      set({
        baseDirectory: protocol.base_directory,
        stages: protocol.stages,
        settings: protocol.settings,
        isLoading: false,
      });
    } catch (err) {
      set({ error: String(err), isLoading: false });
    }
  },

  validate: async () => {
    set({ isLoading: true, error: null });
    try {
      const result = await api.validateProtocol();
      // Update stages with validation results
      const { stages } = get();
      const updatedStages = stages.map(stage => ({
        ...stage,
        validation: result.stage_validations[stage.id] || stage.validation,
      }));
      set({ stages: updatedStages, isLoading: false });
    } catch (err) {
      set({ error: String(err), isLoading: false });
    }
  },

  undo: () => {
    const { history, historyIndex, stages } = get();
    if (historyIndex < 0) return;

    // If at the end of history, save current state first so we can redo to it
    let newHistory = [...history];
    let newIndex = historyIndex;

    if (historyIndex === history.length - 1) {
      // We're at the latest change - save current state for redo
      newHistory = [...history, [...stages]];
    }

    // Restore the previous state
    set({
      stages: [...history[historyIndex]],
      history: newHistory,
      historyIndex: newIndex - 1,
    });
  },

  redo: () => {
    const { history, historyIndex } = get();
    // historyIndex is -1 initially, so historyIndex + 2 is the state after the first undo
    // After undo: historyIndex = -1, can redo if history has at least 1 item
    const nextIndex = historyIndex + 2;
    if (nextIndex >= history.length) return;

    set({
      stages: [...history[nextIndex]],
      historyIndex: historyIndex + 1,
    });
  },

  canUndo: () => get().historyIndex >= 0,
  canRedo: () => {
    const { history, historyIndex } = get();
    return historyIndex + 2 < history.length;
  },

  clearError: () => set({ error: null }),
}));
