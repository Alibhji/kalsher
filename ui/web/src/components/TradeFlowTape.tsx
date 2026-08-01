import type { TradePrint } from "../store/tradeStore";

type Props = {
  tape: readonly TradePrint[];
  netUsd: number;
  compact?: boolean;
};

function formatFlow(usd: number): string {
  const abs = Math.abs(usd);
  if (abs >= 1_000_000) return `$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${(abs / 1_000).toFixed(1)}K`;
  if (abs >= 100) return `$${abs.toFixed(0)}`;
  if (abs >= 10) return `$${abs.toFixed(1)}`;
  return `$${abs.toFixed(2)}`;
}

function formatSigned(usd: number): string {
  const prefix = usd >= 0 ? "+" : "−";
  return `${prefix}${formatFlow(usd)}`;
}

export function TradeFlowTape({ tape, netUsd, compact = false }: Props) {
  const recent = [...tape].reverse().slice(0, compact ? 12 : 24);

  return (
    <div
      className={`flex shrink-0 flex-col border-ink-800 bg-ink-950/90 ${
        compact ? "w-[88px] border-r px-1.5 py-2" : "w-[104px] border-r px-2 py-3"
      }`}
    >
      <div className="mb-2 border-b border-ink-800/80 pb-2">
        <p className="text-[10px] uppercase tracking-wide text-ink-500">Net since open</p>
        <p
          className={`font-mono text-sm font-semibold ${
            netUsd > 0 ? "text-emerald-400" : netUsd < 0 ? "text-red-400" : "text-ink-400"
          }`}
        >
          {formatSigned(netUsd)}
        </p>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-hidden">
        {recent.length === 0 ? (
          <p className="text-[10px] text-ink-600">Waiting for trades…</p>
        ) : (
          recent.map((trade, i) => (
            <p
              key={`${trade.trade_id ?? trade.ts}-${i}`}
              className={`truncate font-mono text-[11px] leading-tight ${
                trade.signed_usd >= 0 ? "text-emerald-400/95" : "text-red-400/95"
              }`}
            >
              {formatSigned(trade.signed_usd)}
            </p>
          ))
        )}
      </div>
    </div>
  );
}

export function TradeNetBadge({ netUsd }: { netUsd: number }) {
  if (netUsd === 0) return null;
  const positive = netUsd > 0;
  return (
    <span
      className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
        positive
          ? "border-emerald-900/60 bg-emerald-950/40 text-emerald-400"
          : "border-red-900/60 bg-red-950/40 text-red-400"
      }`}
    >
      {formatSigned(netUsd)}
    </span>
  );
}
