import { STAGE_ROLE_CONFIG } from "@/types";

export function formatPs(v: number | null): string {
  if (v === null) return "—";
  return `${v} ps`;
}

export function formatCount(n: number | null): string {
  if (n === null) return "—";
  return n.toLocaleString("en-US");
}

export function roleLabel(role: string): string {
  return STAGE_ROLE_CONFIG[role]?.label ?? (role || "Unknown");
}

function splitPath(p: string): string[] {
  return p.split(/[\\/]/);
}

export function relativizePath(path: string, base: string | null): string {
  if (!base) return path;
  const nb = base.replace(/[\\/]+$/, "");
  if (path === nb) return "";
  if (path.startsWith(nb + "/") || path.startsWith(nb + "\\")) {
    return path.slice(nb.length + 1);
  }
  return path;
}

export function fileLabel(
  input: string,
  base?: string | null
): { folder: string; name: string; full: string } {
  const rel = relativizePath(input, base ?? null);
  const parts = splitPath(rel);
  const name = parts.pop() ?? rel;
  return { folder: parts.join("/"), name, full: input };
}
