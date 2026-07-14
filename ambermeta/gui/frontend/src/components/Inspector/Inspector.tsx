import { useSelection } from "@/state/selection";
import { FilePeek } from "./FilePeek";
import { FileDetails } from "./FileDetails";

export function Inspector() {
  const { sel } = useSelection();

  if (sel.kind === "file" && sel.id) {
    const path = sel.id;
    return (
      <div className="flex flex-col h-full">
        <FilePeek path={path} />
        <FileDetails path={path} />
      </div>
    );
  }

  if (sel.kind === "step" && sel.id) {
    // Filled in by the step-editing task; a stub keeps the pane usable meanwhile.
    return <div className="p-3 text-sm text-ink-muted">Step editor.</div>;
  }

  if (sel.kind === "phase" && sel.id) {
    // Filled in by the phase-editing task; a stub keeps the pane usable meanwhile.
    return <div className="p-3 text-sm text-ink-muted">Phase editor.</div>;
  }

  if (sel.kind === "sim") {
    // Filled in by the sim-settings task; a stub keeps the pane usable meanwhile.
    return <div className="p-3 text-sm text-ink-muted">Simulation settings.</div>;
  }

  return <div className="p-3 text-sm text-ink-muted">Pick a file to inspect it.</div>;
}
