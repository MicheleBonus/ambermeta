import type {
  DocumentResponse, SaveResult, PreviewResponse, ValidationReport,
  GlobalSettings, FileInfo, FileMetadata, StageCreate, StageUpdate,
  SettingsPatch, ExportFormat,
} from "@/types";

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

export const api = {
  getDocument: () => request<DocumentResponse>("/document"),
  openDocument: (path: string) => post<DocumentResponse>("/document/open", { path }),
  saveDocument: (args: { path?: string; format?: ExportFormat }) =>
    post<SaveResult>("/document/save", args),
  previewDocument: (format: ExportFormat) =>
    post<PreviewResponse>("/document/preview", { format }),
  discover: (args: { recursive: boolean; pattern?: string }) =>
    post<DocumentResponse>("/document/discover", args),

  createStage: (stage: StageCreate) => post<DocumentResponse>("/stages", stage),
  updateStage: (id: string, update: StageUpdate) =>
    put<DocumentResponse>(`/stages/${id}`, update),
  deleteStage: (id: string) =>
    request<DocumentResponse>(`/stages/${id}`, { method: "DELETE" }),
  reorderStages: (stage_ids: string[]) =>
    post<DocumentResponse>("/stages/reorder", { stage_ids }),
  bulkUpdateStages: (stage_ids: string[], update: StageUpdate) =>
    put<DocumentResponse>("/stages/bulk", { stage_ids, update }),

  getSettings: () => request<GlobalSettings>("/settings"),
  updateSettings: (patch: SettingsPatch) => put<DocumentResponse>("/settings", patch),

  undo: () => post<DocumentResponse>("/undo"),
  redo: () => post<DocumentResponse>("/redo"),

  validate: () => post<ValidationReport>("/validate"),
  linkRestarts: () => post<DocumentResponse>("/link-restarts"),

  listFiles: (args: { path?: string; recursive?: boolean; include_all?: boolean }) => {
    const q = new URLSearchParams();
    if (args.path) q.set("path", args.path);
    if (args.recursive !== undefined) q.set("recursive", String(args.recursive));
    if (args.include_all !== undefined) q.set("include_all", String(args.include_all));
    return request<FileInfo[]>(`/files?${q.toString()}`);
  },
  fileMetadata: (path: string) =>
    request<FileMetadata>(`/files/metadata?path=${encodeURIComponent(path)}`),
  relatedFiles: (stem: string) =>
    request<Record<string, string>>(`/files/related/${encodeURIComponent(stem)}`),
  sequences: () => request<Record<string, string[]>>("/sequences"),
};
