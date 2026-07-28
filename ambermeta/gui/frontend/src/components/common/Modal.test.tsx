import { useState } from "react";
import { it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Modal } from "./Modal";

/**
 * A dialog that owns a controlled field and — like every real caller — builds its own
 * `onClose` inline, so the prop is a new function on every render.
 */
function TypingDialog({ onClose = vi.fn() }: { onClose?: () => void }) {
  const [value, setValue] = useState("");
  const close = () => onClose();          // fresh identity each render, as PlanModal does
  return (
    <Modal open title="Write plan outputs" onClose={close}>
      <input aria-label="Path" value={value} onChange={(e) => setValue(e.target.value)} />
    </Modal>
  );
}

it("keeps focus in a field while it is being typed into", async () => {
  // The effect that focuses the dialog listed `onClose` in its deps. A controlled field
  // re-renders its parent on every keystroke, which gave `onClose` a new identity, which
  // re-ran the effect, which pulled focus back to the dialog — so only the first
  // character of a typed filename ever landed.
  render(<TypingDialog />);
  const path = screen.getByLabelText("Path");

  await userEvent.type(path, "runs/protocol.yaml");

  expect((path as HTMLInputElement).value).toBe("runs/protocol.yaml");
  expect(document.activeElement).toBe(path);
});

it("still focuses the dialog when it opens", async () => {
  render(<TypingDialog />);
  expect(document.activeElement).toBe(screen.getByRole("dialog"));
});

it("still closes on Escape, with the latest handler rather than a stale one", async () => {
  const first = vi.fn();
  const second = vi.fn();
  function Swapper() {
    const [handler, setHandler] = useState(() => first);
    return (
      <>
        <button type="button" onClick={() => setHandler(() => second)}>swap</button>
        <Modal open title="d" onClose={() => handler()}>
          <input aria-label="Path" />
        </Modal>
      </>
    );
  }
  render(<Swapper />);

  await userEvent.keyboard("{Escape}");
  expect(first).toHaveBeenCalledOnce();

  // The handler now lives in a ref; it must be read at keypress time, not captured once.
  await userEvent.click(screen.getByRole("button", { name: "swap" }));
  await userEvent.keyboard("{Escape}");
  expect(second).toHaveBeenCalledOnce();
  expect(first).toHaveBeenCalledOnce();
});
