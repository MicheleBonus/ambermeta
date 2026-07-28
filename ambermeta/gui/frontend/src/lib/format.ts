export function formatPs(v: number | null): string {
  if (v === null) return "—";
  return `${v} ps`;
}

export function formatCount(n: number | null): string {
  if (n === null) return "—";
  return n.toLocaleString("en-US");
}

export function roleLabel(role: string): string {
  return role ? role : "Unknown";
}

/** Split on both posix and windows separators — paths come from the OS as-is. */
function splitPath(p: string): string[] {
  return p.split(/[\\/]/);
}

/**
 * Drop the leading `base` directory from an absolute `path`.
 * Returns "" when the path *is* the base, and the untouched path when it does
 * not live under the base (or when there is no base at all).
 */
export function relativizePath(path: string, base: string | null): string {
  if (!base) return path;
  const nb = base.replace(/[\\/]+$/, "");
  if (!nb) return path;
  if (path === nb) return "";
  if (path.startsWith(nb + "/") || path.startsWith(nb + "\\")) {
    return path.slice(nb.length + 1);
  }
  return path;
}

/**
 * The basename of `path` without its final extension — the default name for a
 * step created from a dropped file ("/work/equil/01_min.mdin" -> "01_min").
 */
export function stemName(path: string): string {
  const base = splitPath(path).pop() ?? path;
  return base.replace(/\.[^.]+$/, "");
}

/**
 * Break a file path into a display pair: the parent folders that disambiguate
 * it (`folder`, always "/"-joined) and the basename *with* its extension
 * (`name`), plus the original absolute path for tooltips (`full`).
 */
export function fileLabel(
  input: string,
  base?: string | null
): { folder: string; name: string; full: string } {
  const rel = relativizePath(input, base ?? null);
  const parts = splitPath(rel);
  const name = parts.pop() ?? rel;
  return { folder: parts.join("/"), name, full: input };
}
