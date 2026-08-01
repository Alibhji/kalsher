import { Fragment, useEffect, useState } from "react";
import {
  fetchArchiveEventMarkets,
  fetchArchiveTree,
  type ArchiveMarket,
  type ArchiveSeries,
} from "../api";
import { formatStrike, formatVolume } from "../lib/format";
import { marketStore } from "../store/marketStore";

function collapseKey(...parts: string[]): string {
  return parts.join(":");
}

function formatWhen(openTime: string | null, closeTime: string | null): string {
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

function volumeLabel(total: number): string {
  return formatVolume(String(total));
}

export function ArchivePanel() {
  const [open, setOpen] = useState(false);
  const [tree, setTree] = useState<ArchiveSeries[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [expandedSeries, setExpandedSeries] = useState<Set<string>>(() => new Set());
  const [expandedBets, setExpandedBets] = useState<Set<string>>(() => new Set());
  const [expandedPeriods, setExpandedPeriods] = useState<Set<string>>(() => new Set());
  const [periodMarkets, setPeriodMarkets] = useState<Record<string, ArchiveMarket[]>>({});
  const [loadingPeriod, setLoadingPeriod] = useState<string | null>(null);
  const [archiveStale, setArchiveStale] = useState(false);

  async function refreshArchive() {
    setState("loading");
    setError(null);
    try {
      const rows = await fetchArchiveTree(undefined, 40);
      setTree(rows);
      setExpandedSeries(new Set(rows.map((s) => s.series_ticker)));
      setArchiveStale(false);
      setState("ready");
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : "Failed to load archive");
    }
  }

  async function loadArchive() {
    setOpen(true);
    if (state !== "ready" || archiveStale) {
      await refreshArchive();
    }
  }

  useEffect(() => {
    return marketStore.subscribeArchive(() => {
      setArchiveStale(true);
      if (open) void refreshArchive();
    });
  }, [open]);

  function toggleSeries(ticker: string, bets: ArchiveSeries["bets"]) {
    const expanding = !expandedSeries.has(ticker);
    setExpandedSeries((prev) => {
      const next = new Set(prev);
      if (expanding) next.add(ticker);
      else next.delete(ticker);
      return next;
    });

    setExpandedBets((prev) => {
      const next = new Set(prev);
      for (const bet of bets) {
        const key = collapseKey(ticker, bet.bet_name);
        if (expanding) next.add(key);
        else next.delete(key);
      }
      return next;
    });

    if (!expanding) {
      setExpandedPeriods((prev) => {
        const next = new Set(prev);
        for (const bet of bets) {
          for (const period of bet.periods) {
            next.delete(collapseKey(ticker, bet.bet_name, period.event_ticker));
          }
        }
        return next;
      });
    }
  }

  function toggleBet(seriesTicker: string, betName: string) {
    const key = collapseKey(seriesTicker, betName);
    setExpandedBets((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function togglePeriod(seriesTicker: string, betName: string, eventTicker: string) {
    const key = collapseKey(seriesTicker, betName, eventTicker);
    const expanding = !expandedPeriods.has(key);
    setExpandedPeriods((prev) => {
      const next = new Set(prev);
      if (expanding) next.add(key);
      else next.delete(key);
      return next;
    });

    if (!expanding || periodMarkets[eventTicker]) return;

    setLoadingPeriod(eventTicker);
    try {
      const markets = await fetchArchiveEventMarkets(eventTicker);
      setPeriodMarkets((prev) => ({ ...prev, [eventTicker]: markets }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load archived strikes");
    } finally {
      setLoadingPeriod(null);
    }
  }

  return (
    <section className="mt-8 animate-fade-in">
      <button
        type="button"
        onClick={() => (open ? setOpen(false) : loadArchive())}
        className="flex w-full items-center justify-between rounded-lg border border-ink-800 bg-ink-950/60 px-4 py-3 text-left text-sm text-ink-300 hover:border-ink-700"
      >
        <span>
          <span className="font-medium text-ink-100">Archive</span>
          <span className="ml-2 text-ink-500">
            Liquid bets only — grouped by series, bet name, then time window
          </span>
        </span>
        <span className="text-ink-500">{open ? "▼" : "▶"}</span>
      </button>

      {open ? (
        <div className="mt-2 overflow-hidden rounded-lg border border-ink-800 bg-ink-950/40">
          {state === "loading" ? <p className="p-4 text-sm text-ink-500">Loading archive…</p> : null}
          {state === "error" ? <p className="p-4 text-sm text-red-400">{error}</p> : null}
          {state === "ready" && tree.length === 0 ? (
            <p className="p-4 text-sm text-ink-500">No archived liquid bets yet.</p>
          ) : null}
          {state === "ready" && tree.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-ink-800 bg-ink-950/90 text-left text-xs uppercase tracking-wide text-ink-500">
                    <th className="px-4 py-3 font-medium">Series / bet / window</th>
                    <th className="px-4 py-3 text-right font-medium">Volume</th>
                    <th className="px-4 py-3 text-right font-medium">Strikes</th>
                    <th className="px-4 py-3 text-right font-medium">Closed</th>
                  </tr>
                </thead>
                <tbody>
                  {tree.map((series) => (
                    <Fragment key={series.series_ticker}>
                      <tr
                        className="cursor-pointer border-b border-ink-800 bg-ink-950/80 hover:bg-ink-900"
                        onClick={() => toggleSeries(series.series_ticker, series.bets)}
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="text-ink-500">
                              {expandedSeries.has(series.series_ticker) ? "▼" : "▶"}
                            </span>
                            <span className="font-semibold text-ink-50">{series.series_ticker}</span>
                            <span className="text-ink-400">{series.series_title}</span>
                            <span className="text-xs text-ink-500">
                              {series.period_count} window{series.period_count === 1 ? "" : "s"}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-ink-300">
                          {volumeLabel(series.total_volume)}
                        </td>
                        <td className="px-4 py-3 text-right text-ink-500">—</td>
                        <td className="px-4 py-3 text-right text-ink-500">—</td>
                      </tr>

                      {expandedSeries.has(series.series_ticker)
                        ? series.bets.map((bet) => {
                            const betKey = collapseKey(series.series_ticker, bet.bet_name);
                            return (
                              <Fragment key={betKey}>
                                <tr
                                  className="cursor-pointer border-b border-ink-800/80 bg-ink-900/50 hover:bg-accent/5"
                                  onClick={() => toggleBet(series.series_ticker, bet.bet_name)}
                                >
                                  <td className="px-4 py-2.5 pl-10">
                                    <div className="flex items-center gap-2">
                                      <span className="text-ink-600">
                                        {expandedBets.has(betKey) ? "▼" : "▶"}
                                      </span>
                                      <span className="font-medium text-ink-100">{bet.bet_name}</span>
                                      <span className="text-xs text-ink-500">
                                        {bet.period_count} period{bet.period_count === 1 ? "" : "s"}
                                      </span>
                                    </div>
                                  </td>
                                  <td className="px-4 py-2.5 text-right font-mono text-ink-300">
                                    {volumeLabel(bet.total_volume)}
                                  </td>
                                  <td className="px-4 py-2.5 text-right text-ink-500">—</td>
                                  <td className="px-4 py-2.5 text-right text-ink-500">—</td>
                                </tr>

                                {expandedBets.has(betKey)
                                  ? bet.periods.map((period) => {
                                      const periodKey = collapseKey(
                                        series.series_ticker,
                                        bet.bet_name,
                                        period.event_ticker,
                                      );
                                      const markets = periodMarkets[period.event_ticker];
                                      return (
                                        <Fragment key={periodKey}>
                                          <tr
                                            className="cursor-pointer border-b border-ink-800/70 bg-ink-900/30 hover:bg-accent/5"
                                            onClick={() =>
                                              togglePeriod(
                                                series.series_ticker,
                                                bet.bet_name,
                                                period.event_ticker,
                                              )
                                            }
                                          >
                                            <td className="px-4 py-2 pl-16">
                                              <div className="flex flex-wrap items-center gap-2">
                                                <span className="text-ink-600">
                                                  {expandedPeriods.has(periodKey) ? "▼" : "▶"}
                                                </span>
                                                <span className="text-ink-200">
                                                  {period.event_title ?? period.event_ticker}
                                                </span>
                                                <span className="font-mono text-xs text-ink-500">
                                                  {period.event_ticker}
                                                </span>
                                              </div>
                                            </td>
                                            <td className="px-4 py-2 text-right font-mono text-ink-300">
                                              {volumeLabel(period.total_volume)}
                                            </td>
                                            <td className="px-4 py-2 text-right font-mono text-ink-400">
                                              {period.liquid_count}
                                            </td>
                                            <td className="px-4 py-2 text-right font-mono text-xs text-ink-400">
                                              {formatWhen(period.open_time, period.close_time)}
                                            </td>
                                          </tr>

                                          {expandedPeriods.has(periodKey) ? (
                                            loadingPeriod === period.event_ticker && !markets ? (
                                              <tr className="bg-ink-950/40">
                                                <td colSpan={4} className="px-4 py-2 pl-20 text-xs text-ink-500">
                                                  Loading strikes…
                                                </td>
                                              </tr>
                                            ) : markets && markets.length === 0 ? (
                                              <tr className="bg-ink-950/40">
                                                <td colSpan={4} className="px-4 py-2 pl-20 text-xs text-ink-500">
                                                  No liquid strikes recorded for this window.
                                                </td>
                                              </tr>
                                            ) : (
                                              markets?.map((market) => (
                                                <tr
                                                  key={market.ticker}
                                                  className="border-b border-ink-800/50 bg-ink-950/30"
                                                >
                                                  <td className="px-4 py-2 pl-20">
                                                    <div className="font-mono text-xs text-ink-400">
                                                      {market.ticker}
                                                    </div>
                                                    {market.title ? (
                                                      <div className="truncate text-xs text-ink-500">
                                                        {market.title}
                                                      </div>
                                                    ) : null}
                                                  </td>
                                                  <td className="px-4 py-2 text-right font-mono text-ink-300">
                                                    {formatVolume(market.volume)}
                                                  </td>
                                                  <td className="px-4 py-2 text-right font-mono text-xs text-ink-400">
                                                    {formatStrike(
                                                      market.floor_strike,
                                                      market.cap_strike,
                                                      market.strike_type,
                                                    )}
                                                  </td>
                                                  <td className="px-4 py-2 text-right font-mono text-xs text-ink-500">
                                                    {market.close_time
                                                      ? new Date(market.close_time).toLocaleString()
                                                      : "—"}
                                                  </td>
                                                </tr>
                                              ))
                                            )
                                          ) : null}
                                        </Fragment>
                                      );
                                    })
                                  : null}
                              </Fragment>
                            );
                          })
                        : null}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
