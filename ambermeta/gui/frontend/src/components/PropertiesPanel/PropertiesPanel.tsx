import { useEffect, useState } from "react";
import { useDocument, useUpdateStage, useBulkUpdate } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { SettingsPanel } from "./SettingsPanel";
import type { StageModel, StageRole, StageUpdate } from "@/types";

const ROLES = ["", "minimization", "heating", "equilibration", "production"];

export function PropertiesPanel() {
  const { data: doc } = useDocument();
  const { selectedId, selectedIds } = useSelection();
  const update = useUpdateStage();
  const bulk = useBulkUpdate();

  if (!doc) return null;

  if (selectedIds.length >= 2) {
    return (
      <div className="p-3 space-y-3 text-sm">
        <h2 className="font-semibold">{selectedIds.length} stages selected</h2>
        <label className="block">
          <span className="text-ink-secondary">Set role for all</span>
          <select className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app"
            defaultValue=""
            onChange={(e) =>
              bulk.mutate({ ids: selectedIds, update: { role: e.target.value as StageRole } })}>
            {ROLES.map((r) => <option key={r} value={r}>{r || "Unknown"}</option>)}
          </select>
        </label>
      </div>
    );
  }

  const stage = selectedId ? doc.stages.find((s) => s.id === selectedId) ?? null : null;
  if (!stage) return <SettingsPanel settings={doc.settings} />;
  return <StageForm key={stage.id} stage={stage} onCommit={(patch) => update.mutate({ id: stage.id, update: patch })} />;
}

const FILE_KINDS = ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"] as const;
type FileKind = (typeof FILE_KINDS)[number];

function StageForm(
  { stage, onCommit, onPickFile }:
  { stage: StageModel; onCommit: (p: StageUpdate) => void; onPickFile?: (slot: FileKind) => void }
) {
  const [name, setName] = useState(stage.name);
  const [role, setRole] = useState<StageRole>(stage.role as StageRole);
  const [gap, setGap] = useState(stage.expected_gap_ps?.toString() ?? "");
  const [tol, setTol] = useState(stage.gap_tolerance_ps?.toString() ?? "");
  const [notes, setNotes] = useState(stage.notes.join("\n"));

  // Re-sync the draft whenever the selected stage changes.
  useEffect(() => {
    setName(stage.name); setRole(stage.role as StageRole);
    setGap(stage.expected_gap_ps?.toString() ?? "");
    setTol(stage.gap_tolerance_ps?.toString() ?? "");
    setNotes(stage.notes.join("\n"));
  }, [stage.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  return (
    <div className="p-3 space-y-3 text-sm">
      <label className="block">
        <span className="text-ink-secondary">Name</span>
        <input aria-label="Name" value={name} onChange={(e) => setName(e.target.value)}
          onBlur={() => name !== stage.name && onCommit({ name })}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app" />
      </label>
      <label className="block">
        <span className="text-ink-secondary">Role</span>
        <select aria-label="Role" value={role}
          onChange={(e) => { setRole(e.target.value as StageRole); onCommit({ role: e.target.value as StageRole }); }}
          className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app">
          {ROLES.map((r) => <option key={r} value={r}>{r || "Unknown"}</option>)}
        </select>
      </label>
      <div className="space-y-1">
        <span className="text-ink-secondary">Files</span>
        {FILE_KINDS.map((k) => (
          <div key={k} className="flex items-center gap-2">
            <span className="w-14 text-ink-muted text-xs">{k}</span>
            <span className="flex-1 truncate font-mono text-xs">{stage[k] ?? "—"}</span>
            {onPickFile && (
              <button type="button" className="text-accent text-xs" onClick={() => onPickFile(k)}>Pick…</button>
            )}
            {stage[k] && (
              <button type="button" aria-label={`clear ${k}`} className="text-ink-muted text-xs"
                onClick={() => onCommit({ files: { [k]: "" } })}>×</button>
            )}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="text-ink-secondary">Expected gap (ps)</span>
          <input aria-label="Expected gap" value={gap} onChange={(e) => setGap(e.target.value)}
            onBlur={() => onCommit({ expected_gap_ps: num(gap) })}
            className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
        </label>
        <label className="block">
          <span className="text-ink-secondary">Tolerance (ps)</span>
          <input aria-label="Gap tolerance" value={tol} onChange={(e) => setTol(e.target.value)}
            onBlur={() => onCommit({ gap_tolerance_ps: num(tol) })}
            className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
        </label>
      </div>
      <label className="block">
        <span className="text-ink-secondary">Notes</span>
        <textarea aria-label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)}
          onBlur={() => onCommit({ notes: notes.split("\n").filter(Boolean) })}
          rows={3}
          className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app" />
      </label>
    </div>
  );
}
