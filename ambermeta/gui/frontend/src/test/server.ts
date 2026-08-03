import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import type { DocumentResponse, ValidationReport } from "@/types";

export const emptyDocument: DocumentResponse = {
  base_directory: "/work", manifest_path: null, dirty: false, can_undo: false, can_redo: false,
  settings: { auto_link_restarts: true, strict_validation: true, allow_gaps: false, use_relative_paths: true },
  simulation: { version: 2, topologies: [], starting_structure: null, phases: [] },
  // The edit that produced this document had nothing to warn about — the ordinary case,
  // and what every handler here stands in for.
  warnings: [],
};

export const emptyValidationReport: ValidationReport = {
  ok: true, totals: {}, protocol_issues: [], stage_issues: [], suggestions: [],
};

export const apiHandlers = [
  http.get("/api/document", () => HttpResponse.json(emptyDocument)),
  http.get("/api/settings", () => HttpResponse.json(emptyDocument.settings)),
  http.get("/api/files", () => HttpResponse.json([])),
  http.post("/api/validate", () => HttpResponse.json(emptyValidationReport)),
  // The canvas header now carries removal controls, so any test that renders it can fire
  // these. setup.ts uses onUnhandledRequest:"error", which would otherwise turn a missing
  // handler into an opaque failure in a test that is not about topologies at all.
  http.post("/api/topologies", () => HttpResponse.json(emptyDocument)),
  http.put("/api/topologies/:id", () => HttpResponse.json(emptyDocument)),
  http.delete("/api/topologies/:id", () => HttpResponse.json(emptyDocument)),
  http.put("/api/simulation/starting-structure", () => HttpResponse.json(emptyDocument)),
  http.post("/api/undo", () => HttpResponse.json(emptyDocument)),
  http.post("/api/redo", () => HttpResponse.json(emptyDocument)),
];
export const server = setupServer(...apiHandlers);
