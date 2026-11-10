import { useState } from "react";
import { useDismissal, useSuggestions } from "./suggestionsContext";
import { useSelection, type SelKind } from "@/state/selection";
import { Button } from "@/components/common";
import { useAcknowledge, useUnacknowledge } from "@/api/hooks";
import { canAcknowledge, findingText } from "@/lib/findings";
import type { Suggestion } from "@/types";

/** Where a card's subject is on the canvas, when it is about one step or one phase. */
function subjectOf(s: Suggestion): { kind: SelKind; id: string; label: string } | null {
  if (s.step_id) return { kind: "step", id: s.step_id, label: "Show step" };
  if (s.phase_id) return { kind: "phase", id: s.phase_id, label: "Show phase" };
  return null;
}

/** The note that settles a finding, written on the card itself.
 *
 *  A note is required: without one this would be Dismiss again, which records nothing,
 *  so the finding came back on the next Validate, in `--strict` and in the methods
 *  summary. The finding is sent as the line `validate` prints, which is how the CLI and
 *  the next Validate recognise it. */
function AcknowledgeForm({ s, onDone }: { s: Suggestion; onDone: () => void }) {
  const [note, setNote] = useState("");
  const acknowledge = useAcknowledge();
  const id = `ack-${s.id}`;
  return (
    <div className="space-y-1 pt-1">
      <label htmlFor={id} className="block text-xs text-ink-secondary">
        Why this finding stands
      </label>
      <textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} rows={2}
        className="w-full px-2 py-1 border border-hairline rounded text-sm bg-app" />
      <div className="flex gap-2">
        <Button variant="primary" disabled={!note.trim() || acknowledge.isPending}
          onClick={() => acknowledge.mutate({ finding: findingText(s), note: note.trim() },
                                            { onSuccess: onDone })}>
          Save note
        </Button>
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
    </div>
  );
}

/** A card offers what the GUI does with it, and nothing else.
 *
 *  Accept, Adjust and Ignore all used to hide the card: "Accept" on a physics finding
 *  read as resolving it while `validate --strict` still failed on it. The server's
 *  `actions` name what could be done about a finding; the ones the GUI performs are
 *  showing its subject (the server's "Investigate"), settling it with a note, and hiding
 *  the card.
 *
 *  Applied cards had an Undo that called the history undo. They describe the document as
 *  it stands, after every validate, so that Undo reversed whichever edit came last -- a
 *  rename made after Discover, not the inference on the card. Undo stays in the top bar
 *  and on Ctrl+Z, where it says what it does. */
function SuggestionCard({ s, onDismiss }: { s: Suggestion; onDismiss: (s: Suggestion) => void }) {
  const { select } = useSelection();
  const subject = subjectOf(s);
  const [writing, setWriting] = useState(false);
  const reopen = useUnacknowledge();

  return (
    <div
      data-testid={`suggestion-${s.id}`}
      className="border border-hairline rounded p-2 space-y-1 bg-surface"
    >
      <div className="text-sm font-medium text-ink">{s.title}</div>
      <div className="text-xs text-ink-muted font-mono">{s.evidence}</div>
      {s.acknowledged && (
        <div className="text-xs text-ink-secondary">
          <span className="font-medium">Note: </span><span>{s.acknowledged}</span>
        </div>
      )}
      {writing ? <AcknowledgeForm s={s} onDone={() => setWriting(false)} /> : (
        <div className="flex gap-2 pt-1">
          {subject && (
            <Button variant={s.severity === "needs_you" && !s.acknowledged ? "primary" : "ghost"}
              onClick={() => select(subject.kind, subject.id)}>{subject.label}</Button>
          )}
          {canAcknowledge(s) && (
            <Button variant="ghost" onClick={() => setWriting(true)}>Acknowledge…</Button>
          )}
          {s.acknowledged ? (
            <Button variant="ghost" onClick={() => reopen.mutate(findingText(s))}>Reopen</Button>
          ) : (
            <Button variant="ghost" onClick={() => onDismiss(s)}>Dismiss</Button>
          )}
        </div>
      )}
    </div>
  );
}

export function SuggestionsTray() {
  const suggestions = useSuggestions();
  const { isDismissed, dismiss } = useDismissal();

  const visible = suggestions.filter((s) => !isDismissed(s));
  const acknowledged = visible.filter((s) => s.acknowledged);
  const needsYou = visible.filter((s) => s.severity === "needs_you" && !s.acknowledged);
  const applied = visible.filter((s) => s.severity !== "needs_you" && !s.acknowledged);

  if (visible.length === 0) {
    return <div className="p-3 text-sm text-ink-muted">No suggestions right now.</div>;
  }

  const group = (label: string, list: Suggestion[]) => list.length > 0 && (
    <div className="space-y-2">
      <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide">{label}</div>
      {list.map((s) => <SuggestionCard key={s.id} s={s} onDismiss={dismiss} />)}
    </div>
  );

  return (
    <div className="flex flex-col gap-4 p-3" data-testid="suggestions-tray">
      {group("Needs you", needsYou)}
      {group("Acknowledged", acknowledged)}
      {group("Applied", applied)}
    </div>
  );
}
