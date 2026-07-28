import { ArrowDown, FileLabel } from "@/components/common";

/** Extracts a "<number> <unit>" magnitude (e.g. "20 ps") from a continuity-gap
 * suggestion's evidence/title text such as "Stage starts +20 ps after previous ended." */
export function parseGap(text: string): string | null {
  const m = text.match(/([+-]?\d+(?:\.\d+)?)\s*(ps|ns|fs)\b/i);
  if (!m) return null;
  return `${m[1].replace(/^\+/, "")} ${m[2]}`;
}

/**
 * The join between two consecutive steps.
 *
 * When the lower step continues from the upper one, the arrow carries the restart file
 * that actually passes between them. That file belongs to neither card on its own — it is
 * written by one run and read by the next — so showing it on the edge is what makes the
 * chain legible instead of a coordinate path repeated inside every step.
 */
export function ContinuityArrow({
  gap,
  link,
  base,
}: {
  gap?: string | null;
  /** The restart file handed from the step above to the step below, if they are chained. */
  link?: string | null;
  base?: string | null;
}) {
  const hasGap = !!gap;
  return (
    <div
      className={`flex min-w-0 items-center justify-center gap-1 py-0.5 text-xs ${
        hasGap ? "text-warning" : "text-ink-muted"
      }`}
    >
      <ArrowDown size={14} className="shrink-0" />
      {link && (
        <span
          title={`continues from the restart written above: ${link}`}
          className="inline-flex min-w-0 max-w-full items-baseline font-mono"
        >
          <FileLabel path={link} base={base ?? null} />
        </span>
      )}
      {hasGap && <span className="shrink-0">{gap}</span>}
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
