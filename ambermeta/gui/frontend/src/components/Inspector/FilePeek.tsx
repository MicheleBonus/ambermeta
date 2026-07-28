import { useDocument, useFileMetadata } from "@/api/hooks";
import { FileLabel } from "@/components/common";

interface ParsedMetadata { details?: Record<string, unknown>; kind?: string }

// Well-known fields shown up-front, before the user drills into "Full details".
const CURATED_KEYS = ["atoms", "residues", "frames", "steps", "hmr_active", "box"];

export function FilePeek({ path }: { path: string }) {
  const { data, isLoading } = useFileMetadata(path);
  const { data: doc } = useDocument();
  const metadata = data?.metadata as ParsedMetadata | undefined;
  const details = metadata?.details ?? {};
  const curated = CURATED_KEYS.filter((k) => k in details);

  return (
    <div className="p-3 border-b border-hairline shrink-0 space-y-1.5">
      {/* Splitting on "/" alone never fires on a Windows path, so the header used to show the
          whole absolute path and let `truncate` clip the basename off the right-hand end. */}
      <div className="flex min-w-0 font-mono text-sm text-ink">
        <FileLabel path={path} base={doc?.base_directory ?? null} />
      </div>
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
