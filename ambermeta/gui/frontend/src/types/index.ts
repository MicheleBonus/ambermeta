export type TopologyKind = "normal" | "hmr";
export type StageRole = "minimization" | "heating" | "equilibration" | "production" | "";
export type ExportFormat = "yaml" | "json";

export interface TopologyModel { id: string; path: string; kind: TopologyKind; }
export interface InputCoordsModel { source: "starting_structure" | "step" | "path"; ref: string | null; path: string | null; }
export interface StepModel {
  id: string; name: string; topology: string | null; input_coords: InputCoordsModel;
  mdin: string | null; mdout: string | null; mdcrd: string | null;
  /** The restart this step writes. The next step reads it — see `resolved_input_coords`. */
  rst: string | null;
  /** Which run lineage (replica, branch, pose) this step belongs to; null = untagged. */
  lineage: string | null;
  /** Server-resolved: the coordinate file this step actually reads, following the chain. */
  resolved_input_coords: string | null;
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

/** The artifacts `ambermeta plan` writes. A null path means "do not write this one". */
export interface PlanRequest {
  summary_path?: string | null;
  methods_summary_path?: string | null;
  stats_csv_path?: string | null;
  summary_format?: "json" | "yaml";
  save_manifest_path?: string | null;
}
export interface WrittenFile { artifact: string; path: string; }
export interface FailedFile { artifact: string; path: string; error: string; }
export interface PlanResult {
  written: WrittenFile[];
  /** Artifacts whose path could not be written; the rest of the run still landed. */
  failed: FailedFile[];
  warnings: string[];
  stage_count: number; totals: Record<string, number>; document: DocumentResponse;
}

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
/** `topology` present (including null) sets or clears it on every step of the phase. */
export interface PhaseUpdate { name?: string; role?: StageRole; topology?: string | null; }
export interface StepFilesPatch { mdin?: string; mdout?: string; mdcrd?: string; rst?: string; }
export interface StepCreatePayload {
  name: string; topology?: string | null; input_coords?: InputCoordsModel;
  mdin?: string; mdout?: string; mdcrd?: string; rst?: string;
  expected_gap_ps?: number; gap_tolerance_ps?: number; notes?: string[];
}
/** A gap sent as null is cleared; omit the key to leave it alone. */
export interface StepUpdatePayload {
  name?: string; topology?: string | null; input_coords?: InputCoordsModel; files?: StepFilesPatch;
  expected_gap_ps?: number | null; gap_tolerance_ps?: number | null; notes?: string[];
}
export interface StepMovePayload { phase_id: string; index: number; }
export type AssignTarget = "pool" | "starting_structure" | "phase_topology" | "step_topology" | "step_slot";
export type SlotName = "mdin" | "mdout" | "mdcrd" | "rst";
export interface AssignRequest {
  path: string; target_type: AssignTarget; target_id?: string; kind?: TopologyKind; slot?: SlotName;
}
