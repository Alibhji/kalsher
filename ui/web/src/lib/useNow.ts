import { useSyncExternalStore } from "react";

const TICK_MS = 1000;

const listeners = new Set<() => void>();
let now = Date.now();
let timer = 0;

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (timer === 0) {
    timer = window.setInterval(() => {
      now = Date.now();
      for (const l of listeners) l();
    }, TICK_MS);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      window.clearInterval(timer);
      timer = 0;
    }
  };
}

/**
 * One shared clock for every countdown in the app. Components that only display
 * elapsed time subscribe here instead of taking `nowMs` as a prop, so a ticking
 * clock no longer invalidates memoised rows that carry live quotes.
 */
export function useNowMs(): number {
  return useSyncExternalStore(subscribe, () => now, () => now);
}
