import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { FileIcon } from "./Icons";

describe("FileIcon", () => {
  it("defaults to a 16px glyph (not lucide's 24)", () => {
    const { container } = render(<FileIcon type="mdin" />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("16");
  });
  it("honors an explicit size", () => {
    const { container } = render(<FileIcon type="folder" size={20} />);
    expect(container.querySelector("svg")?.getAttribute("width")).toBe("20");
  });
});
