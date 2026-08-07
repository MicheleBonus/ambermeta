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
  /**
   * What the edit that produced this document could not do without inventing a link nobody
   * declared: a shared parent deleted out from under several lineages, a hand-set
   * "continues from" that crosses one. It describes the edit rather than the document — the
   * server clears it on the next mutation — so it is never a running total of anything.
   *
   * Required, not optional: the server always sends the key, and a fixture allowed to omit
   * it is a surface that silently reports nothing (see `makeStep`'s note in test/factories).
   */
  warnings: string[];
}
export interface Suggestion {
  id: string; kind: string; severity: "needs_you" | "applied" | "info";
  title: string; evidence: string; actions: string[];
  step_id?: string; phase_id?: string; base?: string; missing?: number[];
  /** missing_run: the lineage the finding is scoped to, null for the untagged bucket. */
  lineage?: string | null;
}
export interface MissingFile { kind: string; path: string; }
export interface StageIssue {
  name: string; ok: boolean; degraded: boolean;
  errors: string[]; warnings: string[]; info: string[];
  /** Non-INFO continuity notes for this stage. Emitted by the server since the beginning
   *  and dropped by the response model until it was declared there. */
  continuity: string[];
  missing_files: MissingFile[];
}
/** One declared member's share of the document. Absent from an untagged one. */
export interface LineageTotals { steps: number; time_ps: number; step_count: number; }
/** What the declared members do and do not agree about. `error` means they are not runs
 *  of the same thing; `warning` is a difference the user may well have meant. */
export interface CoherenceFinding {
  severity: "error" | "warning" | "info";
  kind: string;
  message: string;
}
export interface ValidationReport {
  ok: boolean; totals: Record<string, number>;
  lineages: Record<string, LineageTotals> | null;
  coherence: CoherenceFinding[];
  protocol_issues: string[];
  stage_issues: StageIssue[]; suggestions: Suggestion[];
}
// --- lineage proposal: what discovery inferred, never what it wrote (P2.2) ---

export interface ProposedSource { directory: string; run_count: number; }
/** One member `build_lineage_proposal` proposes — NOT a declared lineage. Nothing here is
 *  on any step's `lineage` yet: `step_ids` is what a `PATCH /steps/lineage` accepting this
 *  member would tag, and `sources` is the evidence a reviewer reads before doing that. */
export interface ProposedMember { tag: string; step_ids: string[]; sources: ProposedSource[]; }
/** One cross-directory restart handoff read off AMBER's own File Assignments block. */
export interface ProposedHandoff {
  consumer_id: string; producer_id: string;
  consumer: string; producer: string; evidence: string;
}
/**
 * What Discover — or a re-run of the layout inference over the open document — proposes.
 * Never written: nothing here corresponds to a `StepModel.lineage` that has actually been
 * set. `segments` is the raw material for a segment picker: the server, not the frontend,
 * owns the math of what a given `segment_index` counts over, so the picker renders
 * directly off this array rather than reconstructing it from step names.
 */
export interface LineageProposal {
  segment_index: number;
  segments: string[][];
  members: ProposedMember[];
  handoffs: ProposedHandoff[];
}
/**
 * `POST /steps/infer-lineages`'s reply: a proposal, or none, plus why not. Its own shape
 * rather than `DocumentResponse` — that route only reads the document (see its docstring:
 * "Writes nothing"), so returning one would claim an edit that never happened.
 */
export interface LineageProposalResponse { proposal: LineageProposal | null; warnings: string[]; }

export interface DiscoverResult {
  document: DocumentResponse; suggestions: Suggestion[]; warnings: string[];
  /**
   * Required, not optional, for the same reason as `warnings` above: the server always
   * sends the key (`DiscoverResponse.proposal: Optional[LineageProposal] = None` still
   * serialises on the wire), and a fixture allowed to omit it is a surface that silently
   * reports no proposal at all. `discover_draft(..., apply_tags=False)` never writes the
   * grouping it finds, so this is the only place it reaches the client until the strip
   * that reads it (`ProposalStrip`) sends it back through `PATCH /steps/lineage`.
   */
  proposal: LineageProposal | null;
}

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
  /** What the run found, in the same shape /validate returns. */
  suggestions: Suggestion[];
  lineages: Record<string, LineageTotals> | null;
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
  lineage?: string | null;
  expected_gap_ps?: number; gap_tolerance_ps?: number; notes?: string[];
}
/** A gap sent as null is cleared; omit the key to leave it alone. */
export interface StepUpdatePayload {
  name?: string; topology?: string | null; input_coords?: InputCoordsModel; files?: StepFilesPatch;
  /** Present (including null) sets or clears the tag; omit to leave it alone. */
  lineage?: string | null;
  expected_gap_ps?: number | null; gap_tolerance_ps?: number | null; notes?: string[];
}
/** Tag many steps in one request and one undo entry. An explicit id list, because
 *  `discover` puts every member's same-role runs in one phase. */
export interface StepsLineagePayload { ids: string[]; lineage: string | null; }
export interface StepMovePayload { phase_id: string; index: number; }
export type AssignTarget = "pool" | "starting_structure" | "phase_topology" | "step_topology" | "step_slot";
export type SlotName = "mdin" | "mdout" | "mdcrd" | "rst";
export interface AssignRequest {
  path: string; target_type: AssignTarget; target_id?: string; kind?: TopologyKind; slot?: SlotName;
}
