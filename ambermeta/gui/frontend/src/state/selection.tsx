import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
export type SelKind = "file" | "step" | "phase" | "sim" | null;
export interface Selection { kind: SelKind; id: string | null; }
interface Ctx { sel: Selection; select: (kind: SelKind, id: string | null) => void; }
const SelectionCtx = createContext<Ctx | null>(null);
export function SelectionProvider({ children }: { children: ReactNode }) {
  const [sel, setSel] = useState<Selection>({ kind: null, id: null });
  const value = useMemo<Ctx>(() => ({ sel, select: (kind, id) => setSel({ kind, id }) }), [sel]);
  return <SelectionCtx.Provider value={value}>{children}</SelectionCtx.Provider>;
}
export function useSelection(): Ctx {
  const c = useContext(SelectionCtx);
  if (!c) throw new Error("useSelection outside SelectionProvider");
  return c;
}
