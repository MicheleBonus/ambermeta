import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { Suggestion } from "@/types";

export const SuggestionsContext = createContext<Suggestion[]>([]);

export function useSuggestions(): Suggestion[] {
  return useContext(SuggestionsContext);
}

/** What a card is about, independent of where it sits in the list.
 *
 *  A suggestion's `id` is its position (`sug_1`, `sug_r_4`), renumbered on every validate.
 *  Keyed on the id, a dismissal moved to whichever card took that position after an
 *  edit: a new "missing run" finding arrived as `sug_1` and was hidden in place of the
 *  card that had been dismissed. The content is what the user dismissed, so the content
 *  is the key; a finding whose text changes is a new finding and is shown again. */
export function suggestionKey(s: Suggestion): string {
  return [s.kind, s.step_id ?? "", s.phase_id ?? "", s.lineage ?? "", s.title, s.evidence]
    .join("␟");
}

interface Dismissal {
  isDismissed: (s: Suggestion) => boolean;
  dismiss: (s: Suggestion) => void;
}

const DismissalCtx = createContext<Dismissal | null>(null);

/** Dismissals for the browser session. Held above the tray, because the inspector
 *  replaces the tray with the step editor whenever a step is selected, and a set kept in
 *  the tray went with it: every dismissed card came back. */
export function SuggestionDismissalProvider({ children }: { children: ReactNode }) {
  const [keys, setKeys] = useState<ReadonlySet<string>>(new Set());
  const value = useMemo<Dismissal>(() => ({
    isDismissed: (s) => keys.has(suggestionKey(s)),
    dismiss: (s) => setKeys((prev) => new Set(prev).add(suggestionKey(s))),
  }), [keys]);
  return <DismissalCtx.Provider value={value}>{children}</DismissalCtx.Provider>;
}

export function useDismissal(): Dismissal {
  const c = useContext(DismissalCtx);
  if (!c) throw new Error("useDismissal outside SuggestionDismissalProvider");
  return c;
}
