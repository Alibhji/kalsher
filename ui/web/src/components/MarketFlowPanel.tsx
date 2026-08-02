import { useEffect, useRef } from "react";
import { useSyncExternalStore } from "react";
import { createChart, type IChartApi, type ISeriesApi } from "lightweight-charts";
import { cumulativeFlowSeries, tradeStore } from "../store/tradeStore";

const CHART_H = 220;

type Props = {
  ticker: string;
  active: boolean;
};

export function MarketFlowPanel({ ticker, active }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const lastPointTimeRef = useRef<number | null>(null);
  const tradeCountRef = useRef(0);

  const windowTrades = useSyncExternalStore(
    (listener) => tradeStore.subscribeTicker(ticker, listener),
    () => tradeStore.getWindowTrades(ticker),
    () => tradeStore.getWindowTrades(ticker),
  );

  useEffect(() => {
    if (!active) {
      chartRef.current?.remove();
      chartRef.current = null;
      seriesRef.current = null;
      lastPointTimeRef.current = null;
      tradeCountRef.current = 0;
      return;
    }
    if (!containerRef.current || chartRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: CHART_H,
      layout: { background: { color: "#0f172a" }, textColor: "#94a3b8" },
      grid: { vertLines: { color: "#1e293b" }, horzLines: { color: "#1e293b" } },
      rightPriceScale: { borderColor: "#334155" },
      timeScale: { borderColor: "#334155", timeVisible: true, secondsVisible: true },
      crosshair: { vertLine: { color: "#475569" }, horzLine: { color: "#475569" } },
    });
    seriesRef.current = chart.addLineSeries({
      color: "#60a5fa",
      lineWidth: 2,
      priceFormat: {
        type: "custom",
        formatter: (v: number) => {
          const abs = Math.abs(v);
          const prefix = v >= 0 ? "+" : "−";
          if (abs >= 1000) return `${prefix}$${(abs / 1000).toFixed(1)}K`;
          return `${prefix}$${abs.toFixed(0)}`;
        },
      },
    });
    chartRef.current = chart;

    const seeded = tradeStore.getWindowTrades(ticker);
    if (seeded.length > 0 && seriesRef.current) {
      const initial = cumulativeFlowSeries(seeded);
      seriesRef.current.setData(initial);
      chart.timeScale().fitContent();
      lastPointTimeRef.current = (initial[initial.length - 1]?.time as number | undefined) ?? null;
      tradeCountRef.current = seeded.length;
    }

    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      lastPointTimeRef.current = null;
      tradeCountRef.current = 0;
    };
  }, [active, ticker]);

  useEffect(() => {
    if (!active) return;

    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !chart) return;

    const tradeCount = windowTrades.length;
    const data = cumulativeFlowSeries(windowTrades);

    if (data.length === 0) {
      if (tradeCountRef.current > 0) {
        series.setData([]);
        lastPointTimeRef.current = null;
      }
      tradeCountRef.current = 0;
      return;
    }

    const latestTime = data[data.length - 1]?.time as number | undefined;

    if (lastPointTimeRef.current == null || tradeCount < tradeCountRef.current) {
      series.setData(data);
      chart.timeScale().fitContent();
      lastPointTimeRef.current = latestTime ?? null;
      tradeCountRef.current = tradeCount;
      return;
    }

    if (tradeCount > tradeCountRef.current) {
      // update() validates against the series' own last point, which can drift from our
      // ref (late trades, pruning, remounts). Rewriting the whole series is the safe
      // recovery, since throwing here would tear down the page.
      try {
        let cursor = lastPointTimeRef.current!;
        for (const point of data) {
          const time = point.time as number;
          if (time < cursor) continue;
          series.update(point);
          cursor = time;
        }
      } catch {
        series.setData(data);
        chart.timeScale().fitContent();
      }
      lastPointTimeRef.current = latestTime ?? lastPointTimeRef.current;
      tradeCountRef.current = tradeCount;
    }
  }, [active, windowTrades, ticker]);

  const hasData = windowTrades.length > 0;

  return (
    <div className="relative h-[220px] overflow-hidden rounded-md border border-ink-800/80">
      {!hasData ? (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-ink-500">
          No trades since window open yet.
        </div>
      ) : null}
      <div ref={containerRef} className={`h-full w-full ${hasData ? "opacity-100" : "opacity-0"}`} />
    </div>
  );
}
