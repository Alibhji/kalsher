export type TradeSide = "yes" | "no";
export type TradeAction = "buy" | "sell";
export type OrderType = "market" | "limit";

export type Experiment = {
  id: string;
  name: string;
  mode: "paper" | "live";
  initial_capital: string;
  cash: string;
  status: string;
  created_at?: string;
  archived_at?: string | null;
  tags?: string[];
};

export type ExperimentStats = {
  experiment_id: string;
  name: string;
  mode: string;
  closed_trades: number;
  wins: number;
  net_pnl: string;
  max_drawdown: string;
  win_rate: string | null;
  profit_factor?: string | null;
};

export type Profile = {
  experiment_id: string;
  name: string;
  mode: string;
  cash: string;
  initial_capital: string;
  realized_pnl: string;
  unrealized_pnl: string;
  fees_paid: string;
  equity: string;
  drawdown: string;
  positions: Array<{
    ticker: string;
    side: TradeSide;
    qty: string;
    avg_price: string;
    cost_basis: string | null;
    mark_price: string | null;
    unrealized_pnl: string | null;
  }>;
  available_funds?: string | null;
  portfolio_value?: string | null;
  total_pnl?: string | null;
  pnl_pct?: string | null;
  capital_invested?: string | null;
  live_trading_enabled?: boolean;
};

export type TradingConfig = {
  live_trading_enabled: boolean;
  kalshi_configured: boolean;
};

export type Fill = {
  id: string;
  ts: string;
  ticker: string;
  side: TradeSide;
  action: TradeAction;
  price: string;
  qty: string;
  fee: string;
  cost: string;
  cash_impact: string;
  trade_pnl?: string | null;
  trade_pnl_pct?: string | null;
};

export type RoundTrip = {
  id: string;
  ticker: string;
  side: TradeSide;
  qty: string;
  entry_ts: string;
  entry_price: string;
  exit_ts: string | null;
  exit_price: string | null;
  cost_basis: string;
  gross_pnl: string | null;
  fees: string;
  net_pnl: string | null;
  pnl_pct: string | null;
  exit_kind: string | null;
  action_at_entry: string;
};

export type PeriodSummary = {
  start: string | null;
  end: string;
  realized_pnl: string;
  pnl_pct: string | null;
  closed_trades: number;
  wins: number;
  fill_count: number;
  win_rate: string | null;
  source: string;
  baseline: string;
  capital_invested?: string | null;
  net_deposits?: string | null;
};

export type PnlPoint = {
  ts: string;
  cumulative_pnl: string;
  equity?: string | null;
};

export type HistoryQuery = {
  start?: string;
  end?: string;
  source?: "auto" | "local" | "kalshi" | "all";
};

function historyQs(query?: HistoryQuery): string {
  if (!query) return "";
  const params = new URLSearchParams();
  if (query.start) params.set("start", query.start);
  if (query.end) params.set("end", query.end);
  if (query.source) params.set("source", query.source);
  const s = params.toString();
  return s ? `?${s}` : "";
}

export type OrderPayload = {
  ticker: string;
  side: TradeSide;
  action: TradeAction;
  type: OrderType;
  qty: number;
  limit_price?: number;
  client_order_id?: string;
};

export type Order = {
  id: string;
  experiment_id: string;
  client_order_id: string | null;
  ticker: string;
  side: TradeSide;
  action: TradeAction;
  type: OrderType;
  limit_price: string | null;
  qty: string;
  filled_qty: string;
  status: string;
  mode: string;
  kalshi_order_id: string | null;
  reason: string | null;
  created_at: string;
  updated_at: string;
};

const BASE = "/api/trading";

async function tradingFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    let message = text || `Request failed (${res.status})`;
    try {
      const payload = JSON.parse(text) as { detail?: string; error?: string };
      message = payload.detail || payload.error || message;
    } catch {
      // plain text
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export async function listExperiments(includeArchived = false, tag?: string): Promise<Experiment[]> {
  const params = new URLSearchParams();
  if (includeArchived) params.set("include_archived", "true");
  if (tag) params.set("tag", tag);
  const qs = params.toString();
  return tradingFetch(`/experiments${qs ? `?${qs}` : ""}`);
}

export async function fetchExperiment(experimentId: string): Promise<Experiment> {
  return tradingFetch(`/experiments/${experimentId}`);
}

export async function fetchStats(experimentId: string): Promise<ExperimentStats> {
  return tradingFetch(`/experiments/${experimentId}/stats`);
}

export async function createExperiment(
  name: string,
  initialCapital = 10000,
  mode: "paper" | "live" = "paper",
  tags: string[] = [],
): Promise<Experiment> {
  const body: Record<string, unknown> = { name, mode };
  if (mode === "paper") {
    body.initial_capital = initialCapital;
  }
  if (tags.length > 0) {
    body.tags = tags;
  }
  return tradingFetch("/experiments", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function patchExperiment(
  experimentId: string,
  patch: { name?: string; tags?: string[] },
): Promise<Experiment> {
  return tradingFetch(`/experiments/${experimentId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteExperiment(experimentId: string, permanent = false): Promise<Experiment> {
  const qs = permanent ? "?permanent=true" : "";
  return tradingFetch(`/experiments/${experimentId}${qs}`, { method: "DELETE" });
}

export async function fetchTradingConfig(): Promise<TradingConfig> {
  return tradingFetch("/config");
}

export async function syncLiveProfile(experimentId: string): Promise<Profile> {
  return tradingFetch(`/experiments/${experimentId}/sync_live`, { method: "POST" });
}

export async function fetchProfile(experimentId: string): Promise<Profile> {
  return tradingFetch(`/experiments/${experimentId}/profile`);
}

export async function syncKalshiHistory(experimentId: string): Promise<{
  fill_count: number;
  first_ts: string | null;
  last_ts: string | null;
  source: string;
}> {
  return tradingFetch(`/experiments/${experimentId}/sync_kalshi_history`, { method: "POST" });
}

export async function fetchPeriodSummary(
  experimentId: string,
  query?: HistoryQuery,
): Promise<PeriodSummary> {
  return tradingFetch(`/experiments/${experimentId}/period_summary${historyQs(query)}`);
}

export async function fetchPnlSeries(
  experimentId: string,
  query?: HistoryQuery,
): Promise<{ points: PnlPoint[]; source: string }> {
  return tradingFetch(`/experiments/${experimentId}/pnl_series${historyQs(query)}`);
}

export async function fetchFills(
  experimentId: string,
  ticker?: string,
  query?: HistoryQuery,
): Promise<Fill[]> {
  const params = new URLSearchParams();
  if (ticker) params.set("ticker", ticker);
  if (query?.start) params.set("start", query.start);
  if (query?.end) params.set("end", query.end);
  if (query?.source) params.set("source", query.source);
  const qs = params.toString();
  return tradingFetch(`/experiments/${experimentId}/fills${qs ? `?${qs}` : ""}`);
}

export async function fetchRoundTrips(
  experimentId: string,
  ticker?: string,
  query?: HistoryQuery,
): Promise<RoundTrip[]> {
  const params = new URLSearchParams();
  if (ticker) params.set("ticker", ticker);
  if (query?.start) params.set("start", query.start);
  if (query?.end) params.set("end", query.end);
  if (query?.source) params.set("source", query.source);
  const qs = params.toString();
  return tradingFetch(`/experiments/${experimentId}/round_trips${qs ? `?${qs}` : ""}`);
}

export async function fetchOrders(experimentId: string, status?: string): Promise<Order[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return tradingFetch(`/experiments/${experimentId}/orders${qs}`);
}

export async function fetchOpenOrders(experimentId: string): Promise<Order[]> {
  const rows = await fetchOrders(experimentId);
  return rows.filter((o) => o.status === "open" || o.status === "pending");
}

export async function cancelOrder(orderId: string, confirmLive = false): Promise<Order> {
  return tradingFetch(`/orders/${orderId}`, {
    method: "DELETE",
    headers: confirmLive ? { "X-Confirm-Live": "yes" } : {},
  });
}

export async function postOrder(
  experimentId: string,
  payload: OrderPayload,
  confirmLive = false,
): Promise<unknown> {
  return tradingFetch(`/experiments/${experimentId}/orders`, {
    method: "POST",
    headers: confirmLive ? { "X-Confirm-Live": "yes" } : {},
    body: JSON.stringify({
      ...payload,
      qty: payload.qty,
      limit_price: payload.limit_price,
    }),
  });
}

export async function closeAll(experimentId: string, ticker?: string, confirmLive = false): Promise<unknown> {
  return tradingFetch(`/experiments/${experimentId}/close_all`, {
    method: "POST",
    headers: confirmLive ? { "X-Confirm-Live": "yes" } : {},
    body: JSON.stringify({ ticker: ticker ?? null }),
  });
}

export function tradeLabel(side: TradeSide, action: TradeAction): string {
  return `${action.toUpperCase()} ${side.toUpperCase()}`;
}
