export type TopologyKind = "normal" | "hmr";
export type StageRole = "minimization" | "heating" | "equilibration" | "production" | "";
export type ExportFormat = "yaml" | "json";

export interface TopologyModel { id: string; path: string; kind: TopologyKind; }
export interface InputCoordsModel { source: "starting_structure" | "step" | "path"; ref: string | null; path: string | null; }
export interface StepModel {
  id: string; name: string; topology: string | null; input_coords: InputCoordsModel;
  mdin: string | null; mdout: string | null; mdcrd: string | null;
  expected_gap_ps: number | null; gap_tolerance_ps: number | null; notes: string[];
}
export interface PhaseModel { id: string; name: string; role: StageRole; steps: StepModel[]; }
export interface SimulationModel {
  version: number; topologies: TopologyModel[]; starting_structure: string | null; phases: PhaseModel[];
}
export interface RuntimeSettings {
  auto_link_restarts: boolean; strict_validation: boolean; allow_gaps: boolean; use_relative_paths: boolean;
}
export interface DocumentResponse {
  base_directory: string; manifest_path: string | null; dirty: boolean;
  can_undo: boolean; can_redo: boolean; settings: RuntimeSettings; simulation: SimulationModel;
}
export interface Suggestion {
  id: string; kind: string; severity: "needs_you" | "applied" | "info";
  title: string; evidence: string; actions: string[];
  step_id?: string; phase_id?: string; base?: string; missing?: number[];
}
export interface MissingFile { kind: string; path: string; }
export interface StageIssue {
  name: string; ok: boolean; degraded: boolean;
  errors: string[]; warnings: string[]; info: string[]; missing_files: MissingFile[];
}
export interface ValidationReport {
  ok: boolean; totals: Record<string, number>; protocol_issues: string[];
  stage_issues: StageIssue[]; suggestions: Suggestion[];
}
export interface DiscoverResult { document: DocumentResponse; suggestions: Suggestion[]; warnings: string[]; }

export type FileType = "prmtop" | "mdin" | "mdout" | "mdcrd" | "inpcrd" | "folder" | "other";
export interface FileInfo {
  path: string; name: string; file_type: FileType; is_directory: boolean;
  size: number | null; extension: string | null; parent: string | null; children: FileInfo[] | null;
}
export interface FileMetadata { file_path: string; file_type: FileType; metadata: Record<string, unknown>; warnings: string[]; }
export interface RawFile { path: string; content: string; truncated: boolean; }

// --- request bodies ---
export interface AddTopology { path: string; kind: TopologyKind; }
export interface UpdateTopology { path?: string; kind?: TopologyKind; }
export interface SetStartingStructure { path: string | null; }
export interface PhaseCreate { name: string; role: StageRole; }
export interface PhaseUpdate { name?: string; role?: StageRole; }
export interface StepFilesPatch { mdin?: string; mdout?: string; mdcrd?: string; }
export interface StepCreatePayload {
  name: string; topology?: string | null; input_coords?: InputCoordsModel;
  mdin?: string; mdout?: string; mdcrd?: string;
  expected_gap_ps?: number; gap_tolerance_ps?: number; notes?: string[];
}
export interface StepUpdatePayload {
  name?: string; topology?: string | null; input_coords?: InputCoordsModel; files?: StepFilesPatch;
  expected_gap_ps?: number; gap_tolerance_ps?: number; notes?: string[];
}
export interface StepMovePayload { phase_id: string; index: number; }
export type AssignTarget = "pool" | "starting_structure" | "phase_topology" | "step_topology" | "step_slot";
export interface AssignRequest {
  path: string; target_type: AssignTarget; target_id?: string; kind?: TopologyKind; slot?: "mdin" | "mdout" | "mdcrd";
}
