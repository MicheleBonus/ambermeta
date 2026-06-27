import { describe, it, expect, beforeEach } from "vitest";
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
