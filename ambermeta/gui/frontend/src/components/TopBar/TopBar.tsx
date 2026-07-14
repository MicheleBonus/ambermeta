import { Button, Undo2, Redo2 } from "@/components/common";
import { useDocument, useUndo, useRedo } from "@/api/hooks";

interface Props {
  onOpen: () => void;
  onSave: () => void;
  onDiscover: () => void;
  onExport: () => void;
  onValidate: () => void;
}

export function TopBar({ onOpen, onSave, onDiscover, onExport, onValidate }: Props) {
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
      <Button onClick={onValidate}>Validate</Button>
      <Button onClick={onExport}>Export</Button>
      <Button aria-label="Undo" disabled={!doc?.can_undo} onClick={() => undo.mutate()}>
        <Undo2 size={16} />
      </Button>
      <Button aria-label="Redo" disabled={!doc?.can_redo} onClick={() => redo.mutate()}>
        <Redo2 size={16} />
      </Button>
    </header>
  );
}
