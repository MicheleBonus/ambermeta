import type { ReactNode } from "react";
import { useSetLineages } from "@/api/hooks";
import { useInlineRename } from "@/lib/useInlineRename";
import type { StepModel } from "@/types";

/**
 * One member's run of steps inside a phase, with the tag on it and a way to change it.
 *
 * The tag is the only thing standing between "these are two replicas" and "this is one
 * chain with a jump in the middle", and until now it appeared nowhere in the UI at all:
 * `groupSteps` used it invisibly, the step card did not show it, and the Inspector did not
 * either. A declared fact the user cannot see is one they cannot correct.
 *
 * Retagging goes through the bulk route rather than a loop of per-step PUTs. Not merely
 * for speed: every per-step write deep-copies the document onto the undo stack, so
 * annotating a 20 x 10 campaign evicts the Discover result being annotated, and leaves the
 * user 200 Ctrl+Z presses from where they started.
 */
export function LineageBand({
  lineage, steps, children,
}: {
  lineage: string | null;
  steps: StepModel[];
  children: ReactNode;
}) {
  const setLineages = useSetLineages();
  const ids = steps.map((s) => s.id);
  const label = lineage ?? "no lineage";
  const rename = useInlineRename(lineage ?? "", (next) =>
    setLineages.mutate({ ids, lineage: next }));

  return (
    <section
      data-lineage={lineage ?? ""}
      className="border-l-2 border-hairline pl-2 space-y-1.5"
    >
      <header className="flex items-center gap-2 text-xs text-ink-muted">
        {rename.editing ? (
          <input
            autoFocus
            aria-label={`set lineage for ${label}`}
            value={rename.value}
            onChange={(e) => rename.change(e.target.value)}
            onKeyDown={rename.keyDown}
            onBlur={rename.blur}
            className="px-1 py-0.5 border border-accent rounded bg-app text-xs text-ink"
          />
        ) : (
          <button
            type="button"
            onClick={rename.start}
            title="Rename this lineage, or tag these runs"
            className={`font-mono hover:underline ${lineage ? "text-ink" : "italic"}`}
          >
            {label}
          </button>
        )}
        <span>· {steps.length} run(s)</span>
        {lineage && (
          <button
            type="button"
            aria-label={`clear lineage ${lineage}`}
            title="Untag these runs"
            // Clearing is `null`, not "": the server reads presence, and an empty string
            // would name a member nobody can refer to.
            onClick={() => setLineages.mutate({ ids, lineage: null })}
            className="hover:text-ink"
          >
            clear
          </button>
        )}
      </header>
      <div className="space-y-1.5">{children}</div>
    </section>
  );
}

/**
 * The shared branch point N members hang off, when there is one.
 *
 * Stated rather than drawn: an arrow from one step to three would have to cross the bands
 * it is the whole point of the bands not to connect. This says which run they all read and
 * leaves the reader to draw the conclusion.
 */
export function FanOutNote({ producerName, count }: { producerName: string; count: number }) {
  return (
    <p className="text-xs text-ink-muted italic px-2 py-1">
      {count} lineages branch from {producerName}
    </p>
  );
}
