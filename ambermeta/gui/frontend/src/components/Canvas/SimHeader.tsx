import { useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import { useSelection } from "@/state/selection";
import {
  useAddTopology, useInferLineages, useRemoveTopology, useSetStartingStructure,
  useUpdateTopology,
} from "@/api/hooks";
import { FilePicker } from "@/components/FilePicker";
import { FileLabel, Plus, X } from "@/components/common";
import { fileLabel } from "@/lib/format";
import { guessTopologyKind } from "@/lib/topology";
import { useUndoOffer } from "@/lib/useUndoOffer";
import type { SimulationModel, TopologyKind, TopologyModel } from "@/types";

/** How many steps in the document run against `topologyId`. */
function usedBy(sim: SimulationModel, topologyId: string): number {
  return sim.phases.reduce(
    (n, p) => n + p.steps.filter((s) => s.topology === topologyId).length,
    0,
  );
}

function TopologyChip({
  topology,
  sim,
  base,
}: {
  topology: TopologyModel;
  sim: SimulationModel;
  base: string | null;
}) {
  const removeTopology = useRemoveTopology();
  const updateTopology = useUpdateTopology();
  const offerUndo = useUndoOffer();
  const steps = usedBy(sim, topology.id);
  const name = fileLabel(topology.path, base).name;

  // min-w-0 + max-w-full: this header sits outside the canvas' scroll container, so an
  // absolute path — one unbreakable token — would spill straight out of the pane.
  return (
    <span
      className={`inline-flex min-w-0 max-w-full items-center gap-1 px-2 py-1 rounded bg-app border border-hairline font-mono text-xs ${
        topology.kind === "hmr" ? "text-accent" : "text-ink"
      }`}
    >
      <FileLabel path={topology.path} base={base} />
      {/* The kind was guessed from the filename when the file was added and used to be
          unchangeable, so a plain prmtop living under a directory called hmr_runs was
          permanently mislabelled. */}
      <select
        aria-label={`topology kind for ${name}`}
        title="Is this the mass-repartitioned topology?"
        value={topology.kind}
        onChange={(e) =>
          updateTopology.mutate({ id: topology.id, body: { kind: e.target.value as TopologyKind } })
        }
        className="shrink-0 rounded border border-hairline bg-surface px-1 text-[10px] text-ink"
      >
        <option value="normal">normal</option>
        <option value="hmr">HMR</option>
      </select>
      <button
        type="button"
        aria-label={`remove topology ${name}`}
        title={
          steps > 0
            ? `Remove from the pool — ${steps} step(s) would be left with no topology`
            : "Remove from the pool"
        }
        onClick={() =>
          removeTopology.mutate(topology.id, {
            onSuccess: () =>
              offerUndo(
                steps > 0
                  ? `Removed ${name} — ${steps} step(s) now have no topology`
                  : `Removed ${name} from the pool`,
              ),
          })
        }
        className="shrink-0 text-ink-muted hover:text-error"
      >
        <X size={12} />
      </button>
    </span>
  );
}

export function SimHeader({
  sim,
  base,
}: {
  sim: SimulationModel;
  /** Document base directory, so pooled topologies read as labels rather than absolute paths. */
  base: string | null;
}) {
  const { sel, select } = useSelection();
  const { setNodeRef: setPoolRef, isOver: poolOver } = useDroppable({ id: "pool" });
  const { setNodeRef: setStartRef, isOver: startOver } = useDroppable({ id: "starting" });
  const setStartingStructure = useSetStartingStructure();
  const addTopology = useAddTopology();
  const inferLineages = useInferLineages();
  const offerUndo = useUndoOffer();
  const [picking, setPicking] = useState<"prmtop" | "inpcrd" | null>(null);
  const isSimSelected = sel.kind === "sim";

  return (
    <div className="bg-surface border-b border-hairline p-3 space-y-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => select("sim", null)}
          className={`text-sm font-medium ${isSimSelected ? "text-accent" : "text-ink"}`}
        >
          Simulation
        </button>
        {/* The same inference `discover` reports as [applied], offered again because a
            document reaches this canvas by other routes than a fresh scan — an opened
            manifest, or a tree whose steps have since been renamed. It refuses far more
            layouts than it accepts, and everything it refuses is left for the band headers
            to tag by hand, which is the point of the tag being declared rather than
            derived. */}
        <button
          type="button"
          disabled={sim.phases.every((p) => p.steps.length === 0)}
          onClick={() => inferLineages.mutate(undefined)}
          title="Tag runs by the directory segment that distinguishes them"
          className="ml-auto text-xs text-ink-muted hover:text-ink disabled:opacity-50"
        >
          Infer lineages
        </button>
      </div>

      <div
        ref={setPoolRef}
        className={`flex flex-wrap gap-2 items-center p-2 rounded border border-dashed border-hairline ${
          poolOver ? "bg-accent-subtle" : ""
        }`}
      >
        {sim.topologies.map((t) => (
          <TopologyChip key={t.id} topology={t} sim={sim} base={base} />
        ))}
        {/* Dropping a prmtop here still works; this is the no-drag way to do the same. */}
        <button
          type="button"
          onClick={() => setPicking("prmtop")}
          title="Add a topology to the pool"
          className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
        >
          <Plus size={12} /> add prmtop
        </button>
      </div>

      <div
        ref={setStartRef}
        className={`flex min-w-0 items-baseline gap-1 p-2 rounded border border-dashed border-hairline font-mono text-xs text-ink-secondary ${
          startOver ? "bg-accent-subtle" : ""
        }`}
      >
        <span className="shrink-0">starting structure:</span>
        {sim.starting_structure ? (
          <>
            <button
              type="button"
              onClick={() => setPicking("inpcrd")}
              aria-label={`change starting structure: ${sim.starting_structure}`}
              className="inline-flex min-w-0 items-baseline text-left hover:underline"
            >
              <FileLabel path={sim.starting_structure} base={base} />
            </button>
            <button
              type="button"
              aria-label="clear starting structure"
              title="Clear the starting structure"
              onClick={() =>
                setStartingStructure.mutate(null, {
                  onSuccess: () => offerUndo("Cleared the starting structure"),
                })
              }
              className="shrink-0 text-ink-muted hover:text-error"
            >
              <X size={12} />
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setPicking("inpcrd")}
            className="text-left text-ink-muted hover:underline"
          >
            drop one here, or choose a file
          </button>
        )}
      </div>

      {picking && (
        <FilePicker
          open
          mode="open"
          filterType={picking}
          title={picking === "prmtop" ? "Add a topology" : "Choose the starting structure"}
          onPick={({ path }) => {
            setPicking(null);
            if (picking === "inpcrd") setStartingStructure.mutate(path);
            // The same first guess the drop path makes; the chip's kind select corrects it.
            else addTopology.mutate({ path, kind: guessTopologyKind(path) });
          }}
          onClose={() => setPicking(null)}
        />
      )}
    </div>
  );
}
