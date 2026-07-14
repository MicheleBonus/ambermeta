import { ArrowDown } from "@/components/common";

/** Extracts a "<number> <unit>" magnitude (e.g. "20 ps") from a continuity-gap
 * suggestion's evidence/title text such as "Stage starts +20 ps after previous ended." */
export function parseGap(text: string): string | null {
  const m = text.match(/([+-]?\d+(?:\.\d+)?)\s*(ps|ns|fs)\b/i);
  if (!m) return null;
  return `${m[1].replace(/^\+/, "")} ${m[2]}`;
}

export function ContinuityArrow({ gap }: { gap?: string | null }) {
  const hasGap = !!gap;
  return (
    <div
      className={`flex items-center justify-center gap-1 py-0.5 text-xs ${
        hasGap ? "text-warning" : "text-ink-muted"
      }`}
    >
      <ArrowDown size={14} />
      {hasGap && <span>{gap}</span>}
    </div>
  );
}

export function MissingRunGhost({ name }: { name: string }) {
  return (
    <div className="rounded border border-dashed border-hairline bg-app px-2 py-1.5 text-xs font-mono text-ink-muted opacity-70">
      {name} <span className="italic">missing</span>
    </div>
  );
}
