import { it, expect, vi } from "vitest";
import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider, useSelection } from "@/state/selection";
import { SuggestionsContext, SuggestionDismissalProvider } from "./suggestionsContext";
import { SuggestionsTray } from "./SuggestionsTray";
import type { Suggestion } from "@/types";

const missingRun: Suggestion = {
  id: "sug_1",
  kind: "missing_run",
  severity: "needs_you",
  title: "prod sequence is missing member(s) 2",
  evidence: "present members of 'prod' skip index(es) 2",
  actions: ["Mark as expected gap", "Locate file", "Ignore"],
  base: "prod",
  missing: [2],
};
const runCheck: Suggestion = {
  id: "sug_r_2",
  kind: "step_check",
  severity: "needs_you",
  title: "Run check",
  evidence: "prod_0001: Time step of 4 fs, but the topology has standard hydrogen masses",
  actions: ["Investigate"],
  step_id: "st_0001",
};
const roleGuess: Suggestion = {
  id: "sug_3",
  kind: "role_guess",
  severity: "applied",
  title: "Phase roles inferred from file content/names",
  evidence: "Production->production",
  actions: ["Undo"],
};
const startingStructure: Suggestion = {
  id: "sug_1",
  kind: "starting_structure",
  severity: "applied",
  title: "prod_0000.rst set as the starting structure",
  evidence: "single-frame coordinates; feeds the first run",
  actions: ["Undo"],
};

function SelectionProbe() {
  const { sel } = useSelection();
  return <div data-testid="selection">{`${sel.kind}:${sel.id}`}</div>;
}

/** The tray as the app mounts it: inside the selection and dismissal providers, with a
 *  switch that takes it off screen the way selecting a step does. */
function Harness({ list }: { list: Suggestion[] }) {
  const [shown, setShown] = useState(true);
  return (
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <SuggestionDismissalProvider>
          <SuggestionsContext.Provider value={list}>
            <button onClick={() => setShown((v) => !v)}>toggle tray</button>
            {shown && <SuggestionsTray />}
            <SelectionProbe />
          </SuggestionsContext.Provider>
        </SuggestionDismissalProvider>
      </SelectionProvider>
    </QueryClientProvider>
  );
}

function setup(list: Suggestion[]) {
  queryClient.clear();
  return render(<Harness list={list} />);
}

it("splits suggestions into Needs you / Applied groups, showing their evidence", () => {
  setup([missingRun, roleGuess]);

  expect(screen.getByText(/needs you/i)).toBeInTheDocument();
  expect(screen.getByText(/applied/i)).toBeInTheDocument();
  expect(screen.getByText("present members of 'prod' skip index(es) 2")).toBeInTheDocument();
  expect(screen.getByText("Production->production")).toBeInTheDocument();
});

it("a finding about one step offers to show that step, and nothing it cannot do", async () => {
  // Accept, Adjust and Ignore all only hid the card. "Accept" on a physics finding read
  // as resolving it, and `validate --strict` still failed on it.
  setup([runCheck]);
  const card = screen.getByTestId("suggestion-sug_r_2");

  await userEvent.click(within(card).getByRole("button", { name: "Show step" }));

  expect(screen.getByTestId("selection")).toHaveTextContent("step:st_0001");
  expect(within(card).getAllByRole("button").map((b) => b.textContent))
    .toEqual(["Show step", "Acknowledge…", "Dismiss"]);
});

it("no card can reverse an edit through the history undo", async () => {
  // An applied card describes the document as it stands, so its Undo -- the global undo --
  // reversed whatever edit came last: a rename made after Discover, not the inference.
  const undo = vi.fn(() => HttpResponse.json({}));
  server.use(http.post("/api/undo", undo));
  setup([missingRun, runCheck, roleGuess, startingStructure]);

  // Dismiss last: it takes the card off screen, and with it every button not yet pressed.
  for (const card of screen.getAllByTestId(/^suggestion-/)) {
    const buttons = within(card).queryAllByRole("button");
    const ordered = [...buttons.filter((b) => b.textContent !== "Dismiss"),
                     ...buttons.filter((b) => b.textContent === "Dismiss")];
    for (const button of ordered) {
      if (button.isConnected) await userEvent.click(button);
    }
  }

  expect(undo).not.toHaveBeenCalled();
});

it("a dismissal stays with its card when the list shifts", async () => {
  // Ids are positional: after an edit the new missing-run card arrived as sug_1, the id
  // the dismissed starting-structure card had held, and was hidden in its place.
  const view = setup([startingStructure, roleGuess]);
  await userEvent.click(
    within(screen.getByTestId("suggestion-sug_1")).getByRole("button", { name: "Dismiss" }));

  view.rerender(<Harness list={[missingRun, { ...startingStructure, id: "sug_2" }]} />);

  expect(screen.getByText("prod sequence is missing member(s) 2")).toBeInTheDocument();
  expect(screen.queryByText("prod_0000.rst set as the starting structure")).not.toBeInTheDocument();
});

it("a dismissal survives the tray leaving the screen", async () => {
  // Selecting a step replaces the tray with the step editor; the dismissed set lived in
  // the tray and went with it, so every dismissed card came back.
  setup([runCheck, roleGuess]);
  await userEvent.click(
    within(screen.getByTestId("suggestion-sug_r_2")).getByRole("button", { name: "Dismiss" }));

  await userEvent.click(screen.getByRole("button", { name: "toggle tray" }));
  await userEvent.click(screen.getByRole("button", { name: "toggle tray" }));

  expect(screen.queryByText("Run check")).not.toBeInTheDocument();
  expect(screen.getByText("Phase roles inferred from file content/names")).toBeInTheDocument();
});

it("a finding whose content changed is shown again", async () => {
  // Dismissing hides that finding, not every later one of the same kind and position.
  const view = setup([missingRun]);
  await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(screen.queryByText("prod sequence is missing member(s) 2")).not.toBeInTheDocument();

  const worse = { ...missingRun, title: "prod sequence is missing member(s) 2, 3",
    evidence: "present members of 'prod' skip index(es) 2, 3", missing: [2, 3] };
  view.rerender(<Harness list={[worse]} />);

  expect(screen.getByText("prod sequence is missing member(s) 2, 3")).toBeInTheDocument();
});

// --- settling a finding --------------------------------------------------------------
// Dismiss recorded nothing, so the finding came back on the next Validate, in --strict
// and in the methods summary. An acknowledgement is kept in the manifest with a note.

const NOTE = "prod_0002 was not deposited.";
const textOf = (s: Suggestion) => `${s.title}: ${s.evidence}`;

it("a finding can be acknowledged with a note, and the note is what is sent", async () => {
  let body: unknown;
  server.use(http.post("/api/acknowledged", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json(emptyDocument);
  }));
  setup([missingRun]);
  const card = screen.getByTestId("suggestion-sug_1");

  await userEvent.click(within(card).getByRole("button", { name: "Acknowledge…" }));
  const save = within(card).getByRole("button", { name: "Save note" });
  expect(save).toBeDisabled();   // no note, no acknowledgement
  await userEvent.type(within(card).getByLabelText("Why this finding stands"), NOTE);
  await userEvent.click(save);

  // The finding is named by the line `validate` prints, which is how the CLI matches it.
  await waitFor(() => expect(body).toEqual({ finding: textOf(missingRun), note: NOTE }));
});

it("an acknowledged finding is listed apart with its note, and can be reopened", async () => {
  let body: unknown;
  server.use(http.post("/api/acknowledged/remove", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json(emptyDocument);
  }));
  setup([{ ...missingRun, acknowledged: NOTE }]);

  expect(screen.getByText(/^acknowledged$/i)).toBeInTheDocument();
  expect(screen.queryByText(/needs you/i)).not.toBeInTheDocument();
  expect(screen.getByText(NOTE)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Reopen" }));
  await waitFor(() => expect(body).toEqual({ finding: textOf(missingRun) }));
});

it("an applied card offers no acknowledgement", () => {
  setup([roleGuess]);
  expect(screen.queryByRole("button", { name: "Acknowledge…" })).not.toBeInTheDocument();
});
