import { useState } from "react";
import { Modal, Button } from "@/components/common";
import type { DiscoverRequest } from "@/api/client";

export function DiscoverModal(
  { open, onClose, onRun }:
  { open: boolean; onClose: () => void; onRun: (a: DiscoverRequest) => void }
) {
  const [recursive, setRecursive] = useState(true);
  const [pattern, setPattern] = useState("");
  // The server refuses a folder whose runs report different atom counts (several
  // systems, `ambermeta.systems`), and its message points here for a false alarm.
  const [asOne, setAsOne] = useState(false);
  return (
    <Modal open={open} title="Discover runs" onClose={onClose}>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={recursive} onChange={(e) => setRecursive(e.target.checked)} />
        <span>Search subdirectories</span>
      </label>
      <label className="block text-sm mt-3">
        <span className="text-ink-secondary">Filename pattern (optional)</span>
        <input value={pattern} onChange={(e) => setPattern(e.target.value)}
          className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
      </label>
      <label className="flex items-center gap-2 text-sm mt-3">
        <input type="checkbox" checked={asOne} aria-describedby="discover-as-one-hint"
          onChange={(e) => setAsOne(e.target.checked)} />
        <span>Treat everything here as one simulation</span>
      </label>
      <p id="discover-as-one-hint" className="text-sm text-ink-secondary ml-6">
        Runs of different sizes are separate systems, and Discover refuses them.
      </p>
      <div className="flex justify-end gap-2 mt-4">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary"
          onClick={() => {
            onRun({ recursive, pattern: pattern || undefined, as_one_simulation: asOne });
            onClose();
          }}>
          Run discover
        </Button>
      </div>
    </Modal>
  );
}
