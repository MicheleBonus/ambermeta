import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  pushToast, dismissToast, getToasts, subscribeToasts, _resetToasts,
} from "./toast";

beforeEach(() => { _resetToasts(); });

describe("toast store", () => {
  it("pushToast adds a toast", () => {
    pushToast("hello", "info");
    expect(getToasts()).toHaveLength(1);
    expect(getToasts()[0].message).toBe("hello");
    expect(getToasts()[0].tone).toBe("info");
  });

  it("dismissToast removes the toast by id", () => {
    pushToast("a", "error");
    pushToast("b", "warning");
    const id = getToasts()[0].id;
    dismissToast(id);
    expect(getToasts()).toHaveLength(1);
    expect(getToasts()[0].message).toBe("b");
  });

  it("subscribeToasts notifies on push and dismiss", () => {
    let calls = 0;
    const unsub = subscribeToasts(() => { calls++; });
    pushToast("x");
    expect(calls).toBe(1);
    dismissToast(getToasts()[0].id);
    expect(calls).toBe(2);
    unsub();
    pushToast("y");
    expect(calls).toBe(2); // unsubscribed
  });

  it("_resetToasts clears all toasts and notifies", () => {
    let calls = 0;
    subscribeToasts(() => { calls++; });
    pushToast("a"); pushToast("b");
    _resetToasts();
    expect(getToasts()).toHaveLength(0);
    expect(calls).toBe(3); // 2 pushes + 1 reset
  });

  it("defaults tone to info", () => {
    pushToast("no tone");
    expect(getToasts()[0].tone).toBe("info");
  });
});

// "Saved to ..." toasts stayed until dismissed, so a working session stacked them over the
// tray. Information goes after a while; an error or warning stays until it is read.
describe("toast lifetime", () => {
  afterEach(() => { vi.useRealTimers(); });

  it("an information toast goes by itself", () => {
    vi.useFakeTimers();
    pushToast("Saved to manifest.yaml", "info");
    vi.advanceTimersByTime(10_000);
    expect(getToasts()).toHaveLength(0);
  });

  it("an error or a warning stays until it is dismissed", () => {
    vi.useFakeTimers();
    pushToast("Could not read manifest", "error");
    pushToast("Saved, but the document changed", "warning");
    vi.advanceTimersByTime(60_000);
    expect(getToasts().map((t) => t.tone)).toEqual(["error", "warning"]);
  });

  it("a toast offering an action stays, so the offer can be taken", () => {
    vi.useFakeTimers();
    pushToast("Deleted step", "info", { label: "Undo", run: () => {} });
    vi.advanceTimersByTime(60_000);
    expect(getToasts()).toHaveLength(1);
  });
});
