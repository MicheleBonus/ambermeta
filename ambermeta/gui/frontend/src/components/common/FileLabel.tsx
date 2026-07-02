import { fileLabel } from "@/lib/format";

export function FileLabel({ path, base }: { path: string | null; base: string | null }) {
  if (!path) return <span className="text-ink-muted">—</span>;
  const { folder, name, full } = fileLabel(path, base);
  return (
    <span className="inline-flex min-w-0 items-baseline" title={full}>
      {folder && <span className="truncate text-ink-muted">{folder}/</span>}
      <span className="shrink-0 text-ink">{name}</span>
    </span>
  );
}
