import { formatPnl, formatPnlPct, pnlColorClass, pnlTone } from "../lib/pnl";

type Props = {
  usd: number;
  pct?: number | null;
  showLabel?: boolean;
};

export function PnlCell({ usd, pct, showLabel = false }: Props) {
  const tone = pnlTone(usd);
  const label = tone === "profit" ? "Profit" : tone === "loss" ? "Loss" : "Even";

  return (
    <div className="flex flex-col gap-0.5">
      {showLabel && usd !== 0 ? (
        <span
          className={`inline-flex w-fit rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
            tone === "profit"
              ? "bg-emerald-950/70 text-emerald-300"
              : tone === "loss"
                ? "bg-red-950/70 text-red-300"
                : "bg-ink-800 text-ink-400"
          }`}
        >
          {label}
        </span>
      ) : null}
      <div className={`font-mono ${pnlColorClass(tone)}`}>
        <span>{formatPnl(usd)}</span>
        {pct != null ? <span className="ml-1.5 text-xs opacity-90">{formatPnlPct(pct)}</span> : null}
      </div>
    </div>
  );
}
