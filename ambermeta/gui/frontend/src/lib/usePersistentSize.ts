import { useCallback, useState } from "react";

export function usePersistentSize(
  key: string, initial: number, opts?: { min?: number; max?: number }
): [number, (n: number) => void] {
  const clamp = (n: number) =>
    Math.min(opts?.max ?? Infinity, Math.max(opts?.min ?? -Infinity, n));
  const [size, setSize] = useState<number>(() => {
    const raw = localStorage.getItem(key);
    const n = raw ? Number(raw) : NaN;
    return clamp(Number.isFinite(n) ? n : initial);
  });
  const set = useCallback((n: number) => {
    const c = clamp(n);
    setSize(c);
    localStorage.setItem(key, String(c));
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return [size, set];
}
