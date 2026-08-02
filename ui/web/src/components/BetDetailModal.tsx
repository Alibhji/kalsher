import { useEffect } from "react";
import type { MarketRow } from "../api";
import {
  countdownTone,
  formatCents,
  formatCountdown,
  formatStrike,
  formatVolume,
} from "../lib/format";
import { useNowMs } from "../lib/useNow";
import { useMarketRow } from "../store/useMarketStore";
import { tradingStore } from "../store/tradingStore";
import { KalshiLink } from "./KalshiLink";
import { MarketChart } from "./MarketChart";

type Props = {
  ticker: string | null;
  fallback: MarketRow | null;
  onClose: () => void;
};

function toneClass(tone: "normal" | "warn" | "urgent"): string {
  if (tone === "urgent") return "text-red-400";
  if (tone === "warn") return "text-amber-400";
  return "text-ink-300";
}

export function BetDetailModal({ ticker, fallback, onClose }: Props) {
  const live = useMarketRow(ticker ?? "") ?? fallback;
  const nowMs = useNowMs();

  useEffect(() => {
    if (!ticker) return;
    tradingStore.setSelectedTicker(ticker);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [ticker, onClose]);

  if (!ticker || !live) return null;

  const label = live.title || live.event_title || live.ticker;
  const expireTone = countdownTone(live.seconds_to_close, nowMs, live.close_time);

  return (
    <div
      className="fixed inset-0 z-[100] flex flex-col bg-[#0b1220]/98 backdrop-blur-sm lg:left-72"
      role="dialog"
      aria-modal="true"
      aria-labelledby="bet-detail-title"
    >
      <header className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b border-ink-800 px-4 py-3 sm:px-6">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-accent">Active bet</p>
          <h2 id="bet-detail-title" className="mt-0.5 truncate text-lg font-semibold text-ink-50">
            {label}
          </h2>
          <p className="font-mono text-xs text-ink-500">{live.ticker}</p>
          {live.event_title && live.title !== live.event_title ? (
            <p className="mt-1 text-sm text-ink-400">{live.event_title}</p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition-colors hover:border-ink-500 hover:text-ink-100"
        >
          Close
        </button>
      </header>

      <div className="grid shrink-0 grid-cols-2 gap-2 border-b border-ink-800/80 px-4 py-3 text-xs sm:grid-cols-4 sm:px-6 md:grid-cols-6">
        <InfoCell label="Strike" value={formatStrike(live.floor_strike, live.cap_strike)} mono />
        <InfoCell label="YES" value={formatCents(live.yes_bid_cents, live.yes_ask_cents)} mono accent="yes" />
        <InfoCell label="NO" value={formatCents(live.no_bid_cents, live.no_ask_cents)} mono accent="no" />
        <InfoCell label="Volume" value={formatVolume(live.volume)} mono />
        <InfoCell label="Open interest" value={formatVolume(live.open_interest)} mono />
        <InfoCell
          label="Expires"
          value={formatCountdown(live.seconds_to_close, nowMs, live.close_time)}
          mono
          className={toneClass(expireTone)}
        />
        {live.series_ticker ? (
          <InfoCell label="Series" value={live.series_ticker} mono className="col-span-2" />
        ) : null}
        <div className="flex items-end sm:col-span-2">
          <KalshiLink url={live.kalshi_url} />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <MarketChart
          key={live.ticker}
          ticker={live.ticker}
          label={label}
          openTime={live.open_time}
          closeTime={live.close_time}
          kalshiUrl={live.kalshi_url}
          chartHeight={480}
          className="min-h-[520px] border-0 bg-transparent"
        />
      </div>
    </div>
  );
}

function InfoCell({
  label,
  value,
  mono = false,
  accent,
  className = "",
}: {
  label: string;
  value: string;
  mono?: boolean;
  accent?: "yes" | "no";
  className?: string;
}) {
  const color =
    accent === "yes" ? "text-emerald-400/90" : accent === "no" ? "text-red-400/90" : "text-ink-200";
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-ink-600">{label}</p>
      <p className={`${mono ? "font-mono" : ""} ${color} ${className}`}>{value}</p>
    </div>
  );
}
