import type { MarketRow } from "../api";
import { tradeStore, type TradePrint } from "./tradeStore";

type QuoteUpdate = Partial<MarketRow> & { ticker: string };

type WsMessage =
  | { t: "ready"; count: number; t_send?: number }
  | { t: "q"; updates: QuoteUpdate[]; t_send?: number }
  | { t: "add"; markets: MarketRow[]; t_send?: number }
  | { t: "rm"; tickers: string[]; t_send?: number }
  | { t: "archived"; tickers?: string[]; t_send?: number }
  | { t: "tr"; trades: TradePrint[]; t_send?: number }
  | { t: "pong"; client_t?: number };

type Listener = () => void;

class MarketStore {
  private markets = new Map<string, MarketRow>();
  private listeners = new Map<string, Set<Listener>>();
  private globalListeners = new Set<Listener>();
  private archiveListeners = new Set<Listener>();
  private dirty = new Set<string>();
  private flushScheduled = false;
  private connected = false;
  private socket: WebSocket | null = null;
  private reconnectTimer = 0;
  private backoffMs = 500;
  /** Bumps only when the market list structure changes (seed / add / remove). */
  private listVersion = 0;
  private listSnapshot: MarketRow[] = [];
  private listSnapshotVersion = -1;

  subscribe(ticker: string, listener: Listener): () => void {
    let set = this.listeners.get(ticker);
    if (!set) {
      set = new Set();
      this.listeners.set(ticker, set);
    }
    set.add(listener);
    return () => {
      set?.delete(listener);
      if (set && set.size === 0) {
        this.listeners.delete(ticker);
      }
    };
  }

  subscribeAll(listener: Listener): () => void {
    this.globalListeners.add(listener);
    return () => this.globalListeners.delete(listener);
  }

  subscribeArchive(listener: Listener): () => void {
    this.archiveListeners.add(listener);
    return () => this.archiveListeners.delete(listener);
  }

  /** Stable array reference until list structure changes — safe for useSyncExternalStore. */
  getSnapshot(): MarketRow[] {
    if (this.listSnapshotVersion !== this.listVersion) {
      this.listSnapshot = [...this.markets.values()];
      this.listSnapshotVersion = this.listVersion;
    }
    return this.listSnapshot;
  }

  getRow(ticker: string): MarketRow | undefined {
    return this.markets.get(ticker);
  }

  /** Current rows from the live map (quote fields up to date). */
  getFreshRows(): MarketRow[] {
    return [...this.markets.values()];
  }

  getListVersion(): number {
    return this.listVersion;
  }

  isConnected(): boolean {
    return this.connected;
  }

  seed(rows: MarketRow[]): void {
    this.markets.clear();
    for (const row of rows) {
      this.markets.set(row.ticker, row);
    }
    this.bumpListVersion();
    this.notifyAll();
  }

  addRows(rows: MarketRow[]): void {
    let changed = false;
    for (const row of rows) {
      if (!row.ticker) continue;
      this.markets.set(row.ticker, row);
      changed = true;
    }
    if (!changed) return;
    this.bumpListVersion();
    this.notifyAll();
  }

  removeTickers(tickers: string[]): void {
    let changed = false;
    for (const ticker of tickers) {
      if (this.markets.delete(ticker)) changed = true;
    }
    if (!changed) return;
    this.bumpListVersion();
    this.notifyAll();
  }

  connect(): void {
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${window.location.host}/ws`;
    const ws = new WebSocket(url);
    this.socket = ws;

    ws.onopen = () => {
      this.connected = true;
      this.backoffMs = 500;
      this.notifyConnection();
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(String(event.data)) as WsMessage;
        this.handleMessage(msg);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      this.connected = false;
      this.socket = null;
      this.notifyConnection();
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = window.setTimeout(() => {
        this.backoffMs = Math.min(this.backoffMs * 2, 10_000);
        this.connect();
      }, this.backoffMs);
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  disconnect(): void {
    window.clearTimeout(this.reconnectTimer);
    this.socket?.close();
    this.socket = null;
    this.connected = false;
  }

  private handleMessage(msg: WsMessage): void {
    if (msg.t === "q") {
      for (const update of msg.updates) {
        this.applyUpdate(update);
      }
      return;
    }
    if (msg.t === "add") {
      this.addRows(msg.markets);
      return;
    }
    if (msg.t === "rm") {
      this.removeTickers(msg.tickers);
      tradeStore.clearTickers(msg.tickers);
      return;
    }
    if (msg.t === "tr") {
      tradeStore.pushTrades(msg.trades);
      return;
    }
    if (msg.t === "archived") {
      this.notifyArchive();
      return;
    }
    if (msg.t === "ready" && msg.count !== this.markets.size) {
      void this.resyncFromApi();
    }
  }

  private async resyncFromApi(): Promise<void> {
    try {
      const { fetchMarkets } = await import("../api");
      const payload = await fetchMarkets();
      this.seed(payload.markets);
    } catch {
      // keep current snapshot; reconcile will retry on next ready/connect
    }
  }

  private applyUpdate(update: QuoteUpdate): void {
    const existing = this.markets.get(update.ticker);
    if (!existing) return;
    const merged: MarketRow = { ...existing, ...update };
    this.markets.set(update.ticker, merged);
    this.markDirty(update.ticker);
  }

  private bumpListVersion(): void {
    this.listVersion += 1;
  }

  private markDirty(ticker: string): void {
    this.dirty.add(ticker);
    if (this.flushScheduled) return;
    this.flushScheduled = true;
    requestAnimationFrame(() => {
      this.flushScheduled = false;
      const tickers = [...this.dirty];
      this.dirty.clear();
      for (const t of tickers) {
        const set = this.listeners.get(t);
        if (set) {
          for (const listener of set) listener();
        }
      }
    });
  }

  private notifyAll(): void {
    for (const listener of this.globalListeners) listener();
    for (const set of this.listeners.values()) {
      for (const listener of set) listener();
    }
  }

  private notifyConnection(): void {
    for (const listener of this.globalListeners) listener();
  }

  private notifyArchive(): void {
    for (const listener of this.archiveListeners) listener();
  }
}

export const marketStore = new MarketStore();
