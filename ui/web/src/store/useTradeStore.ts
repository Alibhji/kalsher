import { useSyncExternalStore } from "react";
import type { LineData } from "lightweight-charts";
import { cumulativeFlowSeries, tradeStore } from "../store/tradeStore";

export function useTradeTape(ticker: string) {
  const tape = useSyncExternalStore(
    (listener) => tradeStore.subscribeTicker(ticker, listener),
    () => tradeStore.getTape(ticker),
    () => tradeStore.getTape(ticker),
  );
  const netUsd = useSyncExternalStore(
    (listener) => tradeStore.subscribeTicker(ticker, listener),
    () => tradeStore.getNetUsd(ticker),
    () => tradeStore.getNetUsd(ticker),
  );
  const windowTrades = useSyncExternalStore(
    (listener) => tradeStore.subscribeTicker(ticker, listener),
    () => tradeStore.getWindowTrades(ticker),
    () => tradeStore.getWindowTrades(ticker),
  );
  return { tape, netUsd, windowTrades };
}

export function useCumulativeFlow(ticker: string): LineData[] {
  const windowTrades = useSyncExternalStore(
    (listener) => tradeStore.subscribeTicker(ticker, listener),
    () => tradeStore.getWindowTrades(ticker),
    () => tradeStore.getWindowTrades(ticker),
  );
  return cumulativeFlowSeries(windowTrades);
}

export function useTradeNet(tickers: readonly string[]): number {
  const tickersKey = tickers.join("\0");
  return useSyncExternalStore(
    (listener) => tradeStore.subscribeGroup(tickersKey, listener),
    () => tradeStore.netForTickers(tickersKey.split("\0").filter(Boolean)),
    () => tradeStore.netForTickers(tickersKey.split("\0").filter(Boolean)),
  );
}

export async function seedTradesSinceOpen(ticker: string, sinceIso: string | null | undefined): Promise<void> {
  if (!sinceIso) return;
  tradeStore.ensureWindow(ticker, sinceIso);
  const { fetchMarketTrades } = await import("../api");
  const trades = await fetchMarketTrades(ticker, { since: sinceIso, limit: 5000 });
  tradeStore.seedTrades(ticker, trades, sinceIso);
}

export async function seedGroupTradesSinceOpen(
  tickers: readonly string[],
  sinceIso: string | null | undefined,
): Promise<void> {
  if (!sinceIso || tickers.length === 0) return;
  await Promise.all(tickers.map((ticker) => seedTradesSinceOpen(ticker, sinceIso)));
}

export async function seedTickersWithOwnOpen(tickers: readonly string[]): Promise<void> {
  const { marketStore } = await import("./marketStore");
  await Promise.all(
    tickers.map((ticker) => {
      const open = marketStore.getRow(ticker)?.open_time ?? null;
      return seedTradesSinceOpen(ticker, open);
    }),
  );
}
