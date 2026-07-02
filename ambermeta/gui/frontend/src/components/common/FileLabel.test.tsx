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
  it("renders a dash for a null path", () => {
    render(<FileLabel path={null} base="/work" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
