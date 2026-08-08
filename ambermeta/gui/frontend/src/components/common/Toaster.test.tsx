import { afterEach, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { pushToast, _resetToasts } from "@/lib/toast";
import { Toaster } from "./Toaster";

afterEach(() => {
  _resetToasts();
});

// F1 follow-up: `totals_delta` (protocol.py) builds a terminal-formatted block — embedded
// "\n"s separating a steps/time_ps/note/queued line each — and `usePlan`'s `onSuccess`
// raises exactly that string as a toast (hooks.ts:91). Before this fix, `Toaster` rendered
// its message in a plain `<span>` with the browser default `white-space: normal`, which
// collapses every "\n" into a space: a four-line block a user reads perfectly well in the
// CLI arrived here as one run-on sentence, in a box only 24rem (`max-w-sm`) wide.
it("keeps a multi-line toast's line breaks, instead of collapsing it into one sentence", () => {
  const delta = "totals changed since the last summary.json (/work/summary.json):\n"
    + "  steps     20000000.000 -> 17500000.000\n"
    + "  time_ps   40000.000 -> 35000.000\n"
    + "  note      totals count what each run's mdout shows it RAN, not what its mdin declared";
  pushToast(delta, "warning");
  render(<Toaster />);

  // jsdom does not lay out CSS, so nothing here can assert the actual visual line
  // wrapping — asserting the utility class is what proves this test would fail without
  // the fix (the pre-fix `<span>` carried no `whitespace-*` class at all).
  const rendered = screen.getByText((_, el) => el?.textContent === delta);
  expect(rendered).toHaveClass("whitespace-pre-line");
  expect(rendered.tagName).toBe("SPAN");
});

it("still renders an ordinary single-line toast exactly as before", () => {
  const message = "5 steps have no lineage. Define replicas… to tag them.";
  pushToast(message, "info");
  render(<Toaster />);

  // `whitespace-pre-line` only changes how an EXISTING "\n" is honoured; a message with
  // none of them (every toast this component rendered before totals_delta existed) reads
  // and wraps exactly as `white-space: normal` already had it.
  const rendered = screen.getByText(message);
  expect(rendered).toHaveClass("whitespace-pre-line");
  expect(rendered.textContent).toBe(message);
});
