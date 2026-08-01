import { useEffect, useState, useSyncExternalStore } from "react";
import type { MarketRow } from "../api";
import { parseVolume } from "../lib/groupMarkets";
import { marketStore } from "../store/marketStore";

function sumGroupVolume(tickers: readonly string[]): number {
  let total = 0;
  for (const ticker of tickers) {
    const row = marketStore.getRow(ticker);
    if (row) total += parseVolume(row.volume);
  }
  return total;
}

/** Live sum of dollar volume across all strikes in a series/event (not gated on current liquidity). */
export function useLiveGroupVolume(tickers: readonly string[]): number {
  const tickersKey = tickers.join("\0");
  return useSyncExternalStore(
    (listener) => {
      if (!tickersKey) return () => {};
      const parts = tickersKey.split("\0");
      const unsubs = parts.map((ticker) => marketStore.subscribe(ticker, listener));
      return () => {
        for (const unsub of unsubs) unsub();
      };
    },
    () => sumGroupVolume(tickersKey.split("\0")),
    () => sumGroupVolume(tickersKey.split("\0")),
  );
}

export function useMarketStoreRows(): MarketRow[] {
  return useSyncExternalStore(
    (listener) => marketStore.subscribeAll(listener),
    () => marketStore.getSnapshot(),
    () => marketStore.getSnapshot(),
  );
}

/** Fresh rows for filters/sorting; quote fields update on interval, not every tick. */
export function useThrottledMarketRows(intervalMs: number): MarketRow[] {
  const listVersion = useSyncExternalStore(
    (listener) => marketStore.subscribeAll(listener),
    () => marketStore.getListVersion(),
    () => marketStore.getListVersion(),
  );
  const [rows, setRows] = useState<MarketRow[]>(() => marketStore.getSnapshot());

  useEffect(() => {
    setRows(marketStore.getFreshRows());
    const id = window.setInterval(() => setRows(marketStore.getFreshRows()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs, listVersion]);

  return rows;
}

export function useMarketRow(ticker: string): MarketRow | undefined {
  return useSyncExternalStore(
    (listener) => marketStore.subscribe(ticker, listener),
    () => marketStore.getRow(ticker),
    () => marketStore.getRow(ticker),
  );
}

export function useMarketStoreConnected(): boolean {
  return useSyncExternalStore(
    (listener) => marketStore.subscribeAll(listener),
    () => marketStore.isConnected(),
    () => marketStore.isConnected(),
  );
}
