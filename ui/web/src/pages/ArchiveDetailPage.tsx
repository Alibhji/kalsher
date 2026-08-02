import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchArchiveEventMarkets, type ArchiveMarket } from "../api";
import {
  fetchExperimentsForEvent,
  fetchRoundTrips,
  type ExperimentForEvent,
  type RoundTrip,
} from "../api/trading";
import { AppNav } from "../components/AppNav";
import { ArchiveEventSubsSummary } from "../components/ArchiveEventSubsSummary";
import { ArchiveStrikeTradesTable } from "../components/ArchiveStrikeTradesTable";
import { MarketChart } from "../components/MarketChart";
import { NotificationCenter } from "../components/NotificationCenter";
import { PnlCell } from "../components/PnlCell";
import { PnlChart } from "../components/PnlChart";
import { formatStrike, formatVolume } from "../lib/format";
import {
  archiveMarketVolume,
  filterTripsForEvent,
  formatArchiveWindow,
  kalshiMarketUrl,
  roundTripsToPnlPoints,
  sumNetPnl,
} from "../lib/archivePnl";
import { formatPnl, pnlColorClass, pnlTone } from "../lib/pnl";

const ARCHIVE_DETAIL_EXP_KEY = "kalshi.archiveDetailExperimentId";
const ARCHIVE_EXP_KEY = "kalshi.archiveListExperimentId";
const ARCHIVE_ONLY_TRADED_KEY = "kalshi.archiveOnlyTraded";

type Props = {
  eventTicker: string;
  experimentId?: string;
};

function formatTs(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ArchiveDetailPage({ eventTicker, experimentId }: Props) {
  const [markets, setMarkets] = useState<ArchiveMarket[]>([]);
  const [experiments, setExperiments] = useState<ExperimentForEvent[]>([]);
  const [selectedExpId, setSelectedExpId] = useState<string>("");
  const [roundTrips, setRoundTrips] = useState<RoundTrip[]>([]);
  const [tripsLoading, setTripsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [onlyTraded, setOnlyTraded] = useState<boolean>(() => {
    try {
      return sessionStorage.getItem(ARCHIVE_ONLY_TRADED_KEY) === "1";
    } catch {
      return false;
    }
  });

  const head = markets[0];
  const openTime = head?.open_time ?? null;
  const closeTime = head?.close_time ?? null;

  const loadBase = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [marketRows, expRows] = await Promise.all([
        fetchArchiveEventMarkets(eventTicker),
        fetchExperimentsForEvent(eventTicker),
      ]);
      setMarkets(marketRows);
      setExperiments(expRows);

      const explicitExp = Boolean(experimentId);
      let nextExpId = experimentId ?? "";
      if (!nextExpId) {
        try {
          const fromList = sessionStorage.getItem(ARCHIVE_EXP_KEY);
          if (fromList) nextExpId = fromList;
        } catch {
          // ignore
        }
      }
      if (!nextExpId) {
        try {
          const saved = sessionStorage.getItem(ARCHIVE_DETAIL_EXP_KEY);
          if (saved) nextExpId = saved;
        } catch {
          // ignore
        }
      }
      const known = expRows.some((e) => e.id === nextExpId);
      if (!nextExpId && expRows.length > 0) {
        nextExpId = expRows[0].id;
      } else if (nextExpId && !known && !explicitExp && expRows.length > 0) {
        // Stale session pick that never traded this event — fall back.
        nextExpId = expRows[0].id;
      }
      setSelectedExpId(nextExpId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load archived bet");
    } finally {
      setLoading(false);
    }
  }, [eventTicker, experimentId]);

  useEffect(() => {
    void loadBase();
  }, [loadBase]);

  useEffect(() => {
    if (!selectedExpId) {
      setRoundTrips([]);
      return;
    }
    let cancelled = false;
    setTripsLoading(true);

    void fetchRoundTrips(selectedExpId, undefined, { event_ticker: eventTicker })
      .then((rows) => {
        if (cancelled) return;
        // Server scopes via markets.event_ticker; heuristic is a safety net.
        setRoundTrips(filterTripsForEvent(rows, eventTicker));
      })
      .catch(() => {
        if (!cancelled) setRoundTrips([]);
      })
      .finally(() => {
        if (!cancelled) setTripsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedExpId, eventTicker]);

  useEffect(() => {
    try {
      if (selectedExpId) {
        sessionStorage.setItem(ARCHIVE_DETAIL_EXP_KEY, selectedExpId);
        sessionStorage.setItem(ARCHIVE_EXP_KEY, selectedExpId);
      }
    } catch {
      // ignore
    }
  }, [selectedExpId]);

  useEffect(() => {
    try {
      sessionStorage.setItem(ARCHIVE_ONLY_TRADED_KEY, onlyTraded ? "1" : "0");
    } catch {
      // ignore
    }
  }, [onlyTraded]);

  const closedTrips = useMemo(
    () => roundTrips.filter((r) => r.exit_ts && r.net_pnl != null),
    [roundTrips],
  );
  const totalPnl = useMemo(() => sumNetPnl(roundTrips), [roundTrips]);
  const pnlPoints = useMemo(() => roundTripsToPnlPoints(roundTrips), [roundTrips]);
  const tripsByTicker = useMemo(() => {
    const map = new Map<string, RoundTrip[]>();
    for (const rt of roundTrips) {
      const list = map.get(rt.ticker) ?? [];
      list.push(rt);
      map.set(rt.ticker, list);
    }
    return map;
  }, [roundTrips]);

  const sortedMarkets = useMemo(() => {
    const tradedTickers = new Set(roundTrips.map((rt) => rt.ticker));
    return [...markets].sort((a, b) => {
      const aTraded = tradedTickers.has(a.ticker) ? 1 : 0;
      const bTraded = tradedTickers.has(b.ticker) ? 1 : 0;
      if (aTraded !== bTraded) return bTraded - aTraded;
      const closeDiff = (b.close_time ?? "").localeCompare(a.close_time ?? "");
      if (closeDiff !== 0) return closeDiff;
      const volDiff = archiveMarketVolume(b.volume) - archiveMarketVolume(a.volume);
      if (volDiff !== 0) return volDiff;
      const fa = a.floor_strike ?? 0;
      const fb = b.floor_strike ?? 0;
      if (fa !== fb) return fa - fb;
      return a.ticker.localeCompare(b.ticker);
    });
  }, [markets, roundTrips]);

  const orphanTrips = useMemo(() => {
    const marketTickers = new Set(markets.map((m) => m.ticker));
    return roundTrips.filter((rt) => !marketTickers.has(rt.ticker));
  }, [roundTrips, markets]);

  const visibleMarkets = useMemo(() => {
    if (!onlyTraded || !selectedExpId) return sortedMarkets;
    return sortedMarkets.filter((m) => (tripsByTicker.get(m.ticker)?.length ?? 0) > 0);
  }, [sortedMarkets, onlyTraded, selectedExpId, tripsByTicker]);

  const title = head?.event_title ?? eventTicker;
  const tone = pnlTone(totalPnl);

  return (
    <div className="min-h-screen bg-[#0b1220]">
      <NotificationCenter />
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="sticky top-0 z-40 -mx-4 mb-6 border-b border-ink-800/80 bg-[#0b1220]/95 px-4 py-3 backdrop-blur-sm sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
          <AppNav active="archive" />
        </div>

        <div className="mb-4">
          <a href="#/archive" className="text-xs text-accent hover:underline">
            ← Back to archive
          </a>
        </div>

        {loading ? <p className="text-sm text-ink-500">Loading…</p> : null}
        {error ? <p className="text-sm text-red-400">{error}</p> : null}

        {!loading && !error ? (
          <>
            <header className="mb-6 animate-fade-in">
              <p className="text-xs font-medium uppercase tracking-[0.2em] text-accent">Archived bet</p>
              <h1 className="mt-1 text-2xl font-semibold text-ink-50">{title}</h1>
              <p className="mt-1 font-mono text-xs text-ink-500">{eventTicker}</p>
              <p className="mt-2 text-sm text-ink-400">
                {formatArchiveWindow(openTime, closeTime)} · {visibleMarkets.length}
                {onlyTraded && selectedExpId ? " traded" : " liquid"} strike
                {visibleMarkets.length === 1 ? "" : "s"}
                {onlyTraded && selectedExpId && visibleMarkets.length !== sortedMarkets.length
                  ? ` (${sortedMarkets.length} total)`
                  : ""}
              </p>
            </header>

            {experiments.length > 0 || selectedExpId ? (
              <div className="mb-6 flex flex-wrap items-end gap-4">
                <label className="flex flex-col gap-1 text-xs text-ink-500">
                  Experiment
                  <select
                    value={selectedExpId}
                    onChange={(e) => setSelectedExpId(e.target.value)}
                    className="min-w-[260px] rounded border border-ink-700 bg-ink-950 px-3 py-2 text-sm text-ink-200"
                  >
                    {!selectedExpId ? <option value="">— select —</option> : null}
                    {selectedExpId &&
                    !experiments.some((exp) => exp.id === selectedExpId) ? (
                      <option value={selectedExpId}>From Archive list</option>
                    ) : null}
                    {experiments.map((exp) => (
                      <option key={exp.id} value={exp.id}>
                        {exp.name} ({exp.mode}) · {exp.trade_count} trade
                        {exp.trade_count === 1 ? "" : "s"} · {formatPnl(Number(exp.net_pnl))}
                      </option>
                    ))}
                  </select>
                </label>
                <label
                  className={`flex cursor-pointer items-center gap-2 self-end pb-2 text-sm ${
                    selectedExpId ? "text-ink-300" : "cursor-not-allowed text-ink-600"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={onlyTraded && Boolean(selectedExpId)}
                    disabled={!selectedExpId}
                    onChange={(e) => setOnlyTraded(e.target.checked)}
                    className="rounded border-ink-600 bg-ink-950 text-accent focus:ring-accent/40 disabled:opacity-40"
                  />
                  Only strikes with trades
                </label>
                {selectedExpId && closedTrips.length > 0 ? (
                  <div className="rounded-lg border border-ink-800 bg-ink-900/60 px-4 py-3">
                    <p className="text-xs text-ink-500">Total net P/L this window</p>
                    <div className={`mt-1 font-mono text-lg ${pnlColorClass(tone)}`}>
                      {closedTrips.length} closed · <PnlCell usd={totalPnl} showLabel />
                    </div>
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="mb-6 text-sm text-ink-500">
                No trades recorded for this window. Pick an experiment on the Archive list first,
                then open this bet again.
              </p>
            )}

            {selectedExpId && tripsLoading ? (
              <p className="mb-4 text-sm text-ink-500">Loading your trades…</p>
            ) : null}

            {selectedExpId && roundTrips.length > 0 ? (
              <ArchiveEventSubsSummary
                eventTicker={eventTicker}
                markets={visibleMarkets}
                tripsByTicker={tripsByTicker}
              />
            ) : null}

            <section className="mb-8">
              <h2 className="mb-3 text-lg font-semibold text-ink-100">Market signal</h2>
              <p className="mb-4 text-sm text-ink-500">
                Historical price, flow, and rules for each strike in this window.
              </p>
              {visibleMarkets.length === 0 && !tripsLoading ? (
                <p className="text-sm text-ink-500">
                  {onlyTraded
                    ? "No strikes with trades for this experiment. Uncheck “Only strikes with trades” to see all charts."
                    : "No liquid strikes loaded for this window."}
                </p>
              ) : tripsLoading && roundTrips.length === 0 ? (
                <p className="text-sm text-ink-500">Loading your trades…</p>
              ) : (
              <div className="space-y-6">
                {visibleMarkets.map((market) => {
                  const strikeTrips = tripsByTicker.get(market.ticker) ?? [];
                  const strikePnl = sumNetPnl(strikeTrips);
                  const hasTrades = strikeTrips.length > 0;
                  return (
                  <div
                    key={market.ticker}
                    className="rounded-lg border border-ink-800 bg-ink-950/40 p-4"
                  >
                    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                      <div>
                        <div className="font-mono text-sm text-ink-200">{market.ticker}</div>
                        {market.title ? (
                          <div className="text-xs text-ink-500">{market.title}</div>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap items-center gap-3 text-xs">
                        <span className="text-ink-400">
                          Strike {formatStrike(market.floor_strike, market.cap_strike)}
                        </span>
                        <span className="font-mono text-ink-300">Vol {formatVolume(market.volume)}</span>
                        {hasTrades ? (
                          <span className={`font-mono ${pnlColorClass(pnlTone(strikePnl))}`}>
                            {formatPnl(strikePnl)}
                          </span>
                        ) : null}
                      </div>
                    </div>
                    <MarketChart
                      ticker={market.ticker}
                      label={market.title ?? market.ticker}
                      openTime={market.open_time}
                      closeTime={market.close_time}
                      kalshiUrl={kalshiMarketUrl(market.ticker, market)}
                      chartHeight={240}
                      roundTrips={strikeTrips}
                      tradeMarkerLabels="in-out"
                    />
                    <ArchiveStrikeTradesTable trips={strikeTrips} />
                  </div>
                  );
                })}
              </div>
              )}
            </section>

            {orphanTrips.length > 0 ? (
              <section className="mb-8">
                <h2 className="mb-2 text-sm font-semibold text-amber-200">Trades outside archived strikes</h2>
                <p className="mb-3 text-xs text-ink-500">
                  These fills match this window but the strike is not in the archived liquid set.
                </p>
                <ArchiveStrikeTradesTable trips={orphanTrips} />
              </section>
            ) : null}

            {closedTrips.length > 0 ? (
              <>
                <section className="mb-8">
                  <h2 className="mb-3 text-lg font-semibold text-ink-100">P/L over time</h2>
                  <div className="rounded-lg border border-ink-800 bg-ink-950/40 p-2">
                    <PnlChart points={pnlPoints} />
                  </div>
                </section>

                <section>
                  <h2 className="mb-3 text-lg font-semibold text-ink-100">Your trades</h2>
                  <div className="overflow-x-auto rounded-lg border border-ink-800">
                    <table className="min-w-full text-left text-sm">
                      <thead className="bg-ink-900/80 text-xs uppercase tracking-wide text-ink-500">
                        <tr>
                          <th className="px-4 py-3 font-medium">Ticker</th>
                          <th className="px-4 py-3 font-medium">Side</th>
                          <th className="px-4 py-3 font-medium">Qty</th>
                          <th className="px-4 py-3 font-medium">Entry</th>
                          <th className="px-4 py-3 font-medium">Exit</th>
                          <th className="px-4 py-3 font-medium">Net P/L</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-ink-800/80">
                        {closedTrips.map((r) => {
                          const net = r.net_pnl != null ? Number(r.net_pnl) : 0;
                          const pct = r.pnl_pct != null ? Number(r.pnl_pct) : null;
                          return (
                            <tr key={r.id} className="bg-ink-950/40 hover:bg-ink-900/60">
                              <td className="px-4 py-2.5 font-mono text-ink-200">{r.ticker}</td>
                              <td className="px-4 py-2.5 text-xs uppercase text-ink-400">{r.side}</td>
                              <td className="px-4 py-2.5 font-mono text-ink-200">{r.qty}</td>
                              <td className="px-4 py-2.5 font-mono text-xs text-ink-400">
                                {Math.round(Number(r.entry_price) * 100)}¢ · {formatTs(r.entry_ts)}
                              </td>
                              <td className="px-4 py-2.5 font-mono text-xs text-ink-400">
                                {r.exit_price != null
                                  ? `${Math.round(Number(r.exit_price) * 100)}¢ · `
                                  : ""}
                                {r.exit_ts ? formatTs(r.exit_ts) : "—"}
                              </td>
                              <td className="px-4 py-2.5">
                                <PnlCell usd={net} pct={pct} showLabel />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                      <tfoot>
                        <tr className="border-t border-ink-700 bg-ink-900/50">
                          <td
                            colSpan={5}
                            className="px-4 py-3 text-right text-xs font-medium uppercase text-ink-500"
                          >
                            Total net P/L
                          </td>
                          <td className="px-4 py-3">
                            <PnlCell usd={totalPnl} showLabel />
                          </td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                </section>
              </>
            ) : selectedExpId && !tripsLoading ? (
              <p className="text-sm text-ink-500">
                No closed trades for this window in the selected experiment.
              </p>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
