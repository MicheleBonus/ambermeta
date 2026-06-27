export type FileType = "prmtop" | "mdin" | "mdout" | "mdcrd" | "inpcrd" | "folder" | "other";
export type StageRole = "minimization" | "heating" | "equilibration" | "production" | "";
export type ExportFormat = "yaml" | "json" | "toml" | "csv";

export interface StageModel {
  id: string;
  name: string;
  role: string;
  prmtop: string | null;
  mdin: string | null;
  mdout: string | null;
  mdcrd: string | null;
  inpcrd: string | null;
  expected_gap_ps: number | null;
  gap_tolerance_ps: number | null;
  notes: string[];
}

export interface GlobalSettings {
  global_prmtop: string | null;
  hmr_prmtop: string | null;
  initial_coordinates: string | null;
  auto_link_restarts: boolean;
  strict_validation: boolean;
  allow_gaps: boolean;
  use_relative_paths: boolean;
}

export interface DocumentResponse {
  base_directory: string;
  manifest_path: string | null;
  dirty: boolean;
  can_undo: boolean;
  can_redo: boolean;
  settings: GlobalSettings;
  stages: StageModel[];
}

export interface SaveResult { document: DocumentResponse; warnings: string[]; }
export interface PreviewResponse { content: string; warnings: string[]; format: string; }

export interface MissingFile { kind: string; path: string; }
export interface StageIssue {
  name: string; ok: boolean; degraded: boolean;
  errors: string[]; warnings: string[]; info: string[]; missing_files: MissingFile[];
}
export interface ValidationReport {
  ok: boolean;
  totals: { steps: number; time_ps: number; stage_count: number };
  protocol_issues: string[];
  stage_issues: StageIssue[];
}

export interface FileInfo {
  path: string; name: string; file_type: FileType; is_directory: boolean;
  size: number | null; extension: string | null; parent: string | null;
  children: FileInfo[] | null;
}
export interface FileMetadata {
  file_path: string; file_type: FileType;
  metadata: { details: Record<string, unknown> | null; warnings: string[]; kind: string };
  warnings: string[];
}

export interface StageFilesPatch {
  prmtop?: string | null; mdin?: string | null; mdout?: string | null;
  mdcrd?: string | null; inpcrd?: string | null;
}
export interface StageCreate {
  name: string; role?: StageRole; files?: StageFilesPatch;
  expected_gap_ps?: number | null; gap_tolerance_ps?: number | null; notes?: string[];
}
export interface StageUpdate {
  name?: string; role?: StageRole; files?: StageFilesPatch;
  expected_gap_ps?: number | null; gap_tolerance_ps?: number | null; notes?: string[];
}
export interface SettingsPatch {
  global_prmtop?: string | null; hmr_prmtop?: string | null; initial_coordinates?: string | null;
  auto_link_restarts?: boolean; strict_validation?: boolean; allow_gaps?: boolean;
  use_relative_paths?: boolean;
}

// Functional display config only (icon name = lucide; color = token name).
export const FILE_TYPE_CONFIG: Record<FileType, { label: string; icon: string; color: string }> = {
  prmtop: { label: "Topology",     icon: "Atom",       color: "ink" },
  mdin:   { label: "Input",        icon: "FileInput",  color: "ink" },
  mdout:  { label: "Output",       icon: "FileOutput", color: "ink" },
  mdcrd:  { label: "Trajectory",   icon: "Film",       color: "ink" },
  inpcrd: { label: "Coordinates",  icon: "Move3d",     color: "ink" },
  folder: { label: "Folder",       icon: "Folder",     color: "ink-muted" },
  other:  { label: "File",         icon: "File",       color: "ink-muted" },
};

export const STAGE_ROLE_CONFIG: Record<string, { label: string }> = {
  minimization:  { label: "Minimization" },
  heating:       { label: "Heating" },
  equilibration: { label: "Equilibration" },
  production:    { label: "Production" },
  "":            { label: "Unknown" },
};
