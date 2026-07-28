import { describe, it, expect } from "vitest";
import { formatPs, formatCount, roleLabel, relativizePath, fileLabel, stemName } from "./format";

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

describe("relativizePath", () => {
  it("strips the base directory from a posix path", () => {
    expect(relativizePath("/work/cryst/CH3L1_HUMAN_6NAG.crd", "/work")).toBe(
      "cryst/CH3L1_HUMAN_6NAG.crd"
    );
  });
  it("ignores a trailing separator on the base", () => {
    expect(relativizePath("/work/equil/01_min.mdin", "/work/")).toBe("equil/01_min.mdin");
    expect(relativizePath("C:\\work\\equil\\01_min.mdin", "C:\\work\\")).toBe(
      "equil\\01_min.mdin"
    );
  });
  it("strips the base directory from a windows path", () => {
    expect(relativizePath("C:\\work\\cryst\\CH3L1_HUMAN_6NAG.top", "C:\\work")).toBe(
      "cryst\\CH3L1_HUMAN_6NAG.top"
    );
  });
  it("returns an empty string when the path is the base itself", () => {
    expect(relativizePath("/work", "/work")).toBe("");
    expect(relativizePath("/work", "/work/")).toBe("");
  });
  it("returns the path unchanged when it is not under the base", () => {
    expect(relativizePath("/elsewhere/run.mdout", "/work")).toBe("/elsewhere/run.mdout");
  });
  it("does not strip a base that is only a string prefix, not a path boundary", () => {
    expect(relativizePath("/workspace/run.mdout", "/work")).toBe("/workspace/run.mdout");
  });
  it("returns the path unchanged when there is no base", () => {
    expect(relativizePath("/work/equil/01_min.mdin", null)).toBe("/work/equil/01_min.mdin");
  });
});

describe("stemName", () => {
  it("takes the basename without its final extension", () => {
    expect(stemName("/work/equil/01_min.mdin")).toBe("01_min");
    expect(stemName("min.in")).toBe("min");
  });
  it("handles windows separators", () => {
    expect(stemName("C:\\work\\equil\\01_min.mdin")).toBe("01_min");
  });
  it("only strips the last extension", () => {
    expect(stemName("/work/prod_0001.mdcrd.nc")).toBe("prod_0001.mdcrd");
  });
  it("leaves an extensionless name alone", () => {
    expect(stemName("/work/README")).toBe("README");
  });
});

describe("fileLabel", () => {
  it("splits a base-relative path into folder and name, keeping the extension", () => {
    expect(fileLabel("/work/cryst/CH3L1_HUMAN_6NAG.crd", "/work")).toEqual({
      folder: "cryst",
      name: "CH3L1_HUMAN_6NAG.crd",
      full: "/work/cryst/CH3L1_HUMAN_6NAG.crd",
    });
  });
  it("distinguishes same-stem files by extension", () => {
    expect(fileLabel("/work/cryst/CH3L1_HUMAN_6NAG.top", "/work").name).toBe(
      "CH3L1_HUMAN_6NAG.top"
    );
    expect(fileLabel("/work/cryst/CH3L1_HUMAN_6NAG.pdb", "/work").name).toBe(
      "CH3L1_HUMAN_6NAG.pdb"
    );
  });
  it("distinguishes identical basenames by folder", () => {
    expect(fileLabel("/work/equil/min.mdin", "/work").folder).toBe("equil");
    expect(fileLabel("/work/prod/min.mdin", "/work").folder).toBe("prod");
  });
  it("normalises windows separators in the folder qualifier", () => {
    expect(fileLabel("C:\\work\\equil\\stage1\\01_min.mdin", "C:\\work")).toEqual({
      folder: "equil/stage1",
      name: "01_min.mdin",
      full: "C:\\work\\equil\\stage1\\01_min.mdin",
    });
  });
  it("reports an empty folder for a file sitting at the base root", () => {
    expect(fileLabel("/work/wt_hmr.prmtop", "/work")).toEqual({
      folder: "",
      name: "wt_hmr.prmtop",
      full: "/work/wt_hmr.prmtop",
    });
  });
  it("keeps the whole folder chain for a path outside the base", () => {
    expect(fileLabel("/elsewhere/runs/run.mdout", "/work")).toEqual({
      folder: "/elsewhere/runs",
      name: "run.mdout",
      full: "/elsewhere/runs/run.mdout",
    });
  });
  it("works without a base", () => {
    expect(fileLabel("/work/equil/01_min.mdin")).toEqual({
      folder: "/work/equil",
      name: "01_min.mdin",
      full: "/work/equil/01_min.mdin",
    });
  });
  it("always reports the original absolute path as full", () => {
    expect(fileLabel("/work/equil/01_min.mdin", "/work").full).toBe("/work/equil/01_min.mdin");
  });
});
