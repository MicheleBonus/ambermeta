import { useDismissal, useSuggestions } from "./suggestionsContext";
import { useSelection, type SelKind } from "@/state/selection";
import { Button } from "@/components/common";
import type { Suggestion } from "@/types";

/** Where a card's subject is on the canvas, when it is about one step or one phase. */
function subjectOf(s: Suggestion): { kind: SelKind; id: string; label: string } | null {
  if (s.step_id) return { kind: "step", id: s.step_id, label: "Show step" };
  if (s.phase_id) return { kind: "phase", id: s.phase_id, label: "Show phase" };
  return null;
}

/** A card offers what the GUI does with it, and nothing else.
 *
 *  Accept, Adjust and Ignore all used to hide the card: "Accept" on a physics finding
 *  read as resolving it while `validate --strict` still failed on it. The server's
 *  `actions` name what could be done about a finding; the ones the GUI performs are
 *  showing its subject (the server's "Investigate") and hiding the card.
 *
 *  Applied cards had an Undo that called the history undo. They describe the document as
 *  it stands, after every validate, so that Undo reversed whichever edit came last -- a
 *  rename made after Discover, not the inference on the card. Undo stays in the top bar
 *  and on Ctrl+Z, where it says what it does. */
function SuggestionCard({ s, onDismiss }: { s: Suggestion; onDismiss: (s: Suggestion) => void }) {
  const { select } = useSelection();
  const subject = subjectOf(s);

  return (
    <div
      data-testid={`suggestion-${s.id}`}
      className="border border-hairline rounded p-2 space-y-1 bg-surface"
    >
      <div className="text-sm font-medium text-ink">{s.title}</div>
      <div className="text-xs text-ink-muted font-mono">{s.evidence}</div>
      <div className="flex gap-2 pt-1">
        {subject && (
          <Button variant={s.severity === "needs_you" ? "primary" : "ghost"}
            onClick={() => select(subject.kind, subject.id)}>{subject.label}</Button>
        )}
        <Button variant="ghost" onClick={() => onDismiss(s)}>Dismiss</Button>
      </div>
    </div>
  );
}

export function SuggestionsTray() {
  const suggestions = useSuggestions();
  const { isDismissed, dismiss } = useDismissal();

  const visible = suggestions.filter((s) => !isDismissed(s));
  const needsYou = visible.filter((s) => s.severity === "needs_you");
  const applied = visible.filter((s) => s.severity !== "needs_you");

  if (visible.length === 0) {
    return <div className="p-3 text-sm text-ink-muted">No suggestions right now.</div>;
  }

  return (
    <div className="flex flex-col gap-4 p-3" data-testid="suggestions-tray">
      {needsYou.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Needs you</div>
          {needsYou.map((s) => (
            <SuggestionCard key={s.id} s={s} onDismiss={dismiss} />
          ))}
        </div>
      )}
      {applied.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Applied</div>
          {applied.map((s) => (
            <SuggestionCard key={s.id} s={s} onDismiss={dismiss} />
          ))}
        </div>
      )}
    </div>
  );
}
