import { useRef, useState, type KeyboardEvent } from "react";

/**
 * Double-click-to-rename plumbing, shared by the step and phase headers on the
 * canvas: a draft string while editing (`null` when not), committed on Enter or
 * blur and dropped on Escape.
 *
 * The ref guard makes finishing idempotent, so the blur that follows an Enter —
 * and the one fired when the input unmounts after an Escape — cannot commit a
 * second time or resurrect a discarded draft.
 */
export function useInlineRename(current: string, commit: (name: string) => void) {
  const [draft, setDraft] = useState<string | null>(null);
  const active = useRef(false);

  const finish = (save: boolean) => {
    if (!active.current) return;
    active.current = false;
    const next = (draft ?? "").trim();
    setDraft(null);
    if (save && next && next !== current) commit(next);
  };

  return {
    editing: draft !== null,
    value: draft ?? "",
    start: () => {
      active.current = true;
      setDraft(current);
    },
    change: (v: string) => setDraft(v),
    keyDown: (e: KeyboardEvent) => {
      if (e.key === "Enter") finish(true);
      else if (e.key === "Escape") finish(false);
    },
    blur: () => finish(true),
  };
}
