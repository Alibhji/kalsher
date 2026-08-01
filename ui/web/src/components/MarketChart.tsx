import { useEffect, useRef, useState } from "react";
import { createChart, type IChartApi, type ISeriesApi, type LineData, type UTCTimestamp } from "lightweight-charts";
import { fetchMarketHistory, type MarketHistory } from "../api";
import { useMarketRow } from "../store/useMarketStore";
import { KalshiLink } from "./KalshiLink";

type Props = {
  ticker: string;
  label: string;
  openTime: string | null;
  closeTime: string | null;
  kalshiUrl: string;
};

const POLL_MS = 2000;
const HIDDEN_POLL_MS = 10000;

function formatWindow(start: string | null, end: string | null): string {
  if (!start || !end) return "";
  const fmt = (iso: string) =>
    new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  return `${fmt(start)} → ${fmt(end)}`;
}

function toSeriesData(points: MarketHistory["points"]): LineData[] {
  const bySecond = new Map<number, LineData>();
  for (const p of points) {
    const sec = Math.floor(Date.parse(p.ts) / 1000);
    if (Number.isNaN(sec)) continue;
    bySecond.set(sec, { time: sec as UTCTimestamp, value: p.yes_cents });
  }
  return [...bySecond.entries()]
    .sort(([a], [b]) => a - b)
    .map(([, point]) => point);
}

function mergePoints(existing: MarketHistory["points"], incoming: MarketHistory["points"]): MarketHistory["points"] {
  const byTs = new Map<string, MarketHistory["points"][number]>();
  for (const p of existing) byTs.set(p.ts, p);
  for (const p of incoming) byTs.set(p.ts, p);
  return [...byTs.values()].sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));
}

function liveMidCents(yesBid: number | null | undefined, yesAsk: number | null | undefined): number | null {
  if (yesBid != null && yesAsk != null) return (yesBid + yesAsk) / 2;
  if (yesBid != null) return yesBid;
  if (yesAsk != null) return yesAsk;
  return null;
}

export function MarketChart({ ticker, label, openTime, closeTime, kalshiUrl }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const lastPointTimeRef = useRef<number | null>(null);
  const lastPointTsRef = useRef<string | null>(null);
  const closedRef = useRef(false);
  const [history, setHistory] = useState<MarketHistory | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error" | "empty">("loading");
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const updatedAtRef = useRef<number>(0);
  const live = useMarketRow(ticker);

  useEffect(() => {
    let cancelled = false;
    let pollId = 0;
    lastPointTimeRef.current = null;
    lastPointTsRef.current = null;
    closedRef.current = false;
    setState("loading");
    setError(null);
    setHistory(null);

    async function load(initial: boolean) {
      try {
        const since = initial ? undefined : lastPointTsRef.current ?? undefined;
        const data = await fetchMarketHistory(ticker, since);
        if (cancelled) return;

        closedRef.current = Boolean(data.closed);
        setHistory((prev) => {
          if (initial || !prev || !data.incremental) return data;
          return { ...data, points: mergePoints(prev.points, data.points) };
        });
        setUpdatedAt(new Date());
        setState(data.points.length === 0 && initial ? "empty" : "ready");
        setError(null);

        if (data.points.length > 0) {
          const last = data.points[data.points.length - 1];
          lastPointTsRef.current = last.ts;
        }
      } catch (err) {
        if (cancelled) return;
        setState((s) => {
          if (s !== "loading" && !initial) return s;
          setError(err instanceof Error ? err.message : "Failed to load chart");
          return "error";
        });
      }
    }

    function schedulePoll() {
      if (cancelled || closedRef.current) return;
      const delay = document.hidden ? HIDDEN_POLL_MS : POLL_MS;
      pollId = window.setTimeout(async () => {
        await load(false);
        schedulePoll();
      }, delay);
    }

    load(true).then(() => schedulePoll());

    function onVisibilityChange() {
      if (document.hidden || cancelled || closedRef.current) return;
      window.clearTimeout(pollId);
      schedulePoll();
    }
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      cancelled = true;
      window.clearTimeout(pollId);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      chartRef.current?.remove();
      chartRef.current = null;
      seriesRef.current = null;
      lastPointTimeRef.current = null;
      lastPointTsRef.current = null;
      closedRef.current = false;
    };
  }, [ticker]);

  useEffect(() => {
    if (!containerRef.current || state !== "ready" || !history) return;

    if (!chartRef.current) {
      const chart = createChart(containerRef.current, {
        width: containerRef.current.clientWidth,
        height: 220,
        layout: {
          background: { color: "#0f172a" },
          textColor: "#94a3b8",
        },
        grid: {
          vertLines: { color: "#1e293b" },
          horzLines: { color: "#1e293b" },
        },
        rightPriceScale: { borderColor: "#334155" },
        timeScale: {
          borderColor: "#334155",
          timeVisible: true,
          secondsVisible: true,
        },
        crosshair: {
          vertLine: { color: "#475569" },
          horzLine: { color: "#475569" },
        },
      });
      seriesRef.current = chart.addLineSeries({
        color: "#2dd4bf",
        lineWidth: 2,
        priceFormat: { type: "custom", formatter: (p: number) => `${p.toFixed(0)}¢` },
      });
      chartRef.current = chart;
    }

    const data = toSeriesData(history.points);
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !chart || data.length === 0) return;

    const lastTime = lastPointTimeRef.current;
    const latest = data[data.length - 1]?.time as number | undefined;

    if (lastTime == null) {
      series.setData(data);
      chart.timeScale().fitContent();
    } else {
      for (const point of data) {
        if ((point.time as number) >= lastTime) {
          series.update(point);
        }
      }
    }

    lastPointTimeRef.current = latest ?? lastTime;

    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [history, state]);

  useEffect(() => {
    if (closedRef.current || state === "loading") return;
    const mid = liveMidCents(live?.yes_bid_cents, live?.yes_ask_cents);
    if (mid == null) return;

    const sec = Math.floor(Date.now() / 1000) as UTCTimestamp;
    const point: LineData = { time: sec, value: mid };

    if (state === "empty") {
      setState("ready");
      setHistory((prev) => ({
        ticker,
        open_time: prev?.open_time ?? openTime,
        close_time: prev?.close_time ?? closeTime,
        window_start: prev?.window_start ?? openTime,
        window_end: prev?.window_end ?? closeTime,
        points: [{ ts: new Date(sec * 1000).toISOString(), yes_cents: mid }],
        incremental: false,
        closed: false,
      }));
      return;
    }

    if (state !== "ready" || !seriesRef.current) return;

    seriesRef.current.update(point);
    lastPointTimeRef.current = sec;
    const now = Date.now();
    if (now - updatedAtRef.current >= 1000) {
      updatedAtRef.current = now;
      setUpdatedAt(new Date(now));
    }
  }, [live?.yes_bid_cents, live?.yes_ask_cents, state, ticker, openTime, closeTime]);

  const windowLabel = formatWindow(
    history?.window_start ?? openTime,
    history?.window_end ?? closeTime,
  );

  return (
    <div className="border-t border-ink-800 bg-ink-950/80 px-4 py-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-ink-100">{label}</p>
          <p className="font-mono text-xs text-ink-500">{ticker}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {windowLabel ? (
            <p className="text-xs text-ink-400">
              {history?.closed ? "Closed window" : "Live window"} · {windowLabel}
            </p>
          ) : null}
          {updatedAt ? (
            <p className="font-mono text-xs text-ink-500">
              Chart {updatedAt.toLocaleTimeString()}
            </p>
          ) : null}
          <KalshiLink url={kalshiUrl} />
        </div>
      </div>

      <div className="relative h-[220px]">
        {state === "loading" ? (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-ink-500">
            Loading chart…
          </div>
        ) : null}
        {state === "error" ? (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-red-400">
            {error}
          </div>
        ) : null}
        {state === "empty" ? (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-ink-500">
            No price data yet for the active bet window.
          </div>
        ) : null}
        <div
          ref={containerRef}
          className={`h-full w-full ${state === "ready" ? "opacity-100" : "opacity-0"}`}
        />
      </div>
    </div>
  );
}
