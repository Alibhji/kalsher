import { Fragment, useEffect, useMemo, useState } from "react";
import type { MarketRow } from "../api";
import { groupMarkets, type EventGroup, type SeriesGroup } from "../lib/groupMarkets";
import { marketHasLiquidity } from "../lib/filters";
import { useMarketRow, useLiveGroupVolume } from "../store/useMarketStore";
import {
  countdownTone,
  formatCents,
  formatCountdown,
  formatStrike,
  formatVolume,
} from "../lib/format";
import { KalshiLink } from "./KalshiLink";
import { MarketChart } from "./MarketChart";

type Props = {
  markets: MarketRow[];
  nowMs: number;
  sortSubByVolume?: boolean;
  sortParentByVolume?: boolean;
  onToggleSortParentByVolume?: () => void;
  hideNoLiquidity?: boolean;
  filtersActive?: boolean;
};

function ParentVolumeSortIcon({ active }: { active: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className={`h-3.5 w-3.5 ${active ? "text-accent" : "text-ink-500"}`}
      fill="currentColor"
    >
      <rect x="2" y="2.5" width="12" height="1.5" rx="0.5" opacity={active ? 1 : 0.45} />
      <rect x="3.5" y="6" width="9" height="1.5" rx="0.5" opacity={active ? 0.85 : 0.35} />
      <rect x="5" y="9.5" width="6" height="1.5" rx="0.5" opacity={active ? 0.7 : 0.25} />
      <path d="M8 12.5v2M6.25 13.25 8 15.25l1.75-2" opacity={active ? 0.95 : 0.3} stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function volumeLabel(total: number): string {
  return formatVolume(String(total));
}

function toneClass(tone: "normal" | "warn" | "urgent"): string {
  if (tone === "urgent") return "text-red-400";
  if (tone === "warn") return "text-amber-400";
  return "text-ink-300";
}

function collapseKey(prefix: string, id: string): string {
  return `${prefix}:${id}`;
}

export function MarketsGrouped({
  markets,
  nowMs,
  sortSubByVolume = true,
  sortParentByVolume = false,
  onToggleSortParentByVolume,
  hideNoLiquidity = true,
  filtersActive = false,
}: Props) {
  const groups = useMemo(
    () =>
      groupMarkets(markets, {
        sortSubByVolume,
        sortParentByVolume,
        hideNoLiquidity,
      }),
    [markets, sortSubByVolume, sortParentByVolume, hideNoLiquidity],
  );
  const [visible, setVisible] = useState(false);
  const [expandedSeries, setExpandedSeries] = useState<Set<string>>(() => new Set());
  const [expandedEvents, setExpandedEvents] = useState<Set<string>>(() => new Set());
  const [expandedChart, setExpandedChart] = useState<string | null>(null);
  const [groupsInitialized, setGroupsInitialized] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(id);
  }, []);

  useEffect(() => {
    if (!groupsInitialized && groups.length > 0) {
      // Show series + event headers; keep strike sub-rows collapsed until user expands.
      setExpandedSeries(new Set(groups.map((g) => g.seriesTicker)));
      setGroupsInitialized(true);
    }

    // Keep user-expanded events across polls; drop keys that no longer exist.
    setExpandedEvents((prev) => {
      const validKeys = new Set(
        groups.flatMap((g) => g.events.map((e) => collapseKey(g.seriesTicker, e.eventTicker))),
      );
      const next = new Set<string>();
      for (const key of prev) {
        if (validKeys.has(key)) next.add(key);
      }
      if (next.size === prev.size && [...next].every((key) => prev.has(key))) {
        return prev;
      }
      return next;
    });
  }, [groups, groupsInitialized]);

  function toggleSeries(seriesTicker: string) {
    const series = groups.find((g) => g.seriesTicker === seriesTicker);
    if (!series) return;

    setExpandedSeries((prevSeries) => {
      const expanding = !prevSeries.has(seriesTicker);
      const nextSeries = new Set(prevSeries);
      if (expanding) nextSeries.add(seriesTicker);
      else nextSeries.delete(seriesTicker);

      setExpandedEvents((prevEvents) => {
        const nextEvents = new Set(prevEvents);
        for (const event of series.events) {
          const key = collapseKey(seriesTicker, event.eventTicker);
          if (expanding) nextEvents.add(key);
          else nextEvents.delete(key);
        }
        return nextEvents;
      });

      if (!expanding) {
        const tickersInSeries = new Set(
          series.events.flatMap((event) => event.markets.map((market) => market.ticker)),
        );
        setExpandedChart((prev) => (prev && tickersInSeries.has(prev) ? null : prev));
      }

      return nextSeries;
    });
  }

  function toggleEvent(seriesTicker: string, eventTicker: string) {
    const key = collapseKey(seriesTicker, eventTicker);
    setExpandedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  if (markets.length === 0) {
    return (
      <div className="rounded-lg border border-ink-800 bg-ink-900/80 px-6 py-16 text-center animate-fade-in">
        <p className="text-lg font-medium text-ink-100">
          {filtersActive ? "No markets match your filters" : "No active markets"}
        </p>
        <p className="mt-2 text-sm text-ink-500">
          {filtersActive
            ? "Try clearing search or turning off “Hide no liquidity”."
            : "The fetcher universe is empty right now."}
        </p>
      </div>
    );
  }

  return (
    <div
      className={`overflow-hidden rounded-lg border border-ink-800 bg-ink-900/90 shadow-lg shadow-black/20 transition-opacity duration-300 ${
        visible ? "opacity-100 animate-fade-in" : "opacity-0"
      }`}
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[960px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-ink-800 bg-ink-950/90 text-left text-xs uppercase tracking-wide text-ink-500">
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 font-medium">Group / bet</th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 font-medium">Strike</th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 text-right font-medium">YES</th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 text-right font-medium">NO</th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 text-right font-medium">
                <button
                  type="button"
                  onClick={onToggleSortParentByVolume}
                  disabled={!onToggleSortParentByVolume}
                  title={
                    sortParentByVolume
                      ? "Parent groups sorted by total volume (click for A–Z)"
                      : "Sort series and events by total volume"
                  }
                  aria-pressed={sortParentByVolume}
                  className={`inline-flex items-center justify-end gap-1.5 rounded px-1 py-0.5 transition-colors ${
                    onToggleSortParentByVolume
                      ? sortParentByVolume
                        ? "text-accent hover:text-accent/90"
                        : "text-ink-500 hover:text-ink-300"
                      : "cursor-default text-ink-500"
                  }`}
                >
                  <span>Volume</span>
                  {onToggleSortParentByVolume ? <ParentVolumeSortIcon active={sortParentByVolume} /> : null}
                </button>
              </th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 text-right font-medium">Expires</th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 font-medium">Links</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((series) => (
              <SeriesSection
                key={series.seriesTicker}
                series={series}
                nowMs={nowMs}
                expanded={expandedSeries.has(series.seriesTicker)}
                expandedEvents={expandedEvents}
                expandedChart={expandedChart}
                onToggleSeries={() => toggleSeries(series.seriesTicker)}
                onToggleEvent={(eventTicker) => toggleEvent(series.seriesTicker, eventTicker)}
                onToggleChart={(ticker) => setExpandedChart(expandedChart === ticker ? null : ticker)}
              />
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-ink-800 px-4 py-2 text-xs text-ink-500">
        Grouped like Kalshi crypto calendar — series → event → strike rows. Expanding a series
        expands all its events and strikes; collapsing it hides them all.
      </p>
    </div>
  );
}

type SeriesSectionProps = {
  series: SeriesGroup;
  nowMs: number;
  expanded: boolean;
  expandedEvents: Set<string>;
  expandedChart: string | null;
  onToggleSeries: () => void;
  onToggleEvent: (eventTicker: string) => void;
  onToggleChart: (ticker: string) => void;
};

function SeriesSection({
  series,
  nowMs,
  expanded,
  expandedEvents,
  expandedChart,
  onToggleSeries,
  onToggleEvent,
  onToggleChart,
}: SeriesSectionProps) {
  const liveVolume = useLiveGroupVolume(series.tickers);

  return (
    <>
      <tr
        className="cursor-pointer border-b border-ink-800 bg-ink-950/80 hover:bg-ink-900"
        onClick={onToggleSeries}
      >
        <td colSpan={7} className="px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-3">
              <span className="text-ink-500">{expanded ? "▼" : "▶"}</span>
              <span className="font-semibold text-ink-50">{series.seriesTicker}</span>
              <span className="text-ink-400">{series.seriesTitle}</span>
              <span className="rounded-full border border-ink-700 px-2 py-0.5 text-xs text-ink-500">
                {series.events.length} event{series.events.length === 1 ? "" : "s"} · {series.marketCount}{" "}
                bet{series.marketCount === 1 ? "" : "s"}
              </span>
            </div>
            <span className="font-mono text-sm text-ink-300">
              {volumeLabel(liveVolume)} vol
            </span>
          </div>
        </td>
      </tr>
      {expanded
        ? series.events.map((event) => (
            <EventSection
              key={event.eventTicker}
              seriesTicker={series.seriesTicker}
              event={event}
              nowMs={nowMs}
              expanded={expandedEvents.has(collapseKey(series.seriesTicker, event.eventTicker))}
              expandedChart={expandedChart}
              onToggleEvent={() => onToggleEvent(event.eventTicker)}
              onToggleChart={onToggleChart}
            />
          ))
        : null}
    </>
  );
}

type EventSectionProps = {
  seriesTicker: string;
  event: EventGroup;
  nowMs: number;
  expanded: boolean;
  expandedChart: string | null;
  onToggleEvent: () => void;
  onToggleChart: (ticker: string) => void;
};

function EventSection({
  seriesTicker,
  event,
  nowMs,
  expanded,
  expandedChart,
  onToggleEvent,
  onToggleChart,
}: EventSectionProps) {
  const tone = countdownTone(event.secondsToClose, nowMs, event.closeTime);
  const illiquidCount = event.strikeCount - event.liquidCount;
  const noLiquidity = event.liquidCount === 0;
  const liveVolume = useLiveGroupVolume(event.tickers);

  return (
    <>
      <tr
        className="cursor-pointer border-b border-ink-800/80 bg-ink-900/60 hover:bg-accent/5"
        onClick={onToggleEvent}
      >
        <td colSpan={4} className="px-4 py-2.5 pl-10">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-ink-600">{expanded ? "▼" : "▶"}</span>
            <span className="font-medium text-ink-100">{event.eventTitle}</span>
            <span className="font-mono text-xs text-ink-500">{event.eventTicker}</span>
            {event.isLive ? (
              <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent">
                live
              </span>
            ) : null}
            <span className="text-xs text-ink-500">
              {event.strikeCount} strike{event.strikeCount === 1 ? "" : "s"}
            </span>
            {noLiquidity ? (
              <span className="rounded border border-ink-700 bg-ink-950/80 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-500">
                no liquidity
              </span>
            ) : illiquidCount > 0 ? (
              <span className="rounded border border-ink-700 bg-ink-950/80 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-500">
                {illiquidCount} no liq.
              </span>
            ) : null}
          </div>
        </td>
        <td className="px-4 py-2.5 text-right font-mono text-sm text-ink-300">
          {volumeLabel(liveVolume)}
        </td>
        <td className={`px-4 py-2.5 text-right font-mono text-sm ${toneClass(tone)}`}>
          {formatCountdown(event.secondsToClose, nowMs, event.closeTime)}
        </td>
        <td className="px-4 py-2.5">
          {event.eventKalshiUrl ? <KalshiLink url={event.eventKalshiUrl} /> : null}
        </td>
      </tr>
      {expanded
        ? event.markets.map((market, i) => (
            <MarketRowView
              key={market.ticker}
              market={market}
              nowMs={nowMs}
              stripe={i % 2 === 0}
              expandedChart={expandedChart === market.ticker}
              onToggleChart={() => onToggleChart(market.ticker)}
            />
          ))
        : null}
    </>
  );
}

type MarketRowViewProps = {
  market: MarketRow;
  nowMs: number;
  stripe: boolean;
  expandedChart: boolean;
  onToggleChart: () => void;
};

function LiveQuoteCells({ live }: { live: MarketRow }) {
  return (
    <>
      <td className="px-4 py-2 text-right font-mono text-emerald-400/90">
        {formatCents(live.yes_bid_cents, live.yes_ask_cents)}
      </td>
      <td className="px-4 py-2 text-right font-mono text-red-400/90">
        {formatCents(live.no_bid_cents, live.no_ask_cents)}
      </td>
      <td className="px-4 py-2 text-right font-mono text-ink-200">{formatVolume(live.volume)}</td>
    </>
  );
}

function MarketRowView({ market, nowMs, stripe, expandedChart, onToggleChart }: MarketRowViewProps) {
  const live = useMarketRow(market.ticker) ?? market;
  const label = live.title || live.event_title || live.ticker;
  const tone = countdownTone(live.seconds_to_close, nowMs, live.close_time);
  const liquid = marketHasLiquidity(live);

  return (
    <Fragment>
      <tr
        onClick={liquid ? onToggleChart : undefined}
        aria-disabled={!liquid}
        className={`border-b border-ink-800/60 transition-colors ${
          !liquid
            ? "cursor-not-allowed bg-ink-950/50 opacity-45"
            : expandedChart
              ? "cursor-pointer bg-accent/10 hover:bg-accent/10"
              : `cursor-pointer hover:bg-accent/10 ${stripe ? "bg-ink-900/40" : "bg-ink-950/30"}`
        }`}
      >
        <td className="px-4 py-2 pl-16">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-ink-400">{live.ticker}</span>
            {!liquid ? (
              <span className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-500">
                no liquidity
              </span>
            ) : null}
          </div>
          {live.title && live.title !== live.event_title ? (
            <div className="truncate text-xs text-ink-500">{live.title}</div>
          ) : null}
        </td>
        <td className="px-4 py-2 font-mono text-xs text-ink-300">
          {formatStrike(live.floor_strike, live.cap_strike, live.strike_type)}
        </td>
        <LiveQuoteCells live={live} />
        <td className={`px-4 py-2 text-right font-mono text-sm ${toneClass(tone)}`}>
          {formatCountdown(live.seconds_to_close, nowMs, live.close_time)}
        </td>
        <td className="px-4 py-2">
          <KalshiLink url={live.kalshi_url} />
        </td>
      </tr>
      {expandedChart && liquid ? (
        <tr className="bg-ink-950">
          <td colSpan={7} className="p-0">
            <MarketChart
              ticker={live.ticker}
              label={label}
              openTime={live.open_time}
              closeTime={live.close_time}
              kalshiUrl={live.kalshi_url}
            />
          </td>
        </tr>
      ) : null}
    </Fragment>
  );
}
