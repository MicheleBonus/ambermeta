import { useState } from "react";
import { useSuggestions } from "@/components/Canvas/Canvas";
import { useUndo } from "@/api/hooks";
import { Button } from "@/components/common";
import type { Suggestion } from "@/types";

function hasAction(s: Suggestion, name: string): boolean {
  return s.actions.some((a) => a.toLowerCase() === name.toLowerCase());
}

function SuggestionCard({ s, onDismiss }: { s: Suggestion; onDismiss: (id: string) => void }) {
  const undo = useUndo();
  const needsYou = s.severity === "needs_you";

  return (
    <div
      data-testid={`suggestion-${s.id}`}
      className="border border-hairline rounded p-2 space-y-1 bg-surface"
    >
      <div className="text-sm font-medium text-ink">{s.title}</div>
      <div className="text-xs text-ink-muted font-mono">{s.evidence}</div>
      <div className="flex gap-2 pt-1">
        {needsYou ? (
          <>
            <Button variant="primary" onClick={() => onDismiss(s.id)}>Accept</Button>
            <Button variant="ghost" onClick={() => onDismiss(s.id)}>Adjust</Button>
            <Button variant="ghost" onClick={() => onDismiss(s.id)}>Ignore</Button>
          </>
        ) : (
          <>
            <Button variant="ghost" onClick={() => onDismiss(s.id)}>Dismiss</Button>
            {hasAction(s, "undo") && (
              <Button variant="ghost" onClick={() => undo.mutate()}>Undo</Button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export function SuggestionsTray() {
  const suggestions = useSuggestions();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const dismiss = (id: string) => setDismissed((prev) => new Set(prev).add(id));

  const visible = suggestions.filter((s) => !dismissed.has(s.id));
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
