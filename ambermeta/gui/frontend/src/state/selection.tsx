import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

interface SelectionCtx {
  selectedId: string | null;
  selectedIds: string[];
  select: (id: string, opts?: { additive?: boolean }) => void;
  clear: () => void;
  selectedFile: string | null;
  selectFile: (path: string | null) => void;
}
const Ctx = createContext<SelectionCtx | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [selectedIds, setIds] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const select = useCallback((id: string, opts?: { additive?: boolean }) => {
    setIds((prev) =>
      opts?.additive
        ? prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
        : [id]
    );
  }, []);
  const clear = useCallback(() => setIds([]), []);
  const value: SelectionCtx = {
    selectedId: selectedIds.length ? selectedIds[selectedIds.length - 1] : null,
    selectedIds, select, clear,
    selectedFile, selectFile: setSelectedFile,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSelection(): SelectionCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSelection must be used within SelectionProvider");
  return v;
}
