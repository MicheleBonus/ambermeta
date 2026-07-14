import { createContext, useContext, useEffect, useState } from "react";
import { useDocument, useValidate } from "@/api/hooks";
import { SimHeader } from "./SimHeader";
import { PhaseSection } from "./PhaseSection";
import type { Suggestion } from "@/types";

export const SuggestionsContext = createContext<Suggestion[]>([]);
export function useSuggestions(): Suggestion[] {
  return useContext(SuggestionsContext);
}

export function Canvas() {
  const { data: doc } = useDocument();
  const sim = doc?.simulation;
  const validate = useValidate();
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);

  useEffect(() => {
    if (!doc) return;
    validate.mutate(undefined, { onSuccess: (report) => setSuggestions(report.suggestions) });
    // Re-validate whenever the document identity changes: on load and after every mutation
    // (setDocument writes a new object into the one ["document"] cache entry).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc]);

  if (!sim) return null;

  return (
    <SuggestionsContext.Provider value={suggestions}>
      <div className="flex flex-col h-full">
        <SimHeader sim={sim} />
        <div className="flex-1 overflow-auto p-3">
          {sim.phases.length === 0 ? (
            <div className="mt-8 text-center text-sm text-ink-muted">Discover or drop files to start</div>
          ) : (
            sim.phases.map((phase) => <PhaseSection key={phase.id} phase={phase} topologies={sim.topologies} />)
          )}
        </div>
      </div>
    </SuggestionsContext.Provider>
  );
}
