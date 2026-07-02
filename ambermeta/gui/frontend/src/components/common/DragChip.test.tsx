import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DragChip } from "./DragChip";

describe("DragChip", () => {
  it("shows the dragged file's basename", () => {
    render(<DragChip activeId="file:/work/equil/01_min.mdin" base="/work" />);
    expect(screen.getByText("01_min.mdin")).toBeInTheDocument();
  });
  it("renders nothing when not dragging a file", () => {
    const { container } = render(<DragChip activeId={null} base="/work" />);
    expect(container).toBeEmptyDOMElement();
  });
});
