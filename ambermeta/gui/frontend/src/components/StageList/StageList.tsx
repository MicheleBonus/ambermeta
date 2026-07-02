import { useMemo, useState } from "react";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { ChevronRight, ChevronDown } from "lucide-react";
import { useDocument, useSequences, useBulkUpdate } from "@/api/hooks";
import { useSelection } from "@/state/selection";
import { StageCard } from "./StageCard";
import { roleLabel } from "@/lib/format";
import type { StageModel, StageRole } from "@/types";

// NOTE: the DndContext + onDragEnd (reorder + file-assign) live in App.tsx — see
// Task 6 "Wire the app-level DndContext" step. StageList only provides the
// SortableContext for the stage rows; it does NOT own a DndContext.

interface Group { base: string; ids: string[]; }
type Row = { type: "stage"; stage: StageModel } | { type: "group"; group: Group };
const ROLE_OPTIONS: StageRole[] = ["", "minimization", "heating", "equilibration", "production"];

export function StageList() {
  const { data: doc } = useDocument();
  const { data: sequences = {} } = useSequences();
  const bulk = useBulkUpdate();
  const { selectedIds, select } = useSelection();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const stages = doc?.stages ?? [];

  const groups: Group[] = useMemo(
    () => Object.entries(sequences)
      .filter(([, ids]) => ids.length >= 2)
      .map(([base, ids]) => ({ base, ids })),
    [sequences]
  );

  const rows: Row[] = useMemo(() => {
    const out: Row[] = [];
    const emittedGroup = new Set<string>();
    for (const s of stages) {
      const g = groups.find((gr) => gr.ids.includes(s.id));
      if (g) {
        if (!emittedGroup.has(g.base)) { out.push({ type: "group", group: g }); emittedGroup.add(g.base); }
        if (expanded[g.base]) out.push({ type: "stage", stage: s });
      } else {
        out.push({ type: "stage", stage: s });
      }
    }
    return out;
  }, [stages, groups, expanded]);

  const toggle = (base: string) => setExpanded((e) => ({ ...e, [base]: !e[base] }));

  function renderRow(row: Row) {
    if (row.type === "group") {
      return (
        <div key={`g:${row.group.base}`}
          className="flex items-center gap-2 px-3 py-1.5 bg-app border-b border-hairline text-sm">
          <button aria-label="toggle group" onClick={() => toggle(row.group.base)}
            className="flex items-center gap-1 font-medium">
            {expanded[row.group.base] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            {row.group.base} · {row.group.ids.length} runs
          </button>
          <span className="flex-1" />
          <select aria-label="group role"
            className="text-xs border border-hairline rounded bg-surface px-1 py-0.5"
            value=""
            onChange={(e) => {
              const v = e.target.value;
              if (v) bulk.mutate({ ids: row.group.ids, update: { role: v as StageRole } });
            }}>
            <option value="">set role…</option>
            {ROLE_OPTIONS.filter(Boolean).map((r) => (
              <option key={r} value={r}>{roleLabel(r)}</option>
            ))}
          </select>
        </div>
      );
    }
    return (
      <StageCard key={row.stage.id} stage={row.stage}
        index={stages.indexOf(row.stage)}
        isSelected={selectedIds.includes(row.stage.id)}
        onSelect={(e) => select(row.stage.id, { additive: e.ctrlKey || e.metaKey })} />
    );
  }

  return (
    <SortableContext items={stages.map((s) => s.id)} strategy={verticalListSortingStrategy}>
      <div className="h-full overflow-auto">
        {rows.length === 0 && (
          <p className="p-4 text-sm text-ink-muted">No stages. Use Discover or drag files in.</p>
        )}
        {rows.map((row) => renderRow(row))}
      </div>
    </SortableContext>
  );
}
