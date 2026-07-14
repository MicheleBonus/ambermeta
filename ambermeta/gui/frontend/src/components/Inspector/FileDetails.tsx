import { useState } from "react";
import { useFileMetadata, useFileRaw } from "@/api/hooks";

interface ParsedMetadata { details?: Record<string, unknown>; kind?: string }

type TabId = "overview" | "details" | "raw" | "warnings";
const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "details", label: "Full details" },
  { id: "raw", label: "Raw file" },
  { id: "warnings", label: "Warnings" },
];

export function FileDetails({ path }: { path: string }) {
  const [tab, setTab] = useState<TabId>("overview");
  const { data } = useFileMetadata(path);
  const metadata = data?.metadata as ParsedMetadata | undefined;
  const details = metadata?.details ?? {};
  const warnings = data?.warnings ?? [];

  return (
    <div className="flex flex-col flex-1 min-h-0 file-details">
      <div role="tablist" className="flex border-b border-hairline shrink-0">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-2 text-xs ${
              tab === t.id ? "text-ink border-b-2 border-accent" : "text-ink-muted"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-3">
        {tab === "overview" && <Overview kind={metadata?.kind} details={details} warnings={warnings} />}
        {tab === "details" && <FullDetails details={details} />}
        {tab === "raw" && <RawTab path={path} />}
        {tab === "warnings" && <Warnings warnings={warnings} />}
      </div>
    </div>
  );
}

function Overview(
  { kind, details, warnings }: { kind?: string; details: Record<string, unknown>; warnings: string[] }
) {
  const count = Object.keys(details).length;
  return (
    <div className="text-sm text-ink-secondary space-y-1">
      {kind && (
        <div>
          Kind: <span className="font-mono text-ink">{kind}</span>
        </div>
      )}
      <div>{count} parsed field{count === 1 ? "" : "s"}.</div>
      {warnings.length > 0 && <div className="text-warning">{warnings.length} warning{warnings.length === 1 ? "" : "s"}.</div>}
    </div>
  );
}

function FullDetails({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details);
  if (entries.length === 0) return <div className="text-sm text-ink-muted">No parsed fields.</div>;
  return (
    <dl className="space-y-1">
      {entries.map(([key, value]) => (
        <div key={key} className="flex items-baseline justify-between gap-2 text-sm py-1 border-b border-hairline last:border-0">
          <dt className="text-ink-secondary">{key}</dt>
          <dd className="font-mono text-ink text-right break-all">{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function RawTab({ path }: { path: string }) {
  const { data, isLoading } = useFileRaw(path);
  if (isLoading) return <div className="text-sm text-ink-muted">Loading…</div>;
  if (!data) return null;
  return (
    <>
      {data.truncated && <div className="text-xs text-warning pb-2">Truncated — showing a prefix of the file.</div>}
      <pre className="font-mono text-xs whitespace-pre-wrap break-all">{data.content}</pre>
    </>
  );
}

function Warnings({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return <div className="text-sm text-ink-muted">No warnings.</div>;
  return (
    <ul className="space-y-1">
      {warnings.map((w, i) => (
        <li key={i} className="text-sm text-warning">{w}</li>
      ))}
    </ul>
  );
}
