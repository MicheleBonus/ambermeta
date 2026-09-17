import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./server";

// Node 22+ ships its own global `localStorage` (Web Storage), and without
// `--localstorage-file` it is an object with none of the methods on it. In vitest's jsdom
// environment `window === globalThis`, so it wins over the one jsdom would have installed
// and `window.localStorage` is the same broken object -- there is nothing working left to
// point at. Anything reading a persisted value then throws "localStorage.getItem is not a
// function"; `usePersistentSize` is `App`'s first line of state, so on Node 25 that was 34
// failures across 4 files with no source change involved, and every App-level test was
// silently not running.
//
// CI pins Node 20, which has no such global, so the guard below is false there and this
// is inert: it repairs local runs on a newer Node without changing what CI executes.
if (typeof (globalThis as any).localStorage?.getItem !== "function") {
  const entries = new Map<string, string>();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: {
      getItem: (key: string) => (entries.has(key) ? entries.get(key)! : null),
      setItem: (key: string, value: unknown) => { entries.set(key, String(value)); },
      removeItem: (key: string) => { entries.delete(key); },
      clear: () => { entries.clear(); },
      key: (index: number) => Array.from(entries.keys())[index] ?? null,
      get length() { return entries.size; },
    },
  });
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
