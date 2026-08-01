import type { MarketRow } from "../api";
import { marketHasLiquidity } from "./filters";

/** Matches fetcher/config.yaml series_allowlist calendar order. */
export const SERIES_ORDER = [
  "KXBTC15M",
  "KXETH15M",
  "KXDOGE15M",
  "KXBNB15M",
  "KXSOL15M",
  "KXHYPE15M",
  "KXXRP15M",
  "KXBTCD",
  "KXETHD",
  "KXSOLD",
] as const;

export type EventGroup = {
  eventTicker: string;
  eventTitle: string;
  eventKalshiUrl: string | null;
  closeTime: string | null;
  secondsToClose: number | null;
  isLive: boolean;
  totalVolume: number;
  liquidCount: number;
  strikeCount: number;
  tickers: string[];
  markets: MarketRow[];
};

export type SeriesGroup = {
  seriesTicker: string;
  seriesTitle: string;
  events: EventGroup[];
  marketCount: number;
  totalVolume: number;
  liquidCount: number;
  tickers: string[];
};

export type GroupMarketsOptions = {
  sortSubByVolume?: boolean;
  sortParentByVolume?: boolean;
  hideNoLiquidity?: boolean;
};

export function parseVolume(value: string | null | undefined): number {
  if (!value) return 0;
  const n = Number(value);
  return Number.isNaN(n) ? 0 : n;
}

function strikeSortKey(m: MarketRow): number {
  if (m.floor_strike != null) return m.floor_strike;
  if (m.cap_strike != null) return m.cap_strike;
  return 0;
}

function sortMarkets(rows: MarketRow[], sortSubByVolume: boolean): MarketRow[] {
  const sorted = [...rows];
  if (sortSubByVolume) {
    sorted.sort((a, b) => {
      const volDiff = parseVolume(b.volume) - parseVolume(a.volume);
      if (volDiff !== 0) return volDiff;
      return strikeSortKey(a) - strikeSortKey(b);
    });
  } else {
    sorted.sort((a, b) => strikeSortKey(a) - strikeSortKey(b));
  }
  return sorted;
}

function sortByVolumeThenTicker<T extends { totalVolume: number }>(
  rows: T[],
  ticker: (row: T) => string,
): T[] {
  return [...rows].sort((a, b) => {
    const volDiff = b.totalVolume - a.totalVolume;
    if (volDiff !== 0) return volDiff;
    return ticker(a).localeCompare(ticker(b));
  });
}

function sumVolume(rows: MarketRow[]): number {
  return rows.reduce((total, row) => total + parseVolume(row.volume), 0);
}

export function groupMarkets(
  markets: MarketRow[],
  options: GroupMarketsOptions = {},
): SeriesGroup[] {
  const sortSubByVolume = options.sortSubByVolume ?? true;
  const sortParentByVolume = options.sortParentByVolume ?? false;
  const hideNoLiquidity = options.hideNoLiquidity ?? true;
  const bySeries = new Map<string, Map<string, MarketRow[]>>();

  for (const market of markets) {
    const series = market.series_ticker ?? "UNKNOWN";
    const event = market.event_ticker ?? market.ticker;
    if (!bySeries.has(series)) bySeries.set(series, new Map());
    const events = bySeries.get(series)!;
    if (!events.has(event)) events.set(event, []);
    events.get(event)!.push(market);
  }

  const groups: SeriesGroup[] = [];

  for (const [seriesTicker, eventsMap] of bySeries) {
    const events: EventGroup[] = [];
    let sampleRow: MarketRow | undefined;
    for (const [eventTicker, rows] of eventsMap) {
      if (!sampleRow) sampleRow = rows[0];
      const liquidRows = rows.filter((r) => marketHasLiquidity(r));
      const subRows =
        liquidRows.length === 0
          ? []
          : hideNoLiquidity
            ? liquidRows
            : rows;
      const sortedRows = sortMarkets(subRows, sortSubByVolume);
      const head = rows[0];
      events.push({
        eventTicker,
        eventTitle: head.event_title || head.title || eventTicker,
        eventKalshiUrl: head.event_kalshi_url,
        closeTime: head.close_time,
        secondsToClose: head.seconds_to_close,
        isLive: rows.some((r) => r.is_live),
        totalVolume: sumVolume(rows),
        liquidCount: liquidRows.length,
        strikeCount: rows.length,
        tickers: rows.map((r) => r.ticker),
        markets: sortedRows,
      });
    }

    const sortedEvents = sortParentByVolume
      ? sortByVolumeThenTicker(events, (e) => e.eventTicker)
      : [...events].sort((a, b) => a.eventTicker.localeCompare(b.eventTicker));

    groups.push({
      seriesTicker,
      seriesTitle: sampleRow?.series_title || seriesTicker,
      events: sortedEvents,
      marketCount: events.reduce((n, e) => n + e.strikeCount, 0),
      totalVolume: events.reduce((n, e) => n + e.totalVolume, 0),
      liquidCount: events.reduce((n, e) => n + e.liquidCount, 0),
      tickers: events.flatMap((e) => e.tickers),
    });
  }

  return sortParentByVolume
    ? sortByVolumeThenTicker(groups, (g) => g.seriesTicker)
    : [...groups].sort((a, b) => a.seriesTicker.localeCompare(b.seriesTicker));
}
