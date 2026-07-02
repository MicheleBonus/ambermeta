import { useEffect, useState } from "react";
import { useDocument, useUpdateStage, useBulkUpdate, useDeleteStage } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { Button, FileLabel } from "@/components/common";
import { SettingsPanel } from "./SettingsPanel";
import { FilePicker } from "@/components/FilePicker";
import { relativizePath, roleLabel } from "@/lib/format";
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
            aria-label="Set role for all"
            value=""
            onChange={(e) => {
              const v = e.target.value;
              if (v) bulk.mutate({ ids: selectedIds, update: { role: v as StageRole } });
            }}>
            <option value="">set role…</option>
            {ROLES.filter(Boolean).map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
          </select>
        </label>
      </div>
    );
  }

  const stage = selectedId ? doc.stages.find((s) => s.id === selectedId) ?? null : null;
  if (!stage) return <SettingsPanel settings={doc.settings} />;
  return <StageEditor key={stage.id} stage={stage}
    onCommit={(patch) => update.mutate({ id: stage.id, update: patch })} />;
}

const FILE_KINDS = ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"] as const;
type FileKind = (typeof FILE_KINDS)[number];

function StageEditor(
  { stage, onCommit }:
  { stage: StageModel; onCommit: (p: StageUpdate) => void }
) {
  const [pickSlot, setPickSlot] = useState<FileKind | null>(null);
  const deleteStage = useDeleteStage();
  const { clear } = useSelection();
  const { data: doc } = useDocument();
  return (
    <>
      <StageForm stage={stage} onCommit={onCommit} onPickFile={(slot) => setPickSlot(slot)} />
      <div className="px-3 pb-3">
        <Button variant="danger" onClick={() => { deleteStage.mutate(stage.id); clear(); }}>
          Delete stage
        </Button>
      </div>
      <FilePicker open={pickSlot !== null} mode="open" title={`Pick ${pickSlot ?? ""} file`}
        onClose={() => setPickSlot(null)}
        onPick={({ path }) => {
          if (pickSlot) onCommit({ files: { [pickSlot]: relativizePath(path, doc?.base_directory ?? null) } });
          setPickSlot(null);
        }} />
    </>
  );
}

function StageForm(
  { stage, onCommit, onPickFile }:
  { stage: StageModel; onCommit: (p: StageUpdate) => void; onPickFile?: (slot: FileKind) => void }
) {
  const { data: doc } = useDocument();
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
            <span className="flex-1 min-w-0 truncate font-mono text-xs">
              <FileLabel path={stage[k]} base={doc?.base_directory ?? null} />
            </span>
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
            onBlur={() => { const v = num(gap); if (v !== stage.expected_gap_ps) onCommit({ expected_gap_ps: v }); }}
            className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
        </label>
        <label className="block">
          <span className="text-ink-secondary">Tolerance (ps)</span>
          <input aria-label="Gap tolerance" value={tol} onChange={(e) => setTol(e.target.value)}
            onBlur={() => { const v = num(tol); if (v !== stage.gap_tolerance_ps) onCommit({ gap_tolerance_ps: v }); }}
            className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
        </label>
      </div>
      <label className="block">
        <span className="text-ink-secondary">Notes</span>
        <textarea aria-label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)}
          onBlur={() => {
            const newNotes = notes.split("\n").filter(Boolean);
            if (JSON.stringify(newNotes) !== JSON.stringify(stage.notes)) onCommit({ notes: newNotes });
          }}
          rows={3}
          className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app" />
      </label>
    </div>
  );
}
