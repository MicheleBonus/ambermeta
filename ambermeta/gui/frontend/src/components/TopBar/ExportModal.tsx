import { useState } from "react";
import { Modal, Button } from "@/components/common";
import { usePreview } from "@/api/hooks";
import type { ExportFormat } from "@/types";

export function ExportModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [format, setFormat] = useState<ExportFormat>("yaml");
  const preview = usePreview();
  return (
    <Modal open={open} title="Export manifest" onClose={() => { preview.reset(); onClose(); }}>
      <div className="flex items-center gap-2">
        <select aria-label="Format" value={format}
          onChange={(e) => setFormat(e.target.value as ExportFormat)}
          className="px-2 py-1 border border-hairline rounded bg-app text-sm">
          <option value="yaml">yaml</option><option value="json">json</option>
          <option value="toml">toml</option><option value="csv">csv</option>
        </select>
        <Button variant="primary" onClick={() => preview.mutate(format)}>Render</Button>
        {preview.data && (
          <Button onClick={() => navigator.clipboard?.writeText(preview.data.content)}>Copy</Button>
        )}
      </div>
      {preview.data && (
        <pre className="mt-3 p-2 bg-app border border-hairline rounded text-xs font-mono overflow-auto max-h-72">
          {preview.data.content}
        </pre>
      )}
    </Modal>
  );
}
