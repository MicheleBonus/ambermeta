import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FileLabel } from "./FileLabel";

describe("FileLabel", () => {
  it("shows folder qualifier + basename with extension and a full-path tooltip", () => {
    render(<FileLabel path="/work/equil/01_min.mdin" base="/work" />);
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
    expect(screen.getByText("equil/")).toBeInTheDocument();
    expect(screen.getByTitle("/work/equil/01_min.mdin")).toBeInTheDocument();
  });

  it("keeps the extension so same-stem files stay distinguishable", () => {
    const { unmount } = render(
      <FileLabel path="/work/cryst/CH3L1_HUMAN_6NAG.crd" base="/work" />
    );
    expect(screen.getByText("CH3L1_HUMAN_6NAG.crd")).toBeInTheDocument();
    unmount();
    render(<FileLabel path="/work/cryst/CH3L1_HUMAN_6NAG.top" base="/work" />);
    expect(screen.getByText("CH3L1_HUMAN_6NAG.top")).toBeInTheDocument();
  });

  it("qualifies identical basenames with their folder", () => {
    render(
      <>
        <FileLabel path="/work/equil/min.mdin" base="/work" />
        <FileLabel path="/work/prod/min.mdin" base="/work" />
      </>
    );
    expect(screen.getByText("equil/")).toBeInTheDocument();
    expect(screen.getByText("prod/")).toBeInTheDocument();
    expect(screen.getAllByText("min.mdin")).toHaveLength(2);
  });

  it("renders windows paths with a normalised folder qualifier", () => {
    render(<FileLabel path={"C:\\work\\cryst\\CH3L1_HUMAN_6NAG.pdb"} base={"C:\\work"} />);
    expect(screen.getByText("cryst/")).toBeInTheDocument();
    expect(screen.getByText("CH3L1_HUMAN_6NAG.pdb")).toBeInTheDocument();
    expect(screen.getByTitle("C:\\work\\cryst\\CH3L1_HUMAN_6NAG.pdb")).toBeInTheDocument();
  });

  it("omits the folder qualifier for a file at the base root", () => {
    render(<FileLabel path="/work/wt_hmr.prmtop" base="/work" />);
    expect(screen.getByText("wt_hmr.prmtop")).toBeInTheDocument();
    expect(screen.queryByText("/")).not.toBeInTheDocument();
  });

  it("shows the full folder chain for a path outside the base", () => {
    render(<FileLabel path="/elsewhere/runs/run.mdout" base="/work" />);
    expect(screen.getByText("/elsewhere/runs/")).toBeInTheDocument();
    expect(screen.getByText("run.mdout")).toBeInTheDocument();
  });

  it("renders a dash for a null path", () => {
    render(<FileLabel path={null} base="/work" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("falls back to the raw path when there is no base", () => {
    render(<FileLabel path="/work/equil/01_min.mdin" base={null} />);
    expect(screen.getByText("/work/equil/")).toBeInTheDocument();
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
  });

  it("gives the folder away first, and still ellipsises rather than hard-clipping the name", () => {
    const { container } = render(<FileLabel path="/work/a/very/deep/tree/01_min.mdin" base="/work" />);
    const folder = screen.getByText("a/very/deep/tree/");
    const name = screen.getByText("01_min.mdin");
    // The folder is weighted to absorb the shrinking, so it disappears before the name does.
    expect(folder).toHaveClass("truncate");
    expect(folder.className).toMatch(/shrink-\[100\]/);
    // …but the name can shrink too. A shrink-0 name would make the label's min-content width the
    // full basename width, so a narrow parent would clip the extension off with no ellipsis.
    expect(name).toHaveClass("truncate");
    expect(name.className).not.toMatch(/shrink-0/);
    // And the label can never grow past the box it sits in.
    expect(container.firstElementChild?.className).toMatch(/max-w-full/);
  });

  it("keeps a basename far wider than its parent inside the parent", () => {
    const { container } = render(
      <div style={{ width: 60 }}>
        <FileLabel path="/work/equil/heat_nvt_100ps_restart.mdout" base="/work" />
      </div>,
    );
    // jsdom has no layout, so this pins the mechanism rather than the pixels: every part of the
    // label is allowed to shrink, and the whole label is capped at the parent's width.
    const label = container.querySelector("[title]");
    expect(label?.className).toMatch(/max-w-full/);
    expect(screen.getByText("heat_nvt_100ps_restart.mdout")).toHaveClass("truncate");
  });
});
