import { useSyncExternalStore } from "react";
import { tradingStore, type TradingSnapshot } from "./tradingStore";

const subscribe = (cb: () => void) => tradingStore.subscribe(cb);

export function useTradingStore() {
  return useSyncExternalStore(subscribe, () => tradingStore.getSnapshot(), () => tradingStore.getSnapshot());
}

/**
 * Subscribe to one field instead of the whole snapshot. `getSnapshot` rebuilds the
 * snapshot object on every emit, so a component reading only `focusTicker` would
 * otherwise re-render whenever an unrelated fill or order arrives.
 */
export function useTradingField<K extends keyof TradingSnapshot>(key: K): TradingSnapshot[K] {
  const read = () => tradingStore.getSnapshot()[key];
  return useSyncExternalStore(subscribe, read, read);
}

export function useTradingFocus(): { focusTicker: string | null; focusSeq: number } {
  return {
    focusTicker: useTradingField("focusTicker"),
    focusSeq: useTradingField("focusSeq"),
  };
}

export function useRoundTrips(ticker: string) {
  const read = () => tradingStore.getRoundTrips(ticker);
  return useSyncExternalStore(subscribe, read, read);
}
