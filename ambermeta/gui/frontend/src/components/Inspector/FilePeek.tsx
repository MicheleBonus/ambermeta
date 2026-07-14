import { useFileMetadata } from "@/api/hooks";

interface ParsedMetadata { details?: Record<string, unknown>; kind?: string }

// Well-known fields shown up-front, before the user drills into "Full details".
const CURATED_KEYS = ["atoms", "residues", "frames", "steps", "hmr_active", "box"];

export function FilePeek({ path }: { path: string }) {
  const { data, isLoading } = useFileMetadata(path);
  const metadata = data?.metadata as ParsedMetadata | undefined;
  const details = metadata?.details ?? {};
  const curated = CURATED_KEYS.filter((k) => k in details);
  const name = path.split("/").pop() ?? path;

  return (
    <div className="p-3 border-b border-hairline shrink-0 space-y-1.5">
      <div className="font-mono text-sm text-ink truncate" title={path}>{name}</div>
      {isLoading && <div className="text-xs text-ink-muted">Loading…</div>}
      {metadata?.kind && <div className="text-xs text-ink-secondary">{metadata.kind}</div>}
      {curated.length > 0 && (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 pt-1">
          {curated.map((key) => (
            <div key={key} className="contents">
              <dt className="text-xs text-ink-muted">{key}</dt>
              <dd className="text-xs font-mono text-ink truncate">{String(details[key])}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
