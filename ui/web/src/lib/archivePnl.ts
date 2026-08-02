import type { PnlPoint, RoundTrip } from "../api/trading";

/** Derive event ticker from a strike ticker (e.g. KXBTCD-26AUG0103-T100000). */
export function eventTickerFromMarketTicker(ticker: string): string {
  const idx = ticker.lastIndexOf("-T");
  return idx > 0 ? ticker.slice(0, idx) : ticker;
}

export function filterTripsForEvent(
  trips: RoundTrip[],
  eventTicker: string,
  marketTickers?: Iterable<string>,
): RoundTrip[] {
  const tickers = marketTickers ? new Set(marketTickers) : null;
  return trips.filter((rt) => {
    if (tickers) return tickers.has(rt.ticker);
    return eventTickerFromMarketTicker(rt.ticker) === eventTicker;
  });
}

export function sumNetPnl(trips: RoundTrip[]): number {
  return trips.reduce((acc, rt) => {
    if (rt.exit_ts == null || rt.net_pnl == null) return acc;
    return acc + Number(rt.net_pnl);
  }, 0);
}

export function buildTradedEventsSet(trips: RoundTrip[]): Set<string> {
  const out = new Set<string>();
  for (const rt of trips) {
    out.add(eventTickerFromMarketTicker(rt.ticker));
  }
  return out;
}

export function buildEventPnlByTicker(trips: RoundTrip[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const rt of trips) {
    if (rt.exit_ts == null || rt.net_pnl == null) continue;
    const event = eventTickerFromMarketTicker(rt.ticker);
    out.set(event, (out.get(event) ?? 0) + Number(rt.net_pnl));
  }
  return out;
}

export function roundTripsToPnlPoints(trips: RoundTrip[]): PnlPoint[] {
  const closed = trips
    .filter((r) => r.exit_ts && r.net_pnl != null)
    .sort((a, b) => Date.parse(a.exit_ts!) - Date.parse(b.exit_ts!));
  let cumulative = 0;
  return closed.map((r) => {
    cumulative += Number(r.net_pnl);
    return { ts: r.exit_ts!, cumulative_pnl: String(cumulative) };
  });
}

export function formatArchiveWindow(openTime: string | null, closeTime: string | null): string {
  if (!closeTime) return "unknown window";
  const close = new Date(closeTime);
  const open = openTime ? new Date(openTime) : null;
  const closeLabel = close.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  if (!open) return closeLabel;
  const sameDay = open.toDateString() === close.toDateString();
  const openLabel = open.toLocaleString(undefined, {
    month: sameDay ? undefined : "short",
    day: sameDay ? undefined : "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${openLabel} → ${closeLabel}`;
}

export function archiveMarketVolume(volume: string | null | undefined): number {
  const n = Number(volume ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function slug(text: string): string {
  const lowered = text.toLowerCase().replace(/\//g, "");
  return lowered.replace(/[^a-z0-9]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "") || "market";
}

export function kalshiMarketUrl(
  ticker: string,
  opts?: {
    event_ticker?: string | null;
    series_ticker?: string | null;
    series_title?: string | null;
    event_title?: string | null;
  },
): string {
  const base = "https://kalshi.com";
  const eventTicker = opts?.event_ticker;
  const seriesTicker = opts?.series_ticker;
  if (seriesTicker) {
    const seriesSlug = slug(opts?.series_title || opts?.event_title || seriesTicker);
    return `${base}/markets/${seriesTicker.toLowerCase()}/${seriesSlug}/${ticker.toLowerCase()}`;
  }
  if (eventTicker) {
    return `${base}/markets/${eventTicker.toLowerCase()}`;
  }
  return `${base}/markets/${ticker.toLowerCase()}`;
}
