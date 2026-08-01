import { Fragment, useEffect, useState } from "react";
import type { MarketRow } from "../api";
import {
  countdownTone,
  formatCents,
  formatCountdown,
  formatStrike,
  formatVolume,
} from "../lib/format";
import { isMarketLive } from "../lib/filters";
import { KalshiLink } from "./KalshiLink";
import { MarketChart } from "./MarketChart";

type Props = {
  markets: MarketRow[];
  nowMs: number;
  filtersActive?: boolean;
};

function toneClass(tone: "normal" | "warn" | "urgent"): string {
  if (tone === "urgent") return "text-red-400";
  if (tone === "warn") return "text-amber-400";
  return "text-ink-300";
}

export function MarketsTable({ markets, nowMs, filtersActive = false }: Props) {
  const [visible, setVisible] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    const id = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(id);
  }, []);

  if (markets.length === 0) {
    return (
      <div className="rounded-lg border border-ink-800 bg-ink-900/80 px-6 py-16 text-center animate-fade-in">
        <p className="text-lg font-medium text-ink-100">
          {filtersActive ? "No markets match your filters" : "No active markets"}
        </p>
        <p className="mt-2 text-sm text-ink-500">
          {filtersActive
            ? "Try clearing search or turning off “Live bets only”."
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
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 font-medium">Series</th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 font-medium">Title / event</th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 font-medium">Ticker</th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 font-medium">Strike</th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 text-right font-medium">YES</th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 text-right font-medium">Volume</th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 text-right font-medium">Expires</th>
              <th className="sticky top-0 z-10 bg-ink-950/95 px-4 py-3 font-medium">Link</th>
            </tr>
          </thead>
          <tbody>
            {markets.map((m, i) => {
              const tone = countdownTone(m.seconds_to_close, nowMs, m.close_time);
              const label = m.event_title || m.title || "—";
              const series = m.series_ticker || m.series_title || m.category || "—";
              const isOpen = expanded === m.ticker;

              return (
                <Fragment key={m.ticker}>
                  <tr
                    onClick={() => setExpanded(isOpen ? null : m.ticker)}
                    className={`cursor-pointer border-b border-ink-800 transition-colors hover:bg-accent/10 ${
                      isOpen ? "bg-accent/10" : i % 2 === 0 ? "bg-ink-900" : "bg-ink-950/50"
                    }`}
                  >
                    <td className="px-4 py-3 font-medium text-ink-100">
                      <span className="inline-flex items-center gap-2">
                        {series}
                        {isMarketLive(m, nowMs) ? (
                          <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent">
                            live
                          </span>
                        ) : null}
                      </span>
                    </td>
                    <td className="max-w-xs px-4 py-3 text-ink-200">
                      <div className="truncate" title={label}>
                        {label}
                      </div>
                      {m.title && m.event_title && m.title !== m.event_title ? (
                        <div className="truncate text-xs text-ink-500" title={m.title}>
                          {m.title}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-ink-400">{m.ticker}</td>
                    <td className="px-4 py-3 font-mono text-xs text-ink-400">
                      {formatStrike(m.floor_strike, m.cap_strike, m.strike_type)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-ink-100">
                      {formatCents(m.yes_bid_cents, m.yes_ask_cents)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-ink-100">
                      {formatVolume(m.volume)}
                    </td>
                    <td className={`px-4 py-3 text-right font-mono font-medium ${toneClass(tone)}`}>
                      {formatCountdown(m.seconds_to_close, nowMs, m.close_time)}
                    </td>
                    <td className="px-4 py-3">
                      <KalshiLink url={m.kalshi_url} />
                    </td>
                  </tr>
                  {isOpen ? (
                    <tr className="bg-ink-950">
                      <td colSpan={8} className="p-0">
                        <MarketChart
                          ticker={m.ticker}
                          label={label}
                          openTime={m.open_time}
                          closeTime={m.close_time}
                          kalshiUrl={m.kalshi_url}
                        />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="border-t border-ink-800 px-4 py-2 text-xs text-ink-500">
        Click a row to expand YES price chart for the active bet window.
      </p>
    </div>
  );
}
