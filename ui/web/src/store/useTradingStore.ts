import { useSyncExternalStore } from "react";
import { tradingStore } from "./tradingStore";

export function useTradingStore() {
  return useSyncExternalStore(
    (cb) => tradingStore.subscribe(cb),
    () => tradingStore.getSnapshot(),
    () => tradingStore.getSnapshot(),
  );
}

export function useRoundTrips(ticker: string) {
  return useSyncExternalStore(
    (cb) => tradingStore.subscribe(cb),
    () => tradingStore.getRoundTrips(ticker),
    () => tradingStore.getRoundTrips(ticker),
  );
}
