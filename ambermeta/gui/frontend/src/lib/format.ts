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
