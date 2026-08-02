export type MarketRow = {
  ticker: string;
  event_ticker: string | null;
  kalshi_url: string;
  event_kalshi_url: string | null;
  title: string | null;
  event_title: string | null;
  series_ticker: string | null;
  series_title: string | null;
  category: string | null;
  status: string | null;
  open_time: string | null;
  close_time: string | null;
  floor_strike: number | null;
  cap_strike: number | null;
  strike_type: string | null;
  yes_bid_cents: number | null;
  yes_ask_cents: number | null;
  no_bid_cents: number | null;
  no_ask_cents: number | null;
  volume: string | null;
  open_interest: string | null;
  seconds_to_close: number | null;
  is_live: boolean;
  has_quotes: boolean;
  has_liquidity: boolean;
};

export type MarketsResponse = {
  markets: MarketRow[];
};

export type HistoryPoint = {
  ts: string;
  yes_cents: number;
};

export type MarketHistory = {
  ticker: string;
  open_time: string | null;
  close_time: string | null;
  window_start: string | null;
  window_end: string | null;
  points: HistoryPoint[];
  incremental?: boolean;
  closed?: boolean;
};

export type TradePrint = {
  ticker: string;
  trade_id: string | null;
  taker_side: string | null;
  signed_usd: number;
  price_cents: number | null;
  count: number | null;
  ts: string;
};

export type ArchivePeriod = {
  event_ticker: string;
  event_title: string | null;
  series_ticker: string | null;
  series_title: string | null;
  bet_name: string;
  open_time: string | null;
  close_time: string | null;
  status: string | null;
  liquid_count: number;
  total_volume: number;
};

export type ArchiveBet = {
  bet_name: string;
  total_volume: number;
  period_count: number;
  periods: ArchivePeriod[];
};

export type ArchiveSeries = {
  series_ticker: string;
  series_title: string | null;
  total_volume: number;
  period_count: number;
  bets: ArchiveBet[];
};

export type ArchiveEvent = {
  event_ticker: string;
  series_ticker: string | null;
  event_title: string | null;
  series_title: string | null;
  bet_name?: string | null;
  open_time: string | null;
  close_time: string | null;
  status: string | null;
  market_count: number;
  total_volume?: number;
};

export type ArchiveMarket = {
  ticker: string;
  event_ticker: string;
  series_ticker: string | null;
  title: string | null;
  event_title: string | null;
  series_title: string | null;
  status: string | null;
  open_time: string | null;
  close_time: string | null;
  floor_strike: number | null;
  cap_strike: number | null;
  strike_type: string | null;
  volume: string | null;
  had_liquidity: boolean;
};

export async function fetchMarkets(): Promise<MarketsResponse> {
  const res = await fetch("/api/markets");
  if (!res.ok) {
    throw new Error(`Failed to load markets (${res.status})`);
  }
  return res.json() as Promise<MarketsResponse>;
}

export async function fetchMarketHistory(ticker: string, since?: string): Promise<MarketHistory> {
  const qs = since ? `?since=${encodeURIComponent(since)}` : "";
  const res = await fetch(`/api/markets/${encodeURIComponent(ticker)}/history${qs}`);
  if (!res.ok) {
    throw new Error(`Failed to load history (${res.status})`);
  }
  return res.json() as Promise<MarketHistory>;
}

export async function fetchMarketTrades(
  ticker: string,
  opts?: { since?: string; limit?: number },
): Promise<TradePrint[]> {
  const params = new URLSearchParams();
  if (opts?.since) params.set("since", opts.since);
  params.set("limit", String(opts?.limit ?? 5000));
  const qs = params.toString();
  const res = await fetch(`/api/markets/${encodeURIComponent(ticker)}/trades?${qs}`);
  if (!res.ok) {
    throw new Error(`Failed to load trades (${res.status})`);
  }
  const payload = (await res.json()) as { trades: TradePrint[] };
  return payload.trades;
}

export type MarketRules = {
  ticker: string;
  markdown: string;
  yes_sub_title?: string | null;
  rules_primary?: string | null;
  rules_secondary?: string | null;
  expiration_value?: string | null;
  settlement_sources?: Array<{ name?: string; url?: string }> | null;
};

export async function fetchMarketRules(ticker: string): Promise<MarketRules> {
  const res = await fetch(`/api/markets/${encodeURIComponent(ticker)}/rules`);
  if (!res.ok) {
    throw new Error(`Failed to load market rules (${res.status})`);
  }
  return res.json() as Promise<MarketRules>;
}

export async function fetchArchiveTree(series?: string, limit = 30): Promise<ArchiveSeries[]> {
  const params = new URLSearchParams();
  if (series) params.set("series", series);
  params.set("limit", String(limit));
  const res = await fetch(`/api/archive/tree?${params}`);
  if (!res.ok) {
    throw new Error(`Failed to load archive (${res.status})`);
  }
  const payload = (await res.json()) as { series?: ArchiveSeries[] };
  return Array.isArray(payload.series) ? payload.series : [];
}

export async function fetchArchiveEventMarkets(eventTicker: string): Promise<ArchiveMarket[]> {
  const res = await fetch(`/api/archive/events/${encodeURIComponent(eventTicker)}/markets`);
  if (!res.ok) {
    throw new Error(`Failed to load archived event (${res.status})`);
  }
  const payload = (await res.json()) as { markets?: ArchiveMarket[] };
  return Array.isArray(payload.markets) ? payload.markets : [];
}

export type ResetPlatformResult = {
  ok: boolean;
  database: Record<string, number>;
  redis_keys_deleted: number;
  tables: string[];
  cleared?: boolean;
};

export async function resetPlatform(confirmPhrase: string): Promise<ResetPlatformResult> {
  const res = await fetch("/api/admin/reset-platform", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmPhrase }),
  });
  if (!res.ok) {
    const text = await res.text();
    let message = text || `Reset failed (${res.status})`;
    try {
      const payload = JSON.parse(text) as { error?: string; detail?: string };
      message = payload.detail || payload.error || message;
    } catch {
      // plain-text error body
    }
    throw new Error(message);
  }
  return res.json() as Promise<ResetPlatformResult>;
}
