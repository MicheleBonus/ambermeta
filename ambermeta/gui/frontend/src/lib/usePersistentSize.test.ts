import { describe, it, expect, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { usePersistentSize } from "./usePersistentSize";

describe("usePersistentSize", () => {
  beforeEach(() => localStorage.clear());
  it("clamps a stale stored value into [min,max] on load", () => {
    localStorage.setItem("files-w", "5000");
    const { result } = renderHook(() => usePersistentSize("files-w", 280, { min: 200, max: 480 }));
    expect(result.current[0]).toBe(480);
  });
  it("keeps an in-range stored value", () => {
    localStorage.setItem("files-w", "300");
    const { result } = renderHook(() => usePersistentSize("files-w", 280, { min: 200, max: 480 }));
    expect(result.current[0]).toBe(300);
  });
});
