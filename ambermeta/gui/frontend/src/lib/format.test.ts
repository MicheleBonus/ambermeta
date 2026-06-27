import { describe, it, expect } from "vitest";
import { formatPs, formatCount, roleLabel } from "./format";

describe("format helpers", () => {
  it("formats ps and null", () => {
    expect(formatPs(2)).toBe("2 ps");
    expect(formatPs(0.5)).toBe("0.5 ps");
    expect(formatPs(null)).toBe("—");
  });
  it("formats counts with thousands separators", () => {
    expect(formatCount(32000)).toBe("32,000");
    expect(formatCount(null)).toBe("—");
  });
  it("labels empty role as Unknown", () => {
    expect(roleLabel("")).toBe("Unknown");
    expect(roleLabel("production")).toBe("production");
  });
});
