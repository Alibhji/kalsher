import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchExperiment,
  fetchFills,
  fetchPeriodSummary,
  fetchPnlSeries,
  fetchProfile,
  fetchRoundTrips,
  fetchStats,
  patchExperiment,
  deleteExperiment,
  syncKalshiHistory,
  tradeLabel,
  type Experiment,
  type ExperimentStats,
  type Fill,
  type HistoryQuery,
  type PeriodSummary,
  type PnlPoint,
  type Profile,
  type RoundTrip,
} from "../api/trading";
import { PnlCell } from "../components/PnlCell";
import { TagEditor } from "../components/TagList";
import { AppNav } from "../components/AppNav";
import { NotificationCenter } from "../components/NotificationCenter";
import { PnlChart } from "../components/PnlChart";
import { formatUsd } from "../lib/format";
import { experimentReturn, formatPnl, formatPnlPct, pnlColorClass, pnlTone } from "../lib/pnl";

type Props = {
  experimentId: string;
};

function startOfCurrentMonthLocal(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0, 0);
}

function toDateInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function startOfLocalDayIso(dateStr: string): string | undefined {
  if (!dateStr) return undefined;
  const [y, m, d] = dateStr.split("-").map(Number);
  if (!y || !m || !d) return undefined;
  return new Date(y, m - 1, d, 0, 0, 0, 0).toISOString();
}

function endOfLocalDayIso(dateStr: string): string | undefined {
  if (!dateStr) return undefined;
  const [y, m, d] = dateStr.split("-").map(Number);
  if (!y || !m || !d) return undefined;
  return new Date(y, m - 1, d, 23, 59, 59, 999).toISOString();
}

function queryFromDateRange(startDate: string, endDate: string): HistoryQuery {
  return {
    start: startOfLocalDayIso(startDate),
    end: endOfLocalDayIso(endDate),
    source: "auto",
  };
}

export function ExperimentDetailPage({ experimentId }: Props) {
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [stats, setStats] = useState<ExperimentStats | null>(null);
  const [period, setPeriod] = useState<PeriodSummary | null>(null);
  const [pnlPoints, setPnlPoints] = useState<PnlPoint[]>([]);
  const [pnlSource, setPnlSource] = useState<string>("");
  const [fills, setFills] = useState<Fill[]>([]);
  const [roundTrips, setRoundTrips] = useState<RoundTrip[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [kalshiInfo, setKalshiInfo] = useState<string | null>(null);
  const [savingTags, setSavingTags] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [startInput, setStartInput] = useState(() => toDateInput(startOfCurrentMonthLocal()));
  const [endInput, setEndInput] = useState(() => toDateInput(new Date()));
  const [rangeReady, setRangeReady] = useState(false);
  const applyTimerRef = useRef<number | null>(null);

  const historyQuery = useMemo<HistoryQuery>(
    () => queryFromDateRange(startInput, endInput),
    [startInput, endInput],
  );

  const loadData = useCallback(async (query: HistoryQuery) => {
    setLoading(true);
    setError(null);
    try {
      const [exp, prof, st, periodSummary, pnlSeries, fillRows, rtRows] = await Promise.all([
        fetchExperiment(experimentId),
        fetchProfile(experimentId),
        fetchStats(experimentId),
        fetchPeriodSummary(experimentId, query),
        fetchPnlSeries(experimentId, query),
        fetchFills(experimentId, undefined, query),
        fetchRoundTrips(experimentId, undefined, query),
      ]);
      setExperiment(exp);
      setProfile(prof);
      setStats(st);
      setPeriod(periodSummary);
      setPnlPoints(pnlSeries.points);
      setPnlSource(pnlSeries.source);
      setFills(fillRows);
      setRoundTrips(rtRows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load experiment");
    } finally {
      setLoading(false);
    }
  }, [experimentId]);

  const applyRange = useCallback(
    (query: HistoryQuery, immediate = false) => {
      if (!rangeReady) return;
      if (applyTimerRef.current != null) {
        window.clearTimeout(applyTimerRef.current);
        applyTimerRef.current = null;
      }
      const run = () => {
        void loadData(query);
      };
      if (immediate) {
        run();
      } else {
        applyTimerRef.current = window.setTimeout(run, 300);
      }
    },
    [rangeReady, loadData],
  );

  useEffect(() => {
    let cancelled = false;
    async function init() {
      setRangeReady(false);
      const exp = await fetchExperiment(experimentId);
      if (cancelled) return;
      const start = toDateInput(startOfCurrentMonthLocal());
      const end = toDateInput(new Date());
      setEndInput(end);
      setStartInput(start);
      if (exp.mode === "live") {
        try {
          const res = await syncKalshiHistory(experimentId);
          if (!cancelled && res.fill_count > 0) {
            setKalshiInfo(
              `${res.fill_count} Kalshi fills loaded (${res.first_ts?.slice(0, 10)} → ${res.last_ts?.slice(0, 10)})`,
            );
          }
        } catch {
          // fall back to local ledger
        }
      }
      if (!cancelled) {
        setRangeReady(true);
        void loadData(queryFromDateRange(start, end));
      }
    }
    void init();
    return () => {
      cancelled = true;
    };
  }, [experimentId, loadData]);

  useEffect(
    () => () => {
      if (applyTimerRef.current != null) window.clearTimeout(applyTimerRef.current);
    },
    [],
  );

  function handleStartChange(value: string) {
    setStartInput(value);
    applyRange(queryFromDateRange(value, endInput), true);
  }

  function handleEndChange(value: string) {
    setEndInput(value);
    applyRange(queryFromDateRange(startInput, value), true);
  }

  function handleRangeSubmit(e: React.FormEvent) {
    e.preventDefault();
    applyRange(historyQuery, true);
  }

  async function handleSyncKalshi() {
    if (!experiment || experiment.mode !== "live") return;
    setSyncing(true);
    setError(null);
    try {
      const res = await syncKalshiHistory(experimentId);
      setKalshiInfo(
        res.fill_count > 0
          ? `Loaded ${res.fill_count} Kalshi fills (${res.first_ts?.slice(0, 10)} → ${res.last_ts?.slice(0, 10)})`
          : "No Kalshi fills found",
      );
      await loadData(historyQuery);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Kalshi sync failed");
    } finally {
      setSyncing(false);
    }
  }

  const total = profile ? experimentReturn(profile) : null;
  const periodPnl = period ? Number(period.realized_pnl) : 0;
  const periodPct = period?.pnl_pct != null ? Number(period.pnl_pct) : null;
  const periodTone = pnlTone(periodPnl);
  const isLive = experiment?.mode === "live";

  return (
    <div className="min-h-screen bg-[#0b1220]">
      <NotificationCenter />
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="sticky top-0 z-40 -mx-4 mb-6 border-b border-ink-800/80 bg-[#0b1220]/95 px-4 py-3 backdrop-blur-sm sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <AppNav active="history" />
            <a href="#/history" className="text-sm text-ink-400 hover:text-accent">
              ← All experiments
            </a>
          </div>
        </div>

        {loading && !experiment ? (
          <div className="rounded-lg border border-ink-800 bg-ink-900/80 px-6 py-16 text-center">
            <p className="text-ink-300">Loading experiment…</p>
          </div>
        ) : null}

        {error ? (
          <div className="rounded-lg border border-red-900/50 bg-red-950/40 px-6 py-10 text-center">
            <p className="font-medium text-red-300">Could not load experiment</p>
            <p className="mt-2 font-mono text-sm text-red-400">{error}</p>
          </div>
        ) : null}

        {experiment && profile && stats && total ? (
          <>
            <header className="mb-6 animate-fade-in">
              <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium uppercase tracking-[0.2em] text-accent">
                    {isLive ? "Live account" : "Paper trading"}
                  </p>
                  <h1 className="mt-1 text-3xl font-semibold tracking-tight text-ink-50">{experiment.name}</h1>
                  <p className="mt-2 font-mono text-xs text-ink-500">{experiment.id}</p>
                </div>
                <span
                  className={`rounded-full px-3 py-1 text-xs font-semibold uppercase ${
                    isLive
                      ? "bg-red-950/80 text-red-300 ring-1 ring-red-800/60"
                      : "bg-sky-950/80 text-sky-300 ring-1 ring-sky-800/60"
                  }`}
                >
                  {experiment.mode}
                </span>
              </div>
            </header>

            {!isLive ? (
              <section className="mb-6 rounded-xl border border-ink-800 bg-ink-900/50 p-4">
                <h2 className="text-sm font-semibold text-ink-100">Tags</h2>
                <div className="mt-2">
                  <TagEditor
                    tags={experiment.tags ?? []}
                    saving={savingTags}
                    size="md"
                    onSave={async (tags) => {
                      setSavingTags(true);
                      try {
                        const exp = await patchExperiment(experimentId, { tags });
                        setExperiment(exp);
                      } finally {
                        setSavingTags(false);
                      }
                    }}
                  />
                </div>
                <div className="mt-3">
                  <button
                    type="button"
                    disabled={deleting}
                    onClick={() => {
                      if (
                        !window.confirm(
                          `Delete "${experiment.name}" permanently? All data will be removed from the database.`,
                        )
                      ) {
                        return;
                      }
                      setDeleting(true);
                      void deleteExperiment(experimentId, true)
                        .then(() => {
                          window.location.hash = "/history";
                        })
                        .catch((err) => setError(err instanceof Error ? err.message : "Delete failed"))
                        .finally(() => setDeleting(false));
                    }}
                    className="rounded border border-red-900/60 px-3 py-1.5 text-xs text-red-400 hover:bg-red-950/40"
                  >
                    {deleting ? "Deleting…" : "Delete experiment"}
                  </button>
                </div>
              </section>
            ) : null}

            <section className="mb-6 rounded-xl border border-ink-800 bg-ink-900/50 p-4">
              <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-ink-100">Time range</h2>
                  <p className="text-xs text-ink-500">Selected days are included in full (local time)</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {isLive ? (
                    <button
                      type="button"
                      disabled={syncing || loading}
                      onClick={() => void handleSyncKalshi()}
                      className="rounded border border-ink-700 px-3 py-1.5 text-xs text-ink-200 hover:border-accent/50 hover:text-accent disabled:opacity-50"
                    >
                      {syncing ? "Loading Kalshi…" : "Refresh Kalshi history"}
                    </button>
                  ) : null}
                  {loading ? (
                    <span className="self-center text-xs text-ink-500">Updating…</span>
                  ) : null}
                </div>
              </div>
              <form
                className="grid gap-3 sm:grid-cols-2"
                onSubmit={handleRangeSubmit}
              >
                <label className="block text-xs text-ink-500">
                  Start (inclusive)
                  <input
                    type="date"
                    value={startInput}
                    onChange={(e) => handleStartChange(e.target.value)}
                    className="mt-1 w-full rounded border border-ink-700 bg-ink-950 px-2 py-1.5 text-sm text-ink-100"
                  />
                </label>
                <label className="block text-xs text-ink-500">
                  End (inclusive)
                  <input
                    type="date"
                    value={endInput}
                    onChange={(e) => handleEndChange(e.target.value)}
                    className="mt-1 w-full rounded border border-ink-700 bg-ink-950 px-2 py-1.5 text-sm text-ink-100"
                  />
                </label>
              </form>
              {kalshiInfo ? <p className="mt-2 text-xs text-emerald-400">{kalshiInfo}</p> : null}
              {period?.capital_invested ? (
                <p className="mt-2 text-xs text-ink-500">
                  Capital invested: {formatUsd(Number(period.capital_invested))}
                  {period.net_deposits ? ` · Deposits in range: ${formatUsd(Number(period.net_deposits))}` : ""}
                </p>
              ) : null}
              {period ? (
                <p className="mt-1 text-xs text-ink-600">
                  Data source: {period.source}
                  {pnlSource ? ` · chart: ${pnlSource}` : ""}
                </p>
              ) : null}
            </section>

            <section className="mb-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <SummaryCard
                label="Period P&L"
                value={period ? formatPnl(periodPnl) : "—"}
                tone={periodTone}
              />
              <SummaryCard
                label="Period return %"
                value={periodPct != null ? formatPnlPct(periodPct) : "—"}
                tone={periodTone}
              />
              <SummaryCard label="All-time P&L" value={formatPnl(total.totalUsd)} tone={pnlTone(total.totalUsd)} />
              <SummaryCard label="Equity" value={formatUsd(Number(profile.equity))} />
              <SummaryCard label="Period fills" value={period ? String(period.fill_count) : "—"} />
              <SummaryCard
                label="Period closed trades"
                value={
                  period
                    ? `${period.closed_trades}${period.win_rate != null ? ` · ${period.win_rate}% win` : ""}`
                    : "—"
                }
              />
              <SummaryCard
                label="Realized (all-time)"
                value={formatPnl(Number(profile.realized_pnl))}
                tone={pnlTone(Number(profile.realized_pnl))}
              />
              <SummaryCard label="Fees paid" value={formatUsd(Number(profile.fees_paid))} />
            </section>

            <section className="mb-10">
              <SectionTitle title="P&L over time" subtitle="Cumulative realized profit/loss in selected range" />
              <PnlChart points={pnlPoints} active={!loading} />
            </section>

            <section className="mb-10">
              <SectionTitle
                title="All transactions"
                subtitle={`${fills.length} fill${fills.length === 1 ? "" : "s"} in range`}
              />
              {fills.length === 0 ? (
                <EmptyTable message="No fills in this range." />
              ) : (
                <div className="overflow-x-auto rounded-lg border border-ink-800">
                  <table className="min-w-full text-left text-sm">
                    <thead className="bg-ink-900/80 text-xs uppercase tracking-wide text-ink-500">
                      <tr>
                        <th className="px-4 py-3 font-medium">Time</th>
                        <th className="px-4 py-3 font-medium">Ticker</th>
                        <th className="px-4 py-3 font-medium">Side</th>
                        <th className="px-4 py-3 font-medium">Price</th>
                        <th className="px-4 py-3 font-medium">Qty</th>
                        <th className="px-4 py-3 font-medium">Fee</th>
                        <th className="px-4 py-3 font-medium">P&L</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ink-800/80">
                      {fills.map((f) => {
                        const hasTradePnl = f.trade_pnl != null;
                        const usd = hasTradePnl ? Number(f.trade_pnl) : 0;
                        const pct = hasTradePnl && f.trade_pnl_pct != null ? Number(f.trade_pnl_pct) : null;
                        return (
                        <tr key={f.id} className="bg-ink-950/40 hover:bg-ink-900/60">
                          <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs text-ink-400">
                            {formatTs(f.ts)}
                          </td>
                          <td className="px-4 py-2.5 font-mono text-ink-200">{f.ticker}</td>
                          <td className="px-4 py-2.5">
                            <SideBadge side={f.side} action={f.action} />
                          </td>
                          <td className="px-4 py-2.5 font-mono text-ink-200">{Math.round(Number(f.price) * 100)}¢</td>
                          <td className="px-4 py-2.5 font-mono text-ink-200">{f.qty}</td>
                          <td className="px-4 py-2.5 font-mono text-ink-400">{formatUsd(Number(f.fee))}</td>
                          <td className="px-4 py-2.5">
                            {hasTradePnl ? (
                              <PnlCell usd={usd} pct={pct} showLabel />
                            ) : (
                              <span className="text-ink-600">—</span>
                            )}
                          </td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section>
              <SectionTitle
                title="Closed round-trips"
                subtitle={`${roundTrips.filter((r) => r.exit_ts).length} completed trades with P&L`}
              />
              {roundTrips.filter((r) => r.exit_ts).length === 0 ? (
                <EmptyTable message="No closed trades in this range." />
              ) : (
                <div className="overflow-x-auto rounded-lg border border-ink-800">
                  <table className="min-w-full text-left text-sm">
                    <thead className="bg-ink-900/80 text-xs uppercase tracking-wide text-ink-500">
                      <tr>
                        <th className="px-4 py-3 font-medium">Ticker</th>
                        <th className="px-4 py-3 font-medium">Side</th>
                        <th className="px-4 py-3 font-medium">Qty</th>
                        <th className="px-4 py-3 font-medium">Entry</th>
                        <th className="px-4 py-3 font-medium">Exit</th>
                        <th className="px-4 py-3 font-medium">Result</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ink-800/80">
                      {roundTrips
                        .filter((r) => r.exit_ts)
                        .map((r) => {
                          const net = r.net_pnl != null ? Number(r.net_pnl) : 0;
                          const pct = r.pnl_pct != null ? Number(r.pnl_pct) : null;
                          return (
                            <tr key={r.id} className="bg-ink-950/40 hover:bg-ink-900/60">
                              <td className="px-4 py-2.5 font-mono text-ink-200">{r.ticker}</td>
                              <td className="px-4 py-2.5">
                                <span className="text-xs uppercase text-ink-400">{r.side}</span>
                              </td>
                              <td className="px-4 py-2.5 font-mono text-ink-200">{r.qty}</td>
                              <td className="px-4 py-2.5 font-mono text-xs text-ink-400">
                                {Math.round(Number(r.entry_price) * 100)}¢ · {formatTs(r.entry_ts)}
                              </td>
                              <td className="px-4 py-2.5 font-mono text-xs text-ink-400">
                                {r.exit_price != null ? `${Math.round(Number(r.exit_price) * 100)}¢ · ` : ""}
                                {r.exit_ts ? formatTs(r.exit_ts) : "—"}
                              </td>
                              <td className="px-4 py-2.5">
                                {r.net_pnl != null ? (
                                  <PnlCell usd={net} pct={pct} showLabel />
                                ) : (
                                  <span className="text-ink-500">—</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  tone = "flat",
}: {
  label: string;
  value: string;
  tone?: "profit" | "loss" | "flat";
}) {
  return (
    <div className="rounded-lg border border-ink-800 bg-ink-900/60 px-4 py-3">
      <p className="text-xs text-ink-500">{label}</p>
      <p className={`mt-1 font-mono text-lg ${pnlColorClass(tone)}`}>{value}</p>
    </div>
  );
}

function SectionTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-lg font-semibold text-ink-100">{title}</h2>
      <p className="text-sm text-ink-500">{subtitle}</p>
    </div>
  );
}

function EmptyTable({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-ink-800 bg-ink-900/40 px-6 py-10 text-center text-sm text-ink-400">
      {message}
    </div>
  );
}

function SideBadge({ side, action }: { side: Fill["side"]; action: Fill["action"] }) {
  const buy = action === "buy";
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
        buy ? "bg-emerald-950/60 text-emerald-300" : "bg-amber-950/60 text-amber-300"
      }`}
    >
      {tradeLabel(side, action)}
    </span>
  );
}

function formatTs(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
