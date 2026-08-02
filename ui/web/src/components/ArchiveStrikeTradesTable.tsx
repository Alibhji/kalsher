import { tradeLabel, type RoundTrip } from "../api/trading";
import { PnlCell } from "./PnlCell";
import { sumNetPnl } from "../lib/archivePnl";

function formatTradePoint(iso: string, price: string): string {
  const t = new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${Math.round(Number(price) * 100)}¢ · ${t}`;
}

type Props = {
  trips: RoundTrip[];
};

/** Compact P/L table shown under each archived strike chart. */
export function ArchiveStrikeTradesTable({ trips }: Props) {
  if (trips.length === 0) return null;

  const subtotal = sumNetPnl(trips);

  return (
    <div className="mt-3 overflow-x-auto rounded border border-ink-800/80 bg-ink-950/60">
      <table className="w-full min-w-[420px] text-left text-xs">
        <thead>
          <tr className="border-b border-ink-800/80 text-[10px] uppercase tracking-wide text-ink-500">
            <th className="px-2.5 py-1.5 font-medium">Side</th>
            <th className="px-2.5 py-1.5 font-medium">Trade in</th>
            <th className="px-2.5 py-1.5 font-medium">Trade out</th>
            <th className="px-2.5 py-1.5 text-right font-medium">Net P/L</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-800/60">
          {trips.map((rt) => {
            const net = rt.net_pnl != null ? Number(rt.net_pnl) : null;
            const pct = rt.pnl_pct != null ? Number(rt.pnl_pct) : null;
            return (
              <tr key={rt.id} className="text-ink-300">
                <td className="px-2.5 py-1.5 font-mono uppercase text-ink-400">
                  {tradeLabel(rt.side, "buy")} ×{rt.qty}
                </td>
                <td className="px-2.5 py-1.5 font-mono text-emerald-400/90">
                  {formatTradePoint(rt.entry_ts, rt.entry_price)}
                </td>
                <td className="px-2.5 py-1.5 font-mono">
                  {rt.exit_ts && rt.exit_price ? (
                    <span className="text-amber-300/90">
                      {formatTradePoint(rt.exit_ts, rt.exit_price)}
                    </span>
                  ) : (
                    <span className="text-ink-600">—</span>
                  )}
                </td>
                <td className="px-2.5 py-1.5 text-right">
                  {net != null && rt.exit_ts ? (
                    <PnlCell usd={net} pct={pct} />
                  ) : (
                    <span className="font-mono text-ink-500">open</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
        {trips.length > 1 ? (
          <tfoot>
            <tr className="border-t border-ink-700/80 bg-ink-900/40">
              <td colSpan={3} className="px-2.5 py-1.5 text-right text-[10px] uppercase text-ink-500">
                Strike total
              </td>
              <td className="px-2.5 py-1.5 text-right">
                <PnlCell usd={subtotal} />
              </td>
            </tr>
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}
