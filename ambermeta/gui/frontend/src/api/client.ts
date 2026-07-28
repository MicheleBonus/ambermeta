import type {
  DocumentResponse, ValidationReport, DiscoverResult,
  RuntimeSettings, FileInfo, FileMetadata, RawFile, ExportFormat,
  AddTopology, UpdateTopology, PhaseCreate, PhaseUpdate,
  StepCreatePayload, StepUpdatePayload, StepMovePayload, AssignRequest,
  PlanRequest, PlanResult,
} from "@/types";
// (SaveResult / PreviewResponse / SettingsPatch are client-response shapes, not part of @/types)
export interface SaveResult { document: DocumentResponse; warnings: string[]; }
export interface PreviewResponse { content: string; warnings: string[]; }
export interface SettingsPatch { auto_link_restarts?: boolean; strict_validation?: boolean; allow_gaps?: boolean; use_relative_paths?: boolean; }

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });

const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

export const api = {
  getDocument: () => request<DocumentResponse>("/document"),
  openDocument: (path: string) => post<DocumentResponse>("/document/open", { path }),
  saveDocument: (a: { path?: string; format?: ExportFormat }) => post<SaveResult>("/document/save", a),
  previewDocument: (format: ExportFormat) => post<PreviewResponse>("/document/preview", { format }),
  discover: (a: { recursive: boolean; pattern?: string }) => post<DiscoverResult>("/document/discover", a),
  validate: () => post<ValidationReport>("/validate"),
  plan: (b: PlanRequest) => post<PlanResult>("/plan", b),
  undo: () => post<DocumentResponse>("/undo"),
  redo: () => post<DocumentResponse>("/redo"),
  getSettings: () => request<RuntimeSettings>("/settings"),
  updateSettings: (p: SettingsPatch) => put<DocumentResponse>("/settings", p),

  addTopology: (b: AddTopology) => post<DocumentResponse>("/topologies", b),
  updateTopology: (id: string, b: UpdateTopology) => put<DocumentResponse>(`/topologies/${id}`, b),
  removeTopology: (id: string) => del<DocumentResponse>(`/topologies/${id}`),
  setStartingStructure: (path: string | null) => put<DocumentResponse>("/simulation/starting-structure", { path }),

  createPhase: (b: PhaseCreate) => post<DocumentResponse>("/phases", b),
  updatePhase: (id: string, b: PhaseUpdate) => put<DocumentResponse>(`/phases/${id}`, b),
  reorderPhases: (phase_ids: string[]) => post<DocumentResponse>("/phases/reorder", { phase_ids }),
  deletePhase: (id: string, reassign_to?: string) =>
    del<DocumentResponse>(`/phases/${id}${reassign_to ? `?reassign_to=${encodeURIComponent(reassign_to)}` : ""}`),

  createStep: (phaseId: string, b: StepCreatePayload) => post<DocumentResponse>(`/phases/${phaseId}/steps`, b),
  reorderSteps: (phaseId: string, step_ids: string[]) => post<DocumentResponse>(`/phases/${phaseId}/steps/reorder`, { step_ids }),
  updateStep: (id: string, b: StepUpdatePayload) => put<DocumentResponse>(`/steps/${id}`, b),
  deleteStep: (id: string) => del<DocumentResponse>(`/steps/${id}`),
  moveStep: (id: string, b: StepMovePayload) => post<DocumentResponse>(`/steps/${id}/move`, b),

  assign: (b: AssignRequest) => post<DocumentResponse>("/assign", b),

  listFiles: (a: { path?: string; recursive?: boolean; include_all?: boolean }) => {
    const q = new URLSearchParams();
    if (a.path) q.set("path", a.path);
    if (a.recursive !== undefined) q.set("recursive", String(a.recursive));
    if (a.include_all !== undefined) q.set("include_all", String(a.include_all));
    return request<FileInfo[]>(`/files?${q.toString()}`);
  },
  fileMetadata: (path: string) => request<FileMetadata>(`/files/metadata?path=${encodeURIComponent(path)}`),
  fileRaw: (path: string, maxBytes = 4096) => request<RawFile>(`/files/raw?path=${encodeURIComponent(path)}&max_bytes=${maxBytes}`),
  relatedFiles: (stem: string) => request<Record<string, string>>(`/files/related/${encodeURIComponent(stem)}`),
};
