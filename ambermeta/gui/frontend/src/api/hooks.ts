import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type SaveResult, type SettingsPatch } from "./client";
import { DOCUMENT_KEY, queryClient, setDocument } from "./queryClient";
import { pushToast } from "@/lib/toast";
import type {
  DocumentResponse, AddTopology, UpdateTopology, PhaseCreate, PhaseUpdate,
  StepCreatePayload, StepUpdatePayload, StepMovePayload, AssignRequest, ExportFormat,
} from "@/types";

export function useDocument() { return useQuery({ queryKey: DOCUMENT_KEY, queryFn: api.getDocument }); }
function docMutation<V>(fn: (v: V) => Promise<DocumentResponse>) {
  return useMutation({ mutationFn: fn, onSuccess: (doc) => setDocument(doc) });
}

export const useOpen = () => docMutation((path: string) => api.openDocument(path));
export const useUpdateSettings = () => docMutation((p: SettingsPatch) => api.updateSettings(p));
export const useUndo = () => docMutation((_: void) => api.undo());
export const useRedo = () => docMutation((_: void) => api.redo());

export const useAddTopology = () => docMutation((b: AddTopology) => api.addTopology(b));
export const useUpdateTopology = () => docMutation((a: { id: string; body: UpdateTopology }) => api.updateTopology(a.id, a.body));
export const useRemoveTopology = () => docMutation((id: string) => api.removeTopology(id));
export const useSetStartingStructure = () => docMutation((path: string | null) => api.setStartingStructure(path));

export const useCreatePhase = () => docMutation((b: PhaseCreate) => api.createPhase(b));
export const useUpdatePhase = () => docMutation((a: { id: string; body: PhaseUpdate }) => api.updatePhase(a.id, a.body));
export const useReorderPhases = () => docMutation((ids: string[]) => api.reorderPhases(ids));
export const useDeletePhase = () => docMutation((a: { id: string; reassignTo?: string }) => api.deletePhase(a.id, a.reassignTo));

export const useCreateStep = () => docMutation((a: { phaseId: string; body: StepCreatePayload }) => api.createStep(a.phaseId, a.body));
export const useUpdateStep = () => docMutation((a: { id: string; body: StepUpdatePayload }) => api.updateStep(a.id, a.body));
export const useDeleteStep = () => docMutation((id: string) => api.deleteStep(id));
export const useMoveStep = () => docMutation((a: { id: string; body: StepMovePayload }) => api.moveStep(a.id, a.body));
export const useReorderSteps = () => docMutation((a: { phaseId: string; ids: string[] }) => api.reorderSteps(a.phaseId, a.ids));

export const useAssign = () => docMutation((b: AssignRequest) => api.assign(b));

export const useDiscover = () =>
  useMutation({
    mutationFn: (a: { recursive: boolean; pattern?: string }) => api.discover(a),
    onSuccess: (res) => { setDocument(res.document); res.warnings.forEach((w) => pushToast(w, "warning")); },
  });
export const useSave = () =>
  useMutation({
    mutationFn: (a: { path?: string; format?: ExportFormat }) => api.saveDocument(a),
    onSuccess: (res: SaveResult) => { setDocument(res.document); res.warnings.forEach((w) => pushToast(w, "warning")); },
  });
export const useValidate = () => useMutation({ mutationFn: () => api.validate() });
export const usePreview = () => useMutation({ mutationFn: (format: ExportFormat) => api.previewDocument(format) });

export function useFiles(a: { path?: string; recursive?: boolean; include_all?: boolean }) {
  return useQuery({ queryKey: ["files", a.path ?? null, a.recursive ?? null, a.include_all ?? null], queryFn: () => api.listFiles(a) });
}
export function useFileMetadata(path: string | null) {
  return useQuery({ queryKey: ["file-metadata", path], enabled: !!path,
    queryFn: () => (path ? api.fileMetadata(path) : Promise.reject(new Error("path required"))) });
}
export function useFileRaw(path: string | null) {
  return useQuery({ queryKey: ["file-raw", path], enabled: !!path,
    queryFn: () => (path ? api.fileRaw(path) : Promise.reject(new Error("path required"))) });
}
export { queryClient, DOCUMENT_KEY };
