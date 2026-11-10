import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DiscoverModal } from "./DiscoverModal";

// A folder holding several systems (runs of different atom counts) is refused by the
// server, and the refusal tells the user to tick this box for a false alarm; so the box
// has to exist, start unticked, and reach the request.
describe("DiscoverModal", () => {
  it("asks for separate systems to be refused unless the box is ticked", () => {
    const onRun = vi.fn();
    render(<DiscoverModal open onClose={() => {}} onRun={onRun} />);
    fireEvent.click(screen.getByRole("button", { name: "Run discover" }));
    expect(onRun).toHaveBeenCalledWith(expect.objectContaining({ as_one_simulation: false }));
  });

  it("sends as_one_simulation when 'Treat everything here as one simulation' is ticked", () => {
    const onRun = vi.fn();
    render(<DiscoverModal open onClose={() => {}} onRun={onRun} />);
    fireEvent.click(screen.getByLabelText("Treat everything here as one simulation"));
    fireEvent.click(screen.getByRole("button", { name: "Run discover" }));
    expect(onRun).toHaveBeenCalledWith(expect.objectContaining({ as_one_simulation: true }));
  });
});
