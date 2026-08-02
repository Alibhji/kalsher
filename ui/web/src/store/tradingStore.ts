import {
  cancelOrder,
  createExperiment,
  deleteExperiment,
  fetchFills,
  fetchOpenOrders,
  fetchProfile,
  fetchRoundTrips,
  fetchTradingConfig,
  listExperiments,
  patchExperiment,
  postOrder,
  syncLiveProfile,
  tradeLabel,
  type Experiment,
  type Fill,
  type Order,
  type OrderPayload,
  type Profile,
  type RoundTrip,
  type TradingConfig,
} from "../api/trading";
import {
  liveFundsBanner,
  liveFundsStatus,
  parseTradingError,
  type LiveFundsStatus,
} from "../lib/tradingAlerts";
import { formatUsd } from "../lib/format";
import { notifyError, notifySuccess, notificationStore } from "./notificationStore";

type Listener = () => void;

export type TradingSnapshot = {
  experiments: Experiment[];
  profile: Profile | null;
  fills: Fill[];
  openOrders: Order[];
  activeExperimentId: string | null;
  selectedTicker: string | null;
  focusTicker: string | null;
  focusSeq: number;
  loading: boolean;
  error: string | null;
  tradingConfig: TradingConfig | null;
  preferredMode: "paper" | "live";
};

const STORAGE_KEY = "kalshi.activeExperimentId";
const MODE_KEY = "kalshi.tradingMode";
const EMPTY_TRIPS: RoundTrip[] = [];

function tripsEqual(a: RoundTrip[], b: RoundTrip[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    const left = a[i];
    const right = b[i];
    if (
      left.id !== right.id ||
      left.exit_ts !== right.exit_ts ||
      left.net_pnl !== right.net_pnl ||
      left.pnl_pct !== right.pnl_pct
    ) {
      return false;
    }
  }
  return true;
}

function profileEqual(a: Profile | null, b: Profile | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if (a.positions.length !== b.positions.length) return false;
  for (let i = 0; i < a.positions.length; i++) {
    const left = a.positions[i];
    const right = b.positions[i];
    if (
      left.ticker !== right.ticker ||
      left.side !== right.side ||
      left.qty !== right.qty ||
      left.unrealized_pnl !== right.unrealized_pnl
    ) {
      return false;
    }
  }
  return (
    a.cash === b.cash &&
    a.equity === b.equity &&
    a.realized_pnl === b.realized_pnl &&
    a.unrealized_pnl === b.unrealized_pnl &&
    a.fees_paid === b.fees_paid &&
    a.available_funds === b.available_funds &&
    a.portfolio_value === b.portfolio_value &&
    a.total_pnl === b.total_pnl &&
    a.pnl_pct === b.pnl_pct
  );
}

function fillsEqual(a: Fill[], b: Fill[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  if (a.length === 0) return true;
  return a[0].id === b[0].id && a[a.length - 1].id === b[b.length - 1].id;
}

function ordersEqual(a: Order[], b: Order[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].id !== b[i].id || a[i].status !== b[i].status || a[i].filled_qty !== b[i].filled_qty) {
      return false;
    }
  }
  return true;
}

class TradingStore {
  private experiments: Experiment[] = [];
  private profile: Profile | null = null;
  private fills: Fill[] = [];
  private openOrders: Order[] = [];
  private roundTripsByTicker = new Map<string, RoundTrip[]>();
  private activeExperimentId: string | null = null;
  private selectedTicker: string | null = null;
  private focusTicker: string | null = null;
  private focusSeq = 0;
  private listeners = new Set<Listener>();
  private pollId: number | null = null;
  private loading = false;
  private error: string | null = null;
  private tradingConfig: TradingConfig | null = null;
  private preferredMode: "paper" | "live" =
    (localStorage.getItem(MODE_KEY) as "paper" | "live" | null) ?? "paper";
  private snapshot: TradingSnapshot;
  private refreshInFlight: Promise<void> | null = null;
  private lastFundsStatus: LiveFundsStatus = "ok";
  private lastNotifiedFillId: string | null = null;
  private lastRefreshError: string | null = null;

  constructor() {
    this.activeExperimentId = localStorage.getItem(STORAGE_KEY);
    this.snapshot = this.buildSnapshot();
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private buildSnapshot(): TradingSnapshot {
    return {
      experiments: this.experiments,
      profile: this.profile,
      fills: this.fills,
      openOrders: this.openOrders,
      activeExperimentId: this.activeExperimentId,
      selectedTicker: this.selectedTicker,
      focusTicker: this.focusTicker,
      focusSeq: this.focusSeq,
      loading: this.loading,
      error: this.error,
      tradingConfig: this.tradingConfig,
      preferredMode: this.preferredMode,
    };
  }

  private emit() {
    this.snapshot = this.buildSnapshot();
    for (const l of this.listeners) l();
  }

  private emitIfMeaningful(prev: {
    profile: Profile | null;
    fills: Fill[];
    openOrders: Order[];
    loading: boolean;
    error: string | null;
  }) {
    if (
      prev.loading === this.loading &&
      prev.error === this.error &&
      profileEqual(prev.profile, this.profile) &&
      fillsEqual(prev.fills, this.fills) &&
      ordersEqual(prev.openOrders, this.openOrders)
    ) {
      return;
    }
    this.emit();
  }

  private clearLiveFundAlerts() {
    notificationStore.dismiss("live-funds-empty");
    notificationStore.dismiss("live-funds-critical");
    notificationStore.dismiss("live-funds-warning");
  }

  private checkLiveFundsAlerts(profile: Profile | null, isLive: boolean) {
    if (!isLive) {
      this.lastFundsStatus = "ok";
      this.clearLiveFundAlerts();
      return;
    }
    const status = liveFundsStatus(profile);
    if (status === this.lastFundsStatus) return;
    this.lastFundsStatus = status;
    this.clearLiveFundAlerts();
    const banner = liveFundsBanner(profile);
    if (!banner) return;
    const level = banner.level === "warning" ? "warning" : "error";
    notificationStore.notify({
      id: `live-funds-${banner.level}`,
      level,
      title: banner.title,
      message: banner.message,
      durationMs: banner.level === "warning" ? 8000 : 15000,
    });
  }

  private notifyNewFill(prevFills: Fill[], isLive: boolean) {
    const latest = this.fills[0];
    if (!latest || latest.id === prevFills[0]?.id || latest.id === this.lastNotifiedFillId) return;
    this.lastNotifiedFillId = latest.id;
    const priceCents = Math.round(Number(latest.price) * 100);
    const modeLabel = isLive ? "Live fill" : "Paper fill";
    notifySuccess(
      modeLabel,
      `${tradeLabel(latest.side, latest.action)} · ${latest.qty} @ ${priceCents}¢ · ${formatUsd(Number(latest.cost))}`,
    );
  }

  private notifyRefreshError(message: string, isLive: boolean) {
    if (message === this.lastRefreshError) return;
    this.lastRefreshError = message;
    const parsed = parseTradingError(new Error(message));
    notifyError(
      isLive ? "Live account sync failed" : parsed.title,
      isLive ? message : parsed.message,
    );
  }

  private clearRefreshError() {
    this.lastRefreshError = null;
  }

  private notifyActionError(err: unknown) {
    const parsed = parseTradingError(err);
    notifyError(parsed.title, parsed.message);
    throw err instanceof Error ? err : new Error(parsed.message);
  }

  getSnapshot(): TradingSnapshot {
    return this.snapshot;
  }

  getRoundTrips(ticker: string): RoundTrip[] {
    return this.roundTripsByTicker.get(ticker) ?? EMPTY_TRIPS;
  }

  setSelectedTicker(ticker: string | null) {
    this.selectedTicker = ticker;
    this.emit();
    if (ticker && this.activeExperimentId) {
      void this.refreshRoundTrips(ticker);
    }
  }

  focusMarket(ticker: string) {
    this.focusTicker = ticker;
    this.selectedTicker = ticker;
    this.focusSeq += 1;
    this.emit();
    if (this.activeExperimentId) {
      void this.refreshRoundTrips(ticker);
    }
  }

  async bootstrap() {
    this.loading = true;
    this.error = null;
    this.emit();
    try {
      this.tradingConfig = await fetchTradingConfig();
      this.experiments = await listExperiments();
      const modeExp = this.findExperimentForMode(this.preferredMode);
      if (modeExp) {
        this.activeExperimentId = modeExp.id;
        localStorage.setItem(STORAGE_KEY, modeExp.id);
      } else if (!this.activeExperimentId && this.experiments.length > 0) {
        this.activeExperimentId = this.experiments[0].id;
        localStorage.setItem(STORAGE_KEY, this.activeExperimentId);
      }
      if (!this.activeExperimentId) {
        const exp = await createExperiment(`paper-${Date.now()}`, 10000, "paper");
        this.experiments = [exp];
        this.activeExperimentId = exp.id;
        localStorage.setItem(STORAGE_KEY, exp.id);
      }
      await this.refresh();
      this.startPolling();
    } catch (err) {
      this.error = err instanceof Error ? err.message : "Trading unavailable";
      const parsed = parseTradingError(err);
      notifyError("Trading unavailable", parsed.message);
    } finally {
      this.loading = false;
      this.emit();
    }
  }

  private findExperimentForMode(mode: "paper" | "live"): Experiment | undefined {
    return this.experiments.find((e) => e.mode === mode && e.status === "active");
  }

  async switchMode(mode: "paper" | "live") {
    this.preferredMode = mode;
    localStorage.setItem(MODE_KEY, mode);
    this.loading = true;
    this.error = null;
    this.emit();
    try {
      let exp = this.findExperimentForMode(mode);
      if (!exp) {
        if (mode === "live") {
          if (!this.tradingConfig?.live_trading_enabled) {
            throw new Error("Live trading disabled — set TRADING_LIVE_ENABLED=true");
          }
          if (!this.tradingConfig?.kalshi_configured) {
            throw new Error("Kalshi API keys not configured");
          }
          exp = await createExperiment(`live-${Date.now()}`, 0, "live");
        } else {
          exp = await createExperiment(`paper-${Date.now()}`, 10000, "paper");
        }
        this.experiments = [exp, ...this.experiments];
      }
      this.activeExperimentId = exp.id;
      localStorage.setItem(STORAGE_KEY, exp.id);
      if (mode === "live") {
        this.profile = await syncLiveProfile(exp.id);
        notifySuccess("Live trading active", "Account balance synced from Kalshi.");
      }
      await this.refresh();
    } catch (err) {
      this.error = err instanceof Error ? err.message : "Mode switch failed";
      const parsed = parseTradingError(err);
      notifyError(parsed.title, parsed.message);
    } finally {
      this.loading = false;
      this.emit();
    }
  }

  startPolling() {
    if (this.pollId != null) return;
    this.pollId = window.setInterval(() => {
      void this.refresh();
    }, 2000);
  }

  stopPolling() {
    if (this.pollId != null) {
      window.clearInterval(this.pollId);
      this.pollId = null;
    }
  }

  async setActiveExperiment(id: string) {
    this.activeExperimentId = id;
    localStorage.setItem(STORAGE_KEY, id);
    const exp = this.experiments.find((e) => e.id === id);
    if (exp && (exp.mode === "paper" || exp.mode === "live")) {
      this.preferredMode = exp.mode;
      localStorage.setItem(MODE_KEY, exp.mode);
    }
    await this.refresh();
  }

  async createPaperExperiment(name?: string, tags: string[] = []) {
    const exp = await createExperiment(name ?? `paper-${Date.now()}`, 10000, "paper", tags);
    this.experiments = [exp, ...this.experiments];
    await this.setActiveExperiment(exp.id);
  }

  async updatePaperTags(experimentId: string, tags: string[]) {
    const exp = await patchExperiment(experimentId, { tags });
    this.experiments = this.experiments.map((e) => (e.id === experimentId ? exp : e));
    this.emit();
  }

  async deletePaperExperiment(experimentId: string) {
    await deleteExperiment(experimentId, true);
    this.experiments = this.experiments.filter((e) => e.id !== experimentId);
    if (this.activeExperimentId === experimentId) {
      const next = this.experiments.find((e) => e.mode === "paper" && e.status === "active");
      this.activeExperimentId = next?.id ?? this.experiments[0]?.id ?? null;
      if (this.activeExperimentId) {
        localStorage.setItem(STORAGE_KEY, this.activeExperimentId);
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    }
    this.emit();
    if (this.activeExperimentId) {
      await this.refresh();
    }
  }

  async refresh() {
    if (!this.activeExperimentId) return;
    if (this.refreshInFlight) {
      await this.refreshInFlight;
      return;
    }

    const prev = {
      profile: this.profile,
      fills: this.fills,
      openOrders: this.openOrders,
      loading: this.loading,
      error: this.error,
    };

    this.refreshInFlight = (async () => {
      const active = this.experiments.find((e) => e.id === this.activeExperimentId);
      const isLive = active?.mode === "live";
      try {
        if (isLive) {
          this.profile = await syncLiveProfile(this.activeExperimentId!);
        } else {
          this.profile = await fetchProfile(this.activeExperimentId!);
        }
        const prevFills = this.fills;
        this.fills = await fetchFills(this.activeExperimentId!);
        this.openOrders = await fetchOpenOrders(this.activeExperimentId!);
        if (this.selectedTicker) {
          await this.refreshRoundTrips(this.selectedTicker, false);
        }
        this.error = null;
        this.clearRefreshError();
        this.checkLiveFundsAlerts(this.profile, isLive);
        this.notifyNewFill(prevFills, isLive);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Refresh failed";
        this.error = message;
        this.notifyRefreshError(message, isLive);
      } finally {
        this.refreshInFlight = null;
      }
    })();

    await this.refreshInFlight;
    this.emitIfMeaningful(prev);
  }

  async refreshRoundTrips(ticker: string, notify = true) {
    if (!this.activeExperimentId) return;
    const trips = await fetchRoundTrips(this.activeExperimentId, ticker);
    const prev = this.roundTripsByTicker.get(ticker) ?? EMPTY_TRIPS;
    if (tripsEqual(prev, trips)) return;
    this.roundTripsByTicker.set(ticker, trips);
    if (notify) this.emit();
  }

  async submitOrder(payload: OrderPayload, confirmLive = false) {
    if (!this.activeExperimentId) {
      notifyError("No active session", "Select or create a trading experiment first.");
      throw new Error("No active experiment");
    }
    try {
      await postOrder(this.activeExperimentId, payload, confirmLive);
      await this.refresh();
    } catch (err) {
      this.notifyActionError(err);
    }
  }

  async closeOpenOrder(order: Order, confirmLive = false) {
    if (!this.activeExperimentId) return;
    try {
      if (order.status === "open" || order.status === "pending") {
        try {
          await cancelOrder(order.id, confirmLive);
        } catch {
          // order may already be gone on exchange
        }
      }

      const pos = this.profile?.positions.find(
        (p) => p.ticker === order.ticker && p.side === order.side,
      );
      const posQty = pos ? Number(pos.qty) : 0;

      if (posQty > 0) {
        const closeAction = order.action === "buy" ? "sell" : "buy";
        await postOrder(
          this.activeExperimentId,
          {
            ticker: order.ticker,
            side: order.side,
            action: closeAction,
            type: "market",
            qty: posQty,
          },
          confirmLive,
        );
        notifySuccess(
          "Trade closed",
          `${closeAction.toUpperCase()} ${order.side.toUpperCase()} · ${posQty} ${order.ticker.slice(0, 16)}…`,
        );
      } else {
        notifySuccess("Order cancelled");
      }
      await this.refresh();
    } catch (err) {
      this.notifyActionError(err);
    }
  }

  async closePosition(ticker: string, side: "yes" | "no", confirmLive = false) {
    if (!this.activeExperimentId) return;
    const pos = this.profile?.positions.find((p) => p.ticker === ticker && p.side === side);
    if (!pos) return;
    await this.submitOrder(
      {
        ticker,
        side,
        action: "sell",
        type: "market",
        qty: Number(pos.qty),
      },
      confirmLive,
    );
  }
}

export const tradingStore = new TradingStore();
