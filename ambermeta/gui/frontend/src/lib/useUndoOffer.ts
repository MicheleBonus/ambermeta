import { useUndo } from "@/api/hooks";
import { pushToast } from "@/lib/toast";

/**
 * Report what just happened and offer to take it back.
 *
 * This is the alternative to asking "are you sure?" before every removal. A confirm
 * dialog costs a click on every correct action to protect against the rare wrong one,
 * and it protects nothing at all once the user has learned to dismiss it. An Undo offer
 * charges nothing for being right and is a single click when wrong.
 *
 * The offer is retired by the next document mutation (see `docMutation`), so it can only
 * ever reverse the edit it was raised for.
 */
export function useUndoOffer(): (message: string) => void {
  const undo = useUndo();
  return (message: string) =>
    pushToast(message, "info", { label: "Undo", run: () => undo.mutate() });
}
