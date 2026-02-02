// File types
export type FileType = 'prmtop' | 'mdin' | 'mdout' | 'mdcrd' | 'inpcrd' | 'folder' | 'other';

export interface FileInfo {
  path: string;
  name: string;
  file_type: FileType;
  is_directory: boolean;
  size?: number;
  extension?: string;
  parent?: string;
  children?: FileInfo[];
}

// Stage types
export type StageRole = 'minimization' | 'heating' | 'equilibration' | 'production' | '';

export interface StageFiles {
  prmtop?: string;
  mdin?: string;
  mdout?: string;
  mdcrd?: string;
  inpcrd?: string;
}

export interface StageValidation {
  is_valid: boolean;
  messages: string[];
  missing_files: string[];
  warnings: string[];
}

export interface Stage {
  id: string;
  name: string;
  role: StageRole;
  files: StageFiles;
  use_hmr_prmtop: boolean;  // If true, use HMR prmtop instead of normal global prmtop
  expected_gap_ps?: number;  // User-specified or undefined to use global default
  gap_tolerance_ps?: number;  // User-specified or undefined to use global default
  detected_duration_ps?: number;  // Auto-detected from mdin (dt * nstlim)
  notes: string[];
  validation: StageValidation;
  sequence_base?: string;
  sequence_index?: number;
}

export interface StageCreate {
  name: string;
  role?: StageRole;
  files?: StageFiles;
  use_hmr_prmtop?: boolean;
  expected_gap_ps?: number;
  gap_tolerance_ps?: number;
  notes?: string[];
}

export interface StageUpdate {
  name?: string;
  role?: StageRole;
  files?: StageFiles;
  use_hmr_prmtop?: boolean;
  expected_gap_ps?: number;
  gap_tolerance_ps?: number;
  notes?: string[];
}

// Settings types
export interface GlobalSettings {
  global_prmtop?: string;
  hmr_prmtop?: string;
  default_expected_gap_ps?: number;  // Default expected gap for all stages
  default_gap_tolerance_ps?: number;  // Default tolerance for all stages (default: 0.1)
  auto_link_restarts: boolean;
  validate_on_export: boolean;
  use_relative_paths: boolean;
}

// Protocol types
export interface ProtocolState {
  base_directory: string;
  settings: GlobalSettings;
  stages: Stage[];
}

// Export types
export type ExportFormat = 'yaml' | 'json' | 'toml' | 'csv';

export interface ExportRequest {
  format: ExportFormat;
  include_validation?: boolean;
  use_relative_paths?: boolean;
}

export interface ExportResponse {
  content: string;
  filename: string;
  format: ExportFormat;
}

// Validation types
export interface ValidationResult {
  is_valid: boolean;
  stage_validations: Record<string, StageValidation>;
  cross_stage_issues: string[];
  summary: string;
}

// Sequence types
export interface SequenceInfo {
  base_name: string;
  stages: string[];
  count: number;
}

// UI types
export interface DragItem {
  type: 'file' | 'stage';
  data: FileInfo | Stage;
}

// File type configuration
export const FILE_TYPE_CONFIG: Record<FileType, {
  icon: string;
  color: string;
  label: string;
}> = {
  prmtop: { icon: 'Dna', color: 'text-green-500', label: 'Topology' },
  mdin: { icon: 'Settings', color: 'text-yellow-500', label: 'Input' },
  mdout: { icon: 'BarChart3', color: 'text-cyan-500', label: 'Output' },
  mdcrd: { icon: 'Film', color: 'text-purple-500', label: 'Trajectory' },
  inpcrd: { icon: 'RefreshCw', color: 'text-blue-500', label: 'Coordinates' },
  folder: { icon: 'Folder', color: 'text-gray-500', label: 'Folder' },
  other: { icon: 'File', color: 'text-gray-400', label: 'Other' },
};

// Stage role configuration
export const STAGE_ROLE_CONFIG: Record<string, {
  color: string;
  bgColor: string;
  label: string;
}> = {
  minimization: { color: 'text-blue-600', bgColor: 'bg-blue-100', label: 'Minimization' },
  heating: { color: 'text-orange-600', bgColor: 'bg-orange-100', label: 'Heating' },
  equilibration: { color: 'text-green-600', bgColor: 'bg-green-100', label: 'Equilibration' },
  production: { color: 'text-purple-600', bgColor: 'bg-purple-100', label: 'Production' },
  '': { color: 'text-gray-500', bgColor: 'bg-gray-100', label: 'Unknown' },
};
