import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchArchiveEvents, type ArchiveEvent } from "../api";
import { fetchArchivePnl, listExperiments, type Experiment } from "../api/trading";
import { AppNav } from "../components/AppNav";
import { NotificationCenter } from "../components/NotificationCenter";
import { PnlCell } from "../components/PnlCell";
import { formatVolume } from "../lib/format";
import { formatArchiveWindow } from "../lib/archivePnl";
import { marketStore } from "../store/marketStore";

const ARCHIVE_EXP_KEY = "kalshi.archiveListExperimentId";
const ARCHIVE_ONLY_TRADED_KEY = "kalshi.archiveOnlyTraded";

type SortKey = "series" | "bet" | "window" | "volume" | "strikes" | "closed" | "pnl";
type SortDir = "asc" | "desc";

function compareStrings(a: string, b: string): number {
  return a.localeCompare(b, undefined, { sensitivity: "base" });
}

function compareNullableNumbers(a: number | null, b: number | null, dir: SortDir): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return dir === "asc" ? a - b : b - a;
}

function SortHeader({
  label,
  column,
  active,
  dir,
  align = "left",
  onSort,
}: {
  label: string;
  column: SortKey;
  active: boolean;
  dir: SortDir;
  align?: "left" | "right";
  onSort: (column: SortKey) => void;
}) {
  return (
    <th
      scope="col"
      onClick={() => onSort(column)}
      className={`cursor-pointer select-none border-b border-ink-800 px-4 py-3 font-medium uppercase tracking-wide transition-colors hover:bg-ink-900/70 hover:text-ink-100 ${
        align === "right" ? "text-right" : "text-left"
      } ${active ? "text-accent" : "text-ink-500"}`}
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <span
        className={`inline-flex w-full items-center gap-1.5 ${
          align === "right" ? "justify-end" : "justify-start"
        }`}
      >
        <span>{label}</span>
        <span className="font-mono text-[10px] text-ink-400" aria-hidden>
          {active ? (dir === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </span>
    </th>
  );
}

export function ArchivePage() {
  const [events, setEvents] = useState<ArchiveEvent[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [selectedExpId, setSelectedExpId] = useState<string>(() => {
    try {
      return sessionStorage.getItem(ARCHIVE_EXP_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [eventPnl, setEventPnl] = useState<Map<string, number>>(new Map());
  const [tradedEvents, setTradedEvents] = useState<Set<string>>(new Set());
  const [onlyTraded, setOnlyTraded] = useState<boolean>(() => {
    try {
      return sessionStorage.getItem(ARCHIVE_ONLY_TRADED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [archiveStale, setArchiveStale] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("closed");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(column: SortKey) {
    if (sortKey === column) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(column);
      setSortDir(
        column === "volume" || column === "strikes" || column === "pnl" || column === "closed"
          ? "desc"
          : "asc",
      );
    }
  }

  const refreshEvents = useCallback(async () => {
    setError(null);
    try {
      const rows = await fetchArchiveEvents(undefined, 60);
      setEvents(rows);
      setArchiveStale(false);
      setState("ready");
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : "Failed to load archive");
    }
  }, []);

  const initialLoad = useCallback(async () => {
    setState("loading");
    await refreshEvents();
  }, [refreshEvents]);

  useEffect(() => {
    void initialLoad();
    void listExperiments(true).then(setExperiments).catch(() => {});
  }, [initialLoad]);

  useEffect(() => {
    return marketStore.subscribeArchive(() => {
      setArchiveStale(true);
      void refreshEvents();
    });
  }, [refreshEvents]);

  useEffect(() => {
    if (!selectedExpId) {
      setEventPnl(new Map());
      setTradedEvents(new Set());
      return;
    }
    let cancelled = false;
    // Server joins markets.event_ticker — correct for both -T and 15M suffixes.
    void fetchArchivePnl(selectedExpId)
      .then((rows) => {
        if (cancelled) return;
        const pnl = new Map<string, number>();
        const traded = new Set<string>();
        for (const row of rows) {
          traded.add(row.event_ticker);
          if (row.trade_count > 0) {
            pnl.set(row.event_ticker, Number(row.net_pnl));
          }
        }
        setEventPnl(pnl);
        setTradedEvents(traded);
      })
      .catch(() => {
        if (!cancelled) {
          setEventPnl(new Map());
          setTradedEvents(new Set());
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedExpId]);

  useEffect(() => {
    try {
      sessionStorage.setItem(ARCHIVE_ONLY_TRADED_KEY, onlyTraded ? "1" : "0");
    } catch {
      // ignore
    }
  }, [onlyTraded]);

  useEffect(() => {
    if (onlyTraded && !selectedExpId) {
      setOnlyTraded(false);
    }
  }, [onlyTraded, selectedExpId]);

  useEffect(() => {
    try {
      if (selectedExpId) sessionStorage.setItem(ARCHIVE_EXP_KEY, selectedExpId);
      else sessionStorage.removeItem(ARCHIVE_EXP_KEY);
    } catch {
      // ignore
    }
  }, [selectedExpId]);

  const filteredEvents = useMemo(() => {
    if (!onlyTraded || !selectedExpId) return events;
    return events.filter((e) => tradedEvents.has(e.event_ticker));
  }, [events, onlyTraded, selectedExpId, tradedEvents]);

  const sortedEvents = useMemo(() => {
    const dir = sortDir;
    const sign = dir === "asc" ? 1 : -1;

    return [...filteredEvents].sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "series":
          cmp = compareStrings(a.series_ticker ?? "", b.series_ticker ?? "");
          break;
        case "bet":
          cmp = compareStrings(a.bet_name ?? "", b.bet_name ?? "");
          break;
        case "window":
          cmp = compareStrings(
            a.event_title ?? a.event_ticker ?? "",
            b.event_title ?? b.event_ticker ?? "",
          );
          break;
        case "volume":
          cmp = (a.total_volume ?? 0) - (b.total_volume ?? 0);
          break;
        case "strikes":
          cmp = (a.market_count ?? 0) - (b.market_count ?? 0);
          break;
        case "closed":
          cmp = compareStrings(a.close_time ?? "", b.close_time ?? "");
          break;
        case "pnl": {
          const pa = selectedExpId ? (eventPnl.get(a.event_ticker) ?? null) : null;
          const pb = selectedExpId ? (eventPnl.get(b.event_ticker) ?? null) : null;
          return compareNullableNumbers(pa, pb, dir);
        }
        default:
          break;
      }
      return cmp * sign;
    });
  }, [filteredEvents, sortKey, sortDir, eventPnl, selectedExpId]);

  return (
    <div className="min-h-screen bg-[#0b1220]">
      <NotificationCenter />
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="sticky top-0 z-40 -mx-4 mb-6 border-b border-ink-800/80 bg-[#0b1220]/95 px-4 py-3 backdrop-blur-sm sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
          <AppNav active="archive" />
        </div>

        <header className="mb-6 animate-fade-in">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-accent">Settled bets</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-ink-50">Archive</h1>
          <p className="mt-2 max-w-xl text-sm text-ink-400">
            Liquid bets with official results. Select an experiment to see your net P/L per window.
          </p>
        </header>

        <div className="mb-4 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-ink-500">
            Experiment (for P/L column)
            <select
              value={selectedExpId}
              onChange={(e) => setSelectedExpId(e.target.value)}
              className="min-w-[220px] rounded border border-ink-700 bg-ink-950 px-3 py-2 text-sm text-ink-200"
            >
              <option value="">— none —</option>
              {experiments.map((exp) => (
                <option key={exp.id} value={exp.id}>
                  {exp.name} ({exp.mode})
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
            Only bets with trades
          </label>
          {archiveStale ? (
            <button
              type="button"
              onClick={() => void refreshEvents()}
              className="rounded border border-amber-800/60 bg-amber-950/30 px-3 py-2 text-xs text-amber-300"
            >
              New settlements — refresh
            </button>
          ) : null}
        </div>

        {state === "loading" ? (
          <p className="text-sm text-ink-500">Loading archive…</p>
        ) : null}
        {state === "error" ? <p className="text-sm text-red-400">{error}</p> : null}
        {state === "ready" && events.length > 0 && sortedEvents.length === 0 ? (
          <p className="text-sm text-ink-500">
            No archived bets with trades for the selected experiment.
          </p>
        ) : null}
        {state === "ready" && events.length === 0 ? (
          <p className="text-sm text-ink-500">No archived liquid bets yet.</p>
        ) : null}

        {state === "ready" && sortedEvents.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-ink-800">
            <table className="w-full min-w-[880px] border-collapse text-sm">
              <thead>
                <tr className="bg-ink-950/90 text-xs uppercase tracking-wide">
                  <SortHeader label="Series" column="series" active={sortKey === "series"} dir={sortDir} onSort={handleSort} />
                  <SortHeader label="Bet" column="bet" active={sortKey === "bet"} dir={sortDir} onSort={handleSort} />
                  <SortHeader label="Window" column="window" active={sortKey === "window"} dir={sortDir} onSort={handleSort} />
                  <SortHeader label="Volume" column="volume" active={sortKey === "volume"} dir={sortDir} align="right" onSort={handleSort} />
                  <SortHeader label="Strikes" column="strikes" active={sortKey === "strikes"} dir={sortDir} align="right" onSort={handleSort} />
                  <SortHeader label="Closed" column="closed" active={sortKey === "closed"} dir={sortDir} align="right" onSort={handleSort} />
                  <SortHeader label="Net P/L" column="pnl" active={sortKey === "pnl"} dir={sortDir} align="right" onSort={handleSort} />
                </tr>
              </thead>
              <tbody>
                {sortedEvents.map((event) => {
                  const pnl = selectedExpId ? eventPnl.get(event.event_ticker) : undefined;
                  const traded = tradedEvents.has(event.event_ticker);
                  return (
                    <tr
                      key={event.event_ticker}
                      className="cursor-pointer border-b border-ink-800/70 bg-ink-950/40 hover:bg-accent/5"
                      onClick={() => {
                        const exp = selectedExpId
                          ? `?exp=${encodeURIComponent(selectedExpId)}`
                          : "";
                        window.location.hash = `#/archive/${encodeURIComponent(event.event_ticker)}${exp}`;
                      }}
                    >
                      <td className="px-4 py-3">
                        <div className="font-mono text-xs text-ink-400">{event.series_ticker}</div>
                        {event.series_title ? (
                          <div className="truncate text-xs text-ink-500">{event.series_title}</div>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-ink-200">{event.bet_name ?? "—"}</td>
                      <td className="px-4 py-3">
                        <div className="text-ink-100">{event.event_title ?? event.event_ticker}</div>
                        <div className="font-mono text-xs text-ink-500">{event.event_ticker}</div>
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-ink-300">
                        {formatVolume(String(event.total_volume ?? 0))}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-ink-400">
                        {event.market_count}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-ink-400">
                        {formatArchiveWindow(event.open_time, event.close_time)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {selectedExpId && traded && pnl != null ? (
                          <PnlCell usd={pnl} />
                        ) : selectedExpId && traded ? (
                          <span className="font-mono text-xs text-ink-500">open</span>
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
        ) : null}
      </div>
    </div>
  );
}
