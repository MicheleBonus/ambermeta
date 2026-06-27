import { useCallback, useState } from "react";

export function usePersistentSize(key: string, initial: number): [number, (n: number) => void] {
  const [size, setSize] = useState<number>(() => {
    const raw = localStorage.getItem(key);
    const n = raw ? Number(raw) : NaN;
    return Number.isFinite(n) ? n : initial;
  });
  const set = useCallback((n: number) => {
    setSize(n);
    localStorage.setItem(key, String(n));
  }, [key]);
  return [size, set];
}
