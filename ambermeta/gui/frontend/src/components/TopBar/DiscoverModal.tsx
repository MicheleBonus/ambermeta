import { useState } from "react";
import { Modal, Button } from "@/components/common";

export function DiscoverModal(
  { open, onClose, onRun }:
  { open: boolean; onClose: () => void; onRun: (a: { recursive: boolean; pattern?: string }) => void }
) {
  const [recursive, setRecursive] = useState(true);
  const [pattern, setPattern] = useState("");
  return (
    <Modal open={open} title="Discover stages" onClose={onClose}>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={recursive} onChange={(e) => setRecursive(e.target.checked)} />
        <span>Search subdirectories</span>
      </label>
      <label className="block text-sm mt-3">
        <span className="text-ink-secondary">Filename pattern (optional)</span>
        <input value={pattern} onChange={(e) => setPattern(e.target.value)}
          className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
      </label>
      <div className="flex justify-end gap-2 mt-4">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary"
          onClick={() => { onRun({ recursive, pattern: pattern || undefined }); onClose(); }}>
          Run discover
        </Button>
      </div>
    </Modal>
  );
}
