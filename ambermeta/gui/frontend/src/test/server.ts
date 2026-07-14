import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import type { DocumentResponse, ValidationReport } from "@/types";

export const emptyDocument: DocumentResponse = {
  base_directory: "/work", manifest_path: null, dirty: false, can_undo: false, can_redo: false,
  settings: { auto_link_restarts: true, strict_validation: true, allow_gaps: false, use_relative_paths: true },
  simulation: { version: 2, topologies: [], starting_structure: null, phases: [] },
};

export const emptyValidationReport: ValidationReport = {
  ok: true, totals: {}, protocol_issues: [], stage_issues: [], suggestions: [],
};

export const apiHandlers = [
  http.get("/api/document", () => HttpResponse.json(emptyDocument)),
  http.get("/api/settings", () => HttpResponse.json(emptyDocument.settings)),
  http.get("/api/files", () => HttpResponse.json([])),
  http.post("/api/validate", () => HttpResponse.json(emptyValidationReport)),
];
export const server = setupServer(...apiHandlers);
