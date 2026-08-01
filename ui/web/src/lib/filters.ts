import type { MarketRow } from "../api";

export type SortKey = "close_time" | "volume" | "series";

export const FIFTEEN_MIN_SERIES = new Set([
  "KXBTC15M",
  "KXETH15M",
  "KXDOGE15M",
  "KXBNB15M",
  "KXSOL15M",
  "KXHYPE15M",
  "KXXRP15M",
]);

export type MarketFilters = {
  search: string;
  liveOnly: boolean;
  hasQuotes: boolean;
  hideNoLiquidity: boolean;
  sortSubByVolume: boolean;
  sortParentByVolume: boolean;
  fifteenMinOnly: boolean;
  category: string;
  series: string;
  closingWithinMinutes: number | null;
  minVolume: number;
  sortBy: SortKey;
};

export const DEFAULT_FILTERS: MarketFilters = {
  search: "",
  liveOnly: true,
  hasQuotes: false,
  hideNoLiquidity: true,
  sortSubByVolume: true,
  sortParentByVolume: false,
  fifteenMinOnly: false,
  category: "all",
  series: "all",
  closingWithinMinutes: null,
  minVolume: 0,
  sortBy: "close_time",
};

function parseVolume(value: string | null): number {
  if (!value) return 0;
  const n = Number(value);
  return Number.isNaN(n) ? 0 : n;
}
function haystack(m: MarketRow): string {
  return [
    m.ticker,
    m.title,
    m.event_title,
    m.series_ticker,
    m.series_title,
    m.category,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function secondsToClose(m: MarketRow, nowMs: number): number | null {
  if (m.close_time) {
    const closeMs = Date.parse(m.close_time);
    if (!Number.isNaN(closeMs)) {
      return Math.max(0, Math.floor((closeMs - nowMs) / 1000));
    }
  }
  return m.seconds_to_close;
}

export function isMarketLive(m: MarketRow, nowMs: number): boolean {
  if (m.is_live != null) return m.is_live;
  if (m.status && m.status !== "active") return false;

  const now = nowMs;
  const openMs = m.open_time ? Date.parse(m.open_time) : NaN;
  const closeMs = m.close_time ? Date.parse(m.close_time) : NaN;

  if (!Number.isNaN(openMs) && now < openMs) return false;
  if (!Number.isNaN(closeMs) && now >= closeMs) return false;
  return m.status === "active" || m.status == null;
}

export function marketHasQuotes(m: MarketRow): boolean {
  if (m.has_quotes != null) return m.has_quotes;
  return m.yes_bid_cents != null || m.yes_ask_cents != null;
}

export function marketHasLiquidity(m: MarketRow): boolean {
  if (parseVolume(m.volume) <= 0) return false;
  if (m.has_liquidity != null) return m.has_liquidity;
  return marketHasQuotes(m);
}

export function applyMarketFilters(
  markets: MarketRow[],
  filters: MarketFilters,
  nowMs: number,
  options?: { keepNoLiquidity?: boolean },
): MarketRow[] {
  const q = filters.search.trim().toLowerCase();
  const skipLiquidity = options?.keepNoLiquidity === true;

  let out = markets.filter((m) => {
    if (filters.liveOnly && !isMarketLive(m, nowMs)) return false;
    if (filters.hasQuotes && !marketHasQuotes(m)) return false;
    if (!skipLiquidity && filters.hideNoLiquidity && !marketHasLiquidity(m)) return false;
    if (filters.fifteenMinOnly && !FIFTEEN_MIN_SERIES.has(m.series_ticker ?? "")) return false;
    if (filters.category !== "all" && (m.category ?? "") !== filters.category) return false;
    if (filters.series !== "all" && (m.series_ticker ?? "") !== filters.series) return false;
    if (parseVolume(m.volume) < filters.minVolume) return false;

    if (filters.closingWithinMinutes != null) {
      const secs = secondsToClose(m, nowMs);
      if (secs == null || secs > filters.closingWithinMinutes * 60) return false;
    }

    if (q && !haystack(m).includes(q)) return false;
    return true;
  });

  out = [...out].sort((a, b) => {
    if (filters.sortBy === "volume") {
      return parseVolume(b.volume) - parseVolume(a.volume);
    }
    if (filters.sortBy === "series") {
      return (a.series_ticker ?? "").localeCompare(b.series_ticker ?? "");
    }
    const aClose = a.close_time ? Date.parse(a.close_time) : Infinity;
    const bClose = b.close_time ? Date.parse(b.close_time) : Infinity;
    return aClose - bClose;
  });

  return out;
}

export function extractFilterOptions(markets: MarketRow[]) {
  const categories = new Set<string>();
  const series = new Set<string>();
  for (const m of markets) {
    if (m.category) categories.add(m.category);
    if (m.series_ticker) series.add(m.series_ticker);
  }
  return {
    categories: [...categories].sort(),
    series: [...series].sort(),
  };
}

export function countLive(markets: MarketRow[], nowMs: number): number {
  return markets.filter((m) => isMarketLive(m, nowMs)).length;
}
