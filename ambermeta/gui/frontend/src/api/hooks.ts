import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "./client";
import { DOCUMENT_KEY, queryClient, setDocument } from "./queryClient";
import { pushToast } from "@/lib/toast";
import type {
  DocumentResponse, SaveResult, StageCreate, StageUpdate, SettingsPatch,
  ExportFormat,
} from "@/types";

export function useDocument() {
  return useQuery({ queryKey: DOCUMENT_KEY, queryFn: api.getDocument });
}

function docMutation<V>(fn: (v: V) => Promise<DocumentResponse>) {
  return useMutation({ mutationFn: fn, onSuccess: (doc) => setDocument(doc) });
}

export const useOpen = () => docMutation((path: string) => api.openDocument(path));
export const useDiscover = () =>
  docMutation((a: { recursive: boolean; pattern?: string }) => api.discover(a));
export const useCreateStage = () => docMutation((s: StageCreate) => api.createStage(s));
export const useUpdateStage = () =>
  docMutation((a: { id: string; update: StageUpdate }) => api.updateStage(a.id, a.update));
export const useDeleteStage = () => docMutation((id: string) => api.deleteStage(id));
export const useReorder = () => docMutation((ids: string[]) => api.reorderStages(ids));
export const useBulkUpdate = () =>
  docMutation((a: { ids: string[]; update: StageUpdate }) =>
    api.bulkUpdateStages(a.ids, a.update));
export const useUpdateSettings = () => docMutation((p: SettingsPatch) => api.updateSettings(p));
export const useUndo = () => docMutation((_: void) => api.undo());
export const useRedo = () => docMutation((_: void) => api.redo());
export const useLinkRestarts = () => docMutation((_: void) => api.linkRestarts());

export const useSave = () =>
  useMutation({
    mutationFn: (a: { path?: string; format?: ExportFormat }) => api.saveDocument(a),
    onSuccess: (res: SaveResult) => {
      setDocument(res.document);
      res.warnings.forEach((w) => pushToast(w, "warning"));
    },
  });

export const useValidate = () => useMutation({ mutationFn: () => api.validate() });
export const usePreview = () =>
  useMutation({ mutationFn: (format: ExportFormat) => api.previewDocument(format) });

export function useFiles(args: { path?: string; recursive?: boolean; include_all?: boolean }) {
  // Spread the args into the key (not the object) so identical values hit the cache
  // regardless of object identity.
  return useQuery({
    queryKey: ["files", args.path ?? null, args.recursive ?? null, args.include_all ?? null],
    queryFn: () => api.listFiles(args),
  });
}

export function useFileMetadata(path: string | null) {
  return useQuery({
    queryKey: ["file-metadata", path],
    queryFn: () => {
      if (!path) return Promise.reject(new Error("file path required"));
      return api.fileMetadata(path);
    },
    enabled: !!path,
  });
}

export function useSequences() {
  return useQuery({ queryKey: ["sequences"], queryFn: api.sequences });
}

// Re-export for tests/consumers that need to reset between renders.
export { queryClient, DOCUMENT_KEY };
