import { fileLabel } from "@/lib/format";

/**
 * Renders a file path as a muted folder qualifier plus its basename (extension
 * included), so that same-name files in different folders — and same-stem files
 * with different extensions — stay distinguishable.
 *
 * Both parts can shrink, and the folder is weighted to give way first, so a
 * narrow parent eats the qualifier before it touches the name. Neither part is
 * `shrink-0`: a `shrink-0` name makes the flex box's min-content width the full
 * basename width, which pushes the label past `max-w-full` and leaves an
 * ancestor's `overflow:hidden` to hard-clip the tail — no ellipsis, no
 * extension. The full path stays reachable as the tooltip either way.
 */
export function FileLabel({ path, base }: { path: string | null; base: string | null }) {
  if (!path) return <span className="text-ink-muted">—</span>;
  const { folder, name, full } = fileLabel(path, base);
  return (
    <span className="inline-flex min-w-0 max-w-full items-baseline" title={full}>
      {folder && <span className="min-w-0 shrink-[100] truncate text-ink-muted">{folder}/</span>}
      <span className="min-w-0 truncate text-ink">{name}</span>
    </span>
  );
}
