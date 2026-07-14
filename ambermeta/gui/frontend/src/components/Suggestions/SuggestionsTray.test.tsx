import { it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/api/queryClient";
import { SuggestionsContext } from "@/components/Canvas/Canvas";
import { SuggestionsTray } from "./SuggestionsTray";
import type { Suggestion } from "@/types";

const suggestions: Suggestion[] = [
  {
    id: "sug_1",
    kind: "missing_run",
    severity: "needs_you",
    title: "prod sequence is missing member(s) 2",
    evidence: "present members of 'prod' skip index(es) 2",
    actions: ["Mark as expected gap", "Locate file", "Ignore"],
    base: "prod",
    missing: [2],
  },
  {
    id: "sug_2",
    kind: "role_guess",
    severity: "applied",
    title: "Phase roles inferred from file content/names",
    evidence: "Production->production",
    actions: ["Undo"],
  },
];

function setup(list: Suggestion[]) {
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <SuggestionsContext.Provider value={list}>
        <SuggestionsTray />
      </SuggestionsContext.Provider>
    </QueryClientProvider>
  );
}

it("splits suggestions into Needs you / Applied groups, showing evidence and the missing-run affordances", () => {
  setup(suggestions);

  expect(screen.getByText(/needs you/i)).toBeInTheDocument();
  expect(screen.getByText(/applied/i)).toBeInTheDocument();

  expect(screen.getByText("present members of 'prod' skip index(es) 2")).toBeInTheDocument();
  expect(screen.getByText("Production->production")).toBeInTheDocument();

  const missingRunCard = screen.getByTestId("suggestion-sug_1");
  expect(within(missingRunCard).getByRole("button", { name: /accept/i })).toBeInTheDocument();
  expect(within(missingRunCard).getByRole("button", { name: /ignore/i })).toBeInTheDocument();

  const appliedCard = screen.getByTestId("suggestion-sug_2");
  expect(within(appliedCard).getByRole("button", { name: /undo/i })).toBeInTheDocument();
});
