import { createContext, useContext } from "react";
import type { Suggestion } from "@/types";

export const SuggestionsContext = createContext<Suggestion[]>([]);

export function useSuggestions(): Suggestion[] {
  return useContext(SuggestionsContext);
}
