import { Button, Undo2, Redo2 } from "@/components/common";
import { useDocument, useUndo, useRedo } from "@/api/hooks";

interface Props {
  onOpen: () => void;
  onSave: () => void;
  onDiscover: () => void;
  onExport: () => void;
  onValidate: () => void;
  onPlan: () => void;
  onDefineReplicas: () => void;
}

export function TopBar({
  onOpen, onSave, onDiscover, onExport, onValidate, onPlan, onDefineReplicas,
}: Props) {
  const { data: doc } = useDocument();
  const undo = useUndo();
  const redo = useRedo();
  const dirty = !!doc?.dirty;
  return (
    <header data-testid="topbar" className="flex items-center gap-2 px-3 h-12 border-b border-hairline bg-surface">
      <span className="font-semibold mr-2 text-ink">AmberMeta</span>
      <Button onClick={onOpen}>Open</Button>
      <Button variant="primary" onClick={onSave}>Save</Button>
      {dirty && (
        <span data-testid="dirty-indicator" title="Unsaved changes"
          className="w-2 h-2 rounded-full bg-accent" />
      )}
      <span className="flex-1" />
      <Button onClick={onDiscover}>Discover</Button>
      {/* Lives here, in the top bar, and not tucked inside SimHeader the way the old
          "Infer lineages" link was -- discoverability, not capability, was the original
          complaint, and a muted control inside the simulation header is exactly what went
          unnoticed. Never gated on document state (see App.tsx's onDefineReplicas for why
          it still works on a tree the smart inference declines to tag): the old control's
          `disabled={sim.phases.every(...)}` guard does not carry over, because this is the
          only path back to a manual picker once that smart inference has refused. */}
      <Button onClick={onDefineReplicas}>Define replicas…</Button>
      <Button onClick={onValidate}>Validate</Button>
      {/* The step after the manifest: the summaries `ambermeta plan` writes. */}
      <Button onClick={onPlan} title="Write the manifest and plan summaries to disk">Plan</Button>
      <Button onClick={onExport}>Export</Button>
      {/* Icon-only, so the shortcut goes in the tooltip — otherwise the only clue that
          Ctrl+Z works at all is trying it. */}
      <Button aria-label="Undo" title="Undo (Ctrl+Z)" aria-keyshortcuts="Control+Z"
        disabled={!doc?.can_undo} onClick={() => undo.mutate()}>
        <Undo2 size={16} />
      </Button>
      <Button aria-label="Redo" title="Redo (Ctrl+Shift+Z)" aria-keyshortcuts="Control+Shift+Z"
        disabled={!doc?.can_redo} onClick={() => redo.mutate()}>
        <Redo2 size={16} />
      </Button>
    </header>
  );
}
