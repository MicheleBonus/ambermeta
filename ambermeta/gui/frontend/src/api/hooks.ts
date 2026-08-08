import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type SaveResult, type SettingsPatch } from "./client";
import { DOCUMENT_KEY, queryClient, setDocument } from "./queryClient";
import { pushToast, pushEditWarning } from "@/lib/toast";
import type {
  DocumentResponse, AddTopology, UpdateTopology, PhaseCreate, PhaseUpdate,
  StepCreatePayload, StepUpdatePayload, StepsLineagePayload, StepMovePayload, AssignRequest, ExportFormat,
  PlanRequest, PlanResult,
} from "@/types";

export function useDocument() { return useQuery({ queryKey: DOCUMENT_KEY, queryFn: api.getDocument }); }
function docMutation<V>(fn: (v: V) => Promise<DocumentResponse>) {
  // setDocument retires whatever the previous edit had to say — its "Undo" offer, its
  // warnings — for every writer of the document; see queryClient.ts. It runs before this
  // mutation's own onSuccess callback, so a caller that raises a fresh offer there still
  // gets to keep it, and so do the warnings raised immediately below.
  return useMutation({
    mutationFn: fn,
    onSuccess: (doc) => {
      setDocument(doc);
      // The server's report on the edit that just landed: a shared parent deleted out from
      // under several lineages, a hand-set link across two of them. Announced here and
      // nowhere else, because a document mutation is the only response on which this field
      // describes the request that produced it. On discover it is always empty (the
      // document is replaced wholesale); on save and plan it still holds the PREVIOUS
      // edit's warnings, because neither is a mutation and neither clears them — so
      // announcing it there would resurrect a finding that already had its say.
      doc.warnings.forEach((w) => pushEditWarning(w));
    },
  });
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
export const useSetLineages = () => docMutation((b: StepsLineagePayload) => api.setLineages(b));
// Bare useMutation, not docMutation: `/steps/infer-lineages` never touches the document
// (routes.py: "Writes nothing"), so there is no DocumentResponse to fold into the query
// cache here. The proposal it returns is applied later, member by member, through
// useSetLineages -- each of THOSE calls is the actual edit and goes through docMutation
// normally, pushing its own undo frame. Warnings are still surfaced as toasts: a refusal
// ("No lineages inferred: ...") is the entire content of that response on the null path,
// and saying nothing there would leave the picker looking like it silently did nothing.
export const useInferLineages = () =>
  useMutation({
    mutationFn: (segmentIndex?: number) => api.inferLineages(segmentIndex),
    onSuccess: (res) => res.warnings.forEach((w) => pushToast(w, "warning")),
  });
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
    onSuccess: (res: SaveResult) => {
      setDocument(res.document);
      res.warnings.forEach((w) => pushToast(w, "warning"));
      // Saying where it went, because the only other evidence a save happened was the
      // dirty dot going out — which reads as "nothing happened" if you were not watching
      // it, and never told you which file was written.
      if (res.document.manifest_path) pushToast(`Saved to ${res.document.manifest_path}`);
    },
  });
export const usePlan = () =>
  useMutation({
    mutationFn: (b: PlanRequest) => api.plan(b),
    onSuccess: (res: PlanResult) => {
      setDocument(res.document);
      res.warnings.forEach((w) => pushToast(w, "warning"));
    },
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
