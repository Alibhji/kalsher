import type { LineData, UTCTimestamp } from "lightweight-charts";

export type TradePrint = {
  ticker: string;
  trade_id: string | null;
  taker_side: string | null;
  signed_usd: number;
  price_cents: number | null;
  count: number | null;
  ts: string;
};

const RING_SIZE = 80;
const MAX_WINDOW_TRADES = 20_000;
const MAX_SEEN_IDS = 20_000;

/**
 * Shared instance for "no trades yet". A fresh `[]` here is not merely wasteful:
 * these getters back useSyncExternalStore, and a new reference each read makes the
 * snapshot look permanently changed, so React re-renders until it throws.
 */
const EMPTY_TRADES: readonly TradePrint[] = Object.freeze([]);

type Listener = () => void;

function parseMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

export function cumulativeFlowSeries(trades: readonly TradePrint[]): LineData[] {
  let cum = 0;
  const bySecond = new Map<number, LineData>();
  for (const trade of trades) {
    cum += trade.signed_usd;
    const sec = Math.floor(Date.parse(trade.ts) / 1000);
    if (Number.isNaN(sec)) continue;
    bySecond.set(sec, { time: sec as UTCTimestamp, value: cum });
  }
  return [...bySecond.entries()]
    .sort(([a], [b]) => a - b)
    .map(([, point]) => point);
}

class TradeStore {
  private windowStartMs = new Map<string, number>();
  private windowTrades = new Map<string, TradePrint[]>();
  private tapeByTicker = new Map<string, TradePrint[]>();
  private netByTicker = new Map<string, number>();
  private listeners = new Map<string, Set<Listener>>();
  private groupListeners = new Map<string, Set<Listener>>();
  private seenIds = new Set<string>();

  subscribeTicker(ticker: string, listener: Listener): () => void {
    return this._subscribe(this.listeners, ticker, listener);
  }

  subscribeGroup(tickersKey: string, listener: Listener): () => void {
    return this._subscribe(this.groupListeners, tickersKey, listener);
  }

  getTape(ticker: string): readonly TradePrint[] {
    return this.tapeByTicker.get(ticker) ?? EMPTY_TRADES;
  }

  getWindowTrades(ticker: string): readonly TradePrint[] {
    return this.windowTrades.get(ticker) ?? EMPTY_TRADES;
  }

  getNetUsd(ticker: string): number {
    return this.netByTicker.get(ticker) ?? 0;
  }

  netForTickers(tickers: readonly string[]): number {
    let total = 0;
    for (const ticker of tickers) {
      total += this.netByTicker.get(ticker) ?? 0;
    }
    return total;
  }

  seedTrades(ticker: string, trades: TradePrint[], sinceIso: string | null | undefined): void {
    const sinceMs = parseMs(sinceIso);
    if (sinceMs != null) {
      this.windowStartMs.set(ticker, sinceMs);
    } else {
      this.windowStartMs.delete(ticker);
    }

    const window: TradePrint[] = [];
    const tape: TradePrint[] = [];
    let net = 0;
    const batchSeen = new Set<string>();
    for (const trade of trades) {
      if (!this._acceptTrade(trade, sinceMs)) continue;
      const key = trade.trade_id
        ? `${trade.ticker}:${trade.trade_id}`
        : `${trade.ticker}:${trade.ts}:${trade.signed_usd}`;
      if (batchSeen.has(key)) continue;
      batchSeen.add(key);
      this._remember(key);
      window.push(trade);
      tape.push(trade);
      net += trade.signed_usd;
      if (tape.length > RING_SIZE) {
        tape.splice(0, tape.length - RING_SIZE);
      }
    }
    if (window.length > MAX_WINDOW_TRADES) {
      window.splice(0, window.length - MAX_WINDOW_TRADES);
    }

    this.windowTrades.set(ticker, window);
    this.tapeByTicker.set(ticker, tape);
    this.netByTicker.set(ticker, net);
    this.notifyTicker(ticker);
  }

  ensureWindow(ticker: string, sinceIso: string | null | undefined): void {
    const sinceMs = parseMs(sinceIso);
    if (sinceMs == null) return;
    const existing = this.windowStartMs.get(ticker);
    if (existing === sinceMs) return;
    this.seedTrades(ticker, [], sinceIso);
  }

  pushTrades(trades: TradePrint[]): void {
    const touched = new Set<string>();
    for (const trade of trades) {
      if (this.pushTrade(trade, { skipNotify: true })) {
        touched.add(trade.ticker);
      }
    }
    for (const ticker of touched) {
      this.notifyTicker(ticker);
    }
  }

  clearTicker(ticker: string): void {
    this.windowStartMs.delete(ticker);
    this.windowTrades.delete(ticker);
    this.tapeByTicker.delete(ticker);
    this.netByTicker.delete(ticker);
    this.notifyTicker(ticker);
  }

  clearTickers(tickers: string[]): void {
    for (const ticker of tickers) {
      this.clearTicker(ticker);
    }
  }

  private pushTrade(trade: TradePrint, opts?: { skipNotify?: boolean }): boolean {
    const sinceMs = this.windowStartMs.get(trade.ticker);
    if (!this._acceptTrade(trade, sinceMs)) return false;
    if (!this._markSeen(trade)) return false;

    const prev = this.windowTrades.get(trade.ticker) ?? [];
    let next = [...prev, trade];
    if (next.length > MAX_WINDOW_TRADES) {
      next = next.slice(next.length - MAX_WINDOW_TRADES);
    }
    this.windowTrades.set(trade.ticker, next);

    const prevTape = this.tapeByTicker.get(trade.ticker) ?? [];
    let nextTape = [...prevTape, trade];
    if (nextTape.length > RING_SIZE) {
      nextTape = nextTape.slice(nextTape.length - RING_SIZE);
    }
    this.tapeByTicker.set(trade.ticker, nextTape);
    this.netByTicker.set(trade.ticker, (this.netByTicker.get(trade.ticker) ?? 0) + trade.signed_usd);

    if (!opts?.skipNotify) {
      this.notifyTicker(trade.ticker);
    }
    return true;
  }

  private _acceptTrade(trade: TradePrint, sinceMs: number | null | undefined): boolean {
    const tradeMs = Date.parse(trade.ts);
    if (sinceMs != null && !Number.isNaN(tradeMs) && tradeMs < sinceMs) {
      return false;
    }
    return true;
  }

  private _markSeen(trade: TradePrint): boolean {
    const key = trade.trade_id
      ? `${trade.ticker}:${trade.trade_id}`
      : `${trade.ticker}:${trade.ts}:${trade.signed_usd}`;
    if (this.seenIds.has(key)) return false;
    this._remember(key);
    return true;
  }

  /** Evict oldest ids rather than clearing, which would let replayed trades through. */
  private _remember(key: string): void {
    this.seenIds.add(key);
    if (this.seenIds.size <= MAX_SEEN_IDS) return;
    const evict = this.seenIds.size - MAX_SEEN_IDS + MAX_SEEN_IDS / 4;
    let removed = 0;
    for (const old of this.seenIds) {
      this.seenIds.delete(old);
      if (++removed >= evict) break;
    }
  }

  private notifyTicker(ticker: string): void {
    const set = this.listeners.get(ticker);
    if (set) {
      for (const listener of set) listener();
    }
    for (const [key, groupSet] of this.groupListeners) {
      if (!key.split("\0").includes(ticker)) continue;
      for (const listener of groupSet) listener();
    }
  }

  private _subscribe(map: Map<string, Set<Listener>>, key: string, listener: Listener): () => void {
    let set = map.get(key);
    if (!set) {
      set = new Set();
      map.set(key, set);
    }
    set.add(listener);
    return () => {
      set?.delete(listener);
      if (set && set.size === 0) {
        map.delete(key);
      }
    };
  }
}

export const tradeStore = new TradeStore();
