import { useEffect } from "react";

/** True while the keystroke belongs to whatever the user is typing into. */
function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  if (el.isContentEditable) return true;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

/**
 * Ctrl/Cmd+Z and Ctrl+Shift+Z / Ctrl+Y, document-wide.
 *
 * Undo existed only as a 16px icon in the top bar, which is not where anyone looks after a
 * mistake. Typing is left alone so the browser's own text undo keeps working inside a
 * rename box, and `enabled` lets a modal opt the whole document out.
 */
export function useUndoShortcuts({
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  enabled = true,
}: {
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  enabled?: boolean;
}): void {
  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      if (isTyping(e.target)) return;
      const key = e.key.toLowerCase();
      const redo = key === "y" || (key === "z" && e.shiftKey);
      if (key !== "z" && key !== "y") return;
      // Claimed either way: letting an unavailable undo fall through to the browser is
      // how a stray Ctrl+Z ends up undoing text in some unrelated field.
      e.preventDefault();
      if (redo) {
        if (canRedo) onRedo();
      } else if (canUndo) {
        onUndo();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onUndo, onRedo, canUndo, canRedo, enabled]);
}
