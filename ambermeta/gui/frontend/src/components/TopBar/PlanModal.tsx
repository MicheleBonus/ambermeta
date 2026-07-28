import { useEffect, useState } from "react";
import { Modal, Button } from "@/components/common";
import { useDocument, useFiles, usePlan } from "@/api/hooks";
import type { FileInfo, PlanRequest } from "@/types";

/** Comparable form of a user-typed path: separators and case are not meaningful here. */
function normalise(path: string): string {
  return path.trim().replace(/\\/g, "/").replace(/^\.\//, "").toLowerCase();
}

/**
 * Does `typed` name a file that is already on disk?
 *
 * Answered from the file tree the picker already fetches rather than from a new endpoint:
 * it only drives a warning, so a stale tree costs nothing, and asking the server would
 * mean a round trip per keystroke.
 */
function targetExists(typed: string, tree: FileInfo[], base: string | null): boolean {
  const want = normalise(typed);
  if (!want) return false;
  const prefix = base ? normalise(base) + "/" : "";
  let found = false;
  const walk = (n: FileInfo) => {
    if (found) return;
    if (!n.is_directory) {
      const p = normalise(n.path);
      if (p === want || (prefix && p === prefix + want)) found = true;
    }
    n.children?.forEach(walk);
  };
  tree.forEach(walk);
  return found;
}

/** One tickable output, its default filename, and what it is for. */
interface Output {
  key: "manifest" | "summary" | "methods_summary" | "stats_csv";
  label: string;
  hint: string;
  defaultPath: string;
}

const OUTPUTS: Output[] = [
  { key: "manifest", label: "Manifest",
    hint: "the document itself — what Open reads back",
    defaultPath: "ambermeta.yaml" },
  { key: "summary", label: "Protocol summary",
    hint: "every stage with its parsed parameters and timings",
    defaultPath: "summary.json" },
  { key: "methods_summary", label: "Methods summary",
    hint: "the reproducibility-critical subset, for a Materials & Methods section",
    defaultPath: "methods_summary.json" },
  { key: "stats_csv", label: "Statistics CSV",
    hint: "one row per stage of mdout averages — needs mdout files",
    defaultPath: "stats.csv" },
];

/**
 * Runs the same artifacts `ambermeta plan` writes, against the document in memory.
 *
 * The manifest is on the list because "build it, then plan it" is one intention: having
 * to Save, then open a terminal, then re-read the file the GUI just wrote is the seam
 * this closes.
 */
export function PlanModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data: doc } = useDocument();
  const { data: tree = [] } = useFiles({ recursive: true, include_all: true });
  const plan = usePlan();
  const base = doc?.base_directory ?? null;
  const [enabled, setEnabled] = useState<Record<string, boolean>>({
    manifest: true, summary: true, methods_summary: true, stats_csv: false,
  });
  const [paths, setPaths] = useState<Record<string, string>>(
    Object.fromEntries(OUTPUTS.map((o) => [o.key, o.defaultPath])),
  );
  const [summaryFormat, setSummaryFormat] = useState<"json" | "yaml">("json");

  // Seeded once per opening: a document that already has a file writes back to it rather
  // than quietly starting a second one beside it. Done here rather than by deriving the
  // value at render time, so that once the dialog is open what is typed is what is sent.
  useEffect(() => {
    if (!open) return;
    setPaths((s) => ({ ...s, manifest: doc?.manifest_path || s.manifest }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, doc?.manifest_path]);

  const ticked = OUTPUTS.filter((o) => enabled[o.key]);
  // A ticked row with an empty path used to be quietly nulled out of the request: the
  // user asked for a file, got no file, and no warning either. Now it blocks the run.
  const blank = ticked.filter((o) => !paths[o.key].trim());
  // Two rows aimed at one file destroy each other; the server rejects it, but saying so
  // here costs nothing and does not require a round trip to find out.
  const collisions = new Set(
    ticked.map((o) => normalise(paths[o.key]))
      .filter((p, i, all) => p && all.indexOf(p) !== i),
  );
  const existing = new Set(
    ticked.filter((o) => paths[o.key].trim() && targetExists(paths[o.key], tree, base))
      .map((o) => o.key),
  );
  const problem = (o: Output): string | null => {
    if (!paths[o.key].trim()) return "Needs a filename.";
    if (collisions.has(normalise(paths[o.key]))) return "Another output is aimed at this file.";
    return null;
  };

  const body: PlanRequest = {
    save_manifest_path: enabled.manifest ? paths.manifest.trim() || null : null,
    summary_path: enabled.summary ? paths.summary.trim() || null : null,
    methods_summary_path: enabled.methods_summary ? paths.methods_summary.trim() || null : null,
    stats_csv_path: enabled.stats_csv ? paths.stats_csv.trim() || null : null,
    summary_format: summaryFormat,
  };

  const close = () => { plan.reset(); onClose(); };

  return (
    <Modal open={open} title="Write plan outputs" onClose={close}>
      <p className="text-xs text-ink-secondary">
        Written relative to the launch directory
        {doc?.base_directory ? <span className="font-mono"> ({doc.base_directory})</span> : null}.
      </p>

      <div className="mt-3 space-y-3">
        {OUTPUTS.map((o) => (
          <div key={o.key} className="space-y-1">
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={!!enabled[o.key]}
                aria-label={o.label}
                onChange={(e) => setEnabled((s) => ({ ...s, [o.key]: e.target.checked }))}
                className="mt-1 accent-current"
              />
              <span>
                <span className="text-ink">{o.label}</span>
                <span className="block text-xs text-ink-muted">{o.hint}</span>
              </span>
            </label>
            {enabled[o.key] && (
              <>
                <input
                  aria-label={`${o.label} path`}
                  value={paths[o.key]}
                  onChange={(e) => setPaths((s) => ({ ...s, [o.key]: e.target.value }))}
                  className={`w-full px-2 py-1 border rounded bg-app font-mono text-xs text-ink ${
                    problem(o) ? "border-error" : "border-hairline"
                  }`}
                />
                {problem(o) ? (
                  <p className="text-xs text-error">{problem(o)}</p>
                ) : existing.has(o.key) ? (
                  // Every box is ticked by default, so the first click in a directory that
                  // already holds one of these names would replace it without a word.
                  <p className="text-xs text-warning">This file exists and will be replaced.</p>
                ) : null}
              </>
            )}
          </div>
        ))}

        {enabled.summary && (
          <label className="flex items-center gap-2 text-xs text-ink-secondary">
            Summary format
            <select
              aria-label="Summary format"
              value={summaryFormat}
              onChange={(e) => setSummaryFormat(e.target.value as "json" | "yaml")}
              className="px-1 py-0.5 border border-hairline rounded bg-app text-xs text-ink"
            >
              <option value="json">json</option>
              <option value="yaml">yaml</option>
            </select>
            {/* Matching the CLI, which writes this one as JSON only. */}
            <span className="text-ink-muted">the methods summary is always JSON</span>
          </label>
        )}
      </div>

      <div className="mt-4 flex items-center justify-end gap-2">
        <Button onClick={close}>Close</Button>
        <Button
          variant="primary"
          disabled={ticked.length === 0 || blank.length > 0 || collisions.size > 0 || plan.isPending}
          onClick={() => plan.mutate(body)}
        >
          {plan.isPending ? "Writing…" : "Write"}
        </Button>
      </div>

      {plan.data && (
        <div className="mt-3 rounded border border-hairline bg-app p-2">
          <p className="text-xs text-ink-secondary">
            {plan.data.stage_count} step(s)
            {typeof plan.data.totals.time_ps === "number" && plan.data.totals.time_ps > 0
              ? ` · ${plan.data.totals.time_ps} ps total`
              : null}
          </p>
          <ul className="mt-1 space-y-0.5">
            {plan.data.written.map((w) => (
              <li key={w.artifact} className="font-mono text-xs text-ink">
                <span className="text-valid">✓</span> {w.path}
              </li>
            ))}
            {/* A run where one path was unwritable still wrote the others; showing only
                an error would misreport what is on disk. */}
            {plan.data.failed.map((f) => (
              <li key={f.artifact} className="font-mono text-xs text-error">
                <span>✗</span> {f.path} — {f.error}
              </li>
            ))}
          </ul>
          {/* Also shown here, not only as a toast: the toast is in the corner while the
              user is reading this list, and "it wrote a file" is exactly the moment a
              caveat about that file matters. */}
          {plan.data.warnings.map((w) => (
            <p key={w} className="mt-1 text-xs text-warning">{w}</p>
          ))}
        </div>
      )}
    </Modal>
  );
}
