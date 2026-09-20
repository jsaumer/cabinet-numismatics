// One request cache per page view, so widgets that want the same request make
// it once: five breakdowns with the same scope, or three widgets reading the
// settings. Cleared by "Refresh melt values" and after a layout is saved.

import { useEffect, useState } from "react";

const cache = new Map<string, Promise<unknown>>();
const listeners = new Set<() => void>();
let generation = 0;

/** The shared promise for `key`, starting the request the first time it is
 * asked for. A failure is not kept, so the next mount tries again. */
export function fetchOnce<T>(key: string, load: () => Promise<T>): Promise<T> {
  const hit = cache.get(key) as Promise<T> | undefined;
  if (hit) return hit;
  const pending = load();
  cache.set(key, pending);
  pending.catch(() => {
    if (cache.get(key) === pending) cache.delete(key);
  });
  return pending;
}

/** Throw the page's data away and refetch what is on screen. */
export function invalidateData() {
  cache.clear();
  generation += 1;
  for (const listener of [...listeners]) listener();
}

export interface Loaded<T> {
  data: T | null;
  error: string | null;
  /** The request finished, one way or the other. */
  settled: boolean;
}

/** Read `key` from the page cache. `enabled` is false until the widget is
 * near the viewport, so cards below the fold cost nothing until scrolled to. */
export function useData<T>(key: string, load: () => Promise<T>, enabled = true): Loaded<T> {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({
    data: null,
    error: null,
  });
  const [gen, setGen] = useState(generation);

  useEffect(() => {
    const listener = () => setGen(generation);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  // `load` is deliberately not a dependency: `key` identifies the request, and
  // every render builds a fresh closure. Old data stays on screen until the
  // new answer arrives, so a refresh doesn't blank the page.
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    fetchOnce(key, load)
      .then((data) => live && setState({ data, error: null }))
      .catch((e: Error) => live && setState({ data: null, error: e.message }));
    return () => {
      live = false;
    };
  }, [key, enabled, gen]);

  return { ...state, settled: state.data !== null || state.error !== null };
}
