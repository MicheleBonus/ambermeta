import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import type { DocumentResponse } from "@/types";

export const emptyDocument: DocumentResponse = {
  base_directory: "/work",
  manifest_path: null,
  dirty: false,
  can_undo: false,
  can_redo: false,
  settings: {
    global_prmtop: null, hmr_prmtop: null, initial_coordinates: null,
    auto_link_restarts: true, strict_validation: true, allow_gaps: false,
    use_relative_paths: true,
  },
  stages: [],
};

export const apiHandlers = [
  http.get("/api/document", () => HttpResponse.json(emptyDocument)),
  http.get("/api/settings", () => HttpResponse.json(emptyDocument.settings)),
  http.get("/api/files", () => HttpResponse.json([])),
  http.get("/api/sequences", () => HttpResponse.json({})),
];

export const server = setupServer(...apiHandlers);
