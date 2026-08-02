import { useEffect, useRef } from "react";
import {
  createChart,
  type BaselineData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { PnlPoint } from "../api/trading";

const CHART_H = 280;

type Props = {
  points: PnlPoint[];
  active?: boolean;
};

export function PnlChart({ points, active = true }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Baseline"> | null>(null);

  useEffect(() => {
    if (!active) {
      chartRef.current?.remove();
      chartRef.current = null;
      seriesRef.current = null;
      return;
    }
    if (!containerRef.current || chartRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: CHART_H,
      layout: { background: { color: "#0f172a" }, textColor: "#94a3b8" },
      grid: { vertLines: { color: "#1e293b" }, horzLines: { color: "#1e293b" } },
      rightPriceScale: { borderColor: "#334155" },
      timeScale: { borderColor: "#334155", timeVisible: true, secondsVisible: false },
      crosshair: { vertLine: { color: "#475569" }, horzLine: { color: "#475569" } },
    });
    seriesRef.current = chart.addBaselineSeries({
      baseValue: { type: "price", price: 0 },
      topLineColor: "#34d399",
      topFillColor1: "rgba(52, 211, 153, 0.35)",
      topFillColor2: "rgba(52, 211, 153, 0.02)",
      bottomLineColor: "#f87171",
      bottomFillColor1: "rgba(248, 113, 113, 0.02)",
      bottomFillColor2: "rgba(248, 113, 113, 0.35)",
      lineWidth: 2,
      priceFormat: {
        type: "custom",
        formatter: (v: number) => {
          if (v > 0) return `+$${v.toFixed(2)}`;
          if (v < 0) return `-$${Math.abs(v).toFixed(2)}`;
          return "$0.00";
        },
      },
    });
    chartRef.current = chart;

    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    ro.observe(containerRef.current);
    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [active]);

  useEffect(() => {
    if (!seriesRef.current || !active) return;
    const data: BaselineData[] = [...points]
      .sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts))
      .map((p) => ({
        time: Math.floor(Date.parse(p.ts) / 1000) as UTCTimestamp,
        value: Number(p.cumulative_pnl),
      }));
    seriesRef.current.setData(data);
    chartRef.current?.timeScale().fitContent();
  }, [points, active]);

  if (!active) return null;

  const last = points.length > 0 ? Number(points[points.length - 1].cumulative_pnl) : 0;
  const tone = last > 0 ? "text-emerald-400" : last < 0 ? "text-red-400" : "text-ink-400";

  return (
    <div className="rounded-lg border border-ink-800 bg-ink-950/60 p-3">
      {points.length === 0 ? (
        <div className="flex h-[280px] items-center justify-center text-sm text-ink-500">
          No P&L data in this range
        </div>
      ) : (
        <>
          <div className="mb-2 flex items-center justify-between text-xs text-ink-500">
            <span>Green = profit · Red = loss · Zero line = break-even</span>
            <span className={`font-mono font-medium ${tone}`}>
              {last > 0 ? `+$${last.toFixed(2)}` : last < 0 ? `-$${Math.abs(last).toFixed(2)}` : "$0.00"}
            </span>
          </div>
          <div ref={containerRef} />
        </>
      )}
    </div>
  );
}
