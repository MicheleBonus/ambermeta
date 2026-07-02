import { describe, it, expect } from "vitest";
import { formatPs, formatCount, roleLabel, fileLabel, relativizePath } from "./format";

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
  it("labels roles in Title Case, empty as Unknown", () => {
    expect(roleLabel("")).toBe("Unknown");
    expect(roleLabel("production")).toBe("Production");
    expect(roleLabel("equilibration")).toBe("Equilibration");
    expect(roleLabel("weird")).toBe("weird"); // unknown role passes through
  });
});

describe("relativizePath", () => {
  it("strips a posix base and separator", () => {
    expect(relativizePath("/work/equil/01_min.mdin", "/work")).toBe("equil/01_min.mdin");
  });
  it("strips a windows base and separator", () => {
    expect(relativizePath("C:\\work\\cryst\\a.pdb", "C:\\work")).toBe("cryst\\a.pdb");
  });
  it("returns the path unchanged when not under base", () => {
    expect(relativizePath("/other/x.mdin", "/work")).toBe("/other/x.mdin");
    expect(relativizePath("/work/x.mdin", null)).toBe("/work/x.mdin");
  });
});

describe("fileLabel", () => {
  it("keeps the extension and derives a base-relative folder", () => {
    expect(fileLabel("/work/equil/01_min.mdin", "/work"))
      .toEqual({ folder: "equil", name: "01_min.mdin", full: "/work/equil/01_min.mdin" });
  });
  it("empty folder at the base root", () => {
    expect(fileLabel("/work/system.prmtop", "/work"))
      .toEqual({ folder: "", name: "system.prmtop", full: "/work/system.prmtop" });
  });
  it("handles windows separators", () => {
    expect(fileLabel("C:\\work\\cryst\\m.crd", "C:\\work"))
      .toEqual({ folder: "cryst", name: "m.crd", full: "C:\\work\\cryst\\m.crd" });
  });
});
