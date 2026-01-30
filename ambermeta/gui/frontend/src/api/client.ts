import type {
  FileInfo,
  Stage,
  StageCreate,
  StageUpdate,
  ProtocolState,
  GlobalSettings,
  ExportRequest,
  ExportResponse,
  ValidationResult,
  SequenceInfo,
} from '../types';

const API_BASE = '/api';

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Request failed');
  }

  return response.json();
}

// File endpoints
export async function listFiles(path?: string, recursive = true): Promise<FileInfo[]> {
  const params = new URLSearchParams();
  if (path) params.append('path', path);
  params.append('recursive', String(recursive));
  return request<FileInfo[]>(`/files?${params}`);
}

export async function getFileMetadata(path: string): Promise<{
  file_path: string;
  file_type: string;
  metadata: Record<string, unknown>;
  warnings: string[];
}> {
  const params = new URLSearchParams({ path });
  return request(`/files/metadata?${params}`);
}

// Stage endpoints
export async function listStages(): Promise<Stage[]> {
  return request<Stage[]>('/stages');
}

export async function createStage(stage: StageCreate): Promise<Stage> {
  return request<Stage>('/stages', {
    method: 'POST',
    body: JSON.stringify(stage),
  });
}

export async function getStage(id: string): Promise<Stage> {
  return request<Stage>(`/stages/${id}`);
}

export async function updateStage(id: string, update: StageUpdate): Promise<Stage> {
  return request<Stage>(`/stages/${id}`, {
    method: 'PUT',
    body: JSON.stringify(update),
  });
}

export async function deleteStage(id: string): Promise<{ status: string; id: string }> {
  return request(`/stages/${id}`, {
    method: 'DELETE',
  });
}

export async function reorderStages(stageIds: string[]): Promise<Stage[]> {
  return request<Stage[]>('/stages/reorder', {
    method: 'POST',
    body: JSON.stringify({ stage_ids: stageIds }),
  });
}

// Protocol endpoints
export async function getProtocol(): Promise<ProtocolState> {
  return request<ProtocolState>('/protocol');
}

export async function validateProtocol(): Promise<ValidationResult> {
  return request<ValidationResult>('/validate', {
    method: 'POST',
  });
}

export async function exportProtocol(exportRequest: ExportRequest): Promise<ExportResponse> {
  return request<ExportResponse>('/export', {
    method: 'POST',
    body: JSON.stringify(exportRequest),
  });
}

// Settings endpoints
export async function getSettings(): Promise<GlobalSettings> {
  return request<GlobalSettings>('/settings');
}

export async function updateSettings(settings: GlobalSettings): Promise<GlobalSettings> {
  return request<GlobalSettings>('/settings', {
    method: 'PUT',
    body: JSON.stringify(settings),
  });
}

// Session endpoints
export async function saveSession(filename: string): Promise<{ status: string; path: string }> {
  return request('/session/save', {
    method: 'POST',
    body: JSON.stringify({ filename }),
  });
}

export async function loadSession(filename: string): Promise<ProtocolState> {
  return request<ProtocolState>('/session/load', {
    method: 'POST',
    body: JSON.stringify({ filename }),
  });
}

// Sequence endpoints
export async function getSequences(): Promise<Record<string, SequenceInfo>> {
  return request<Record<string, SequenceInfo>>('/sequences');
}
