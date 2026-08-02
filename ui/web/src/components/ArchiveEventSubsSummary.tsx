import type { ArchiveMarket } from "../api";
import type { RoundTrip } from "../api/trading";
import { archiveMarketVolume, sortTripsChronologically, sumNetPnl } from "../lib/archivePnl";
import { formatStrike, formatVolume } from "../lib/format";
import { formatPnl, pnlColorClass, pnlTone } from "../lib/pnl";

function formatPoint(iso: string, price: string): string {
  const t = new Date(iso).toLocaleString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${Math.round(Number(price) * 100)}¢ ${t}`;
}

type Props = {
  eventTicker: string;
  markets: ArchiveMarket[];
  tripsByTicker: Map<string, RoundTrip[]>;
};

/** Event-level compact P/L rollup — one row per strike, sorted by volume. */
export function ArchiveEventSubsSummary({ eventTicker, markets, tripsByTicker }: Props) {
  const rows = [...markets]
    .sort((a, b) => archiveMarketVolume(b.volume) - archiveMarketVolume(a.volume))
    .map((m) => {
      const trips = sortTripsChronologically(tripsByTicker.get(m.ticker) ?? []);
      const closed = trips.filter((t) => t.exit_ts && t.exit_price);
      const first = trips[0];
      const lastClosed = closed[closed.length - 1];
      return {
        market: m,
        trips,
        pnl: sumNetPnl(trips),
        tradeIn: first ? formatPoint(first.entry_ts, first.entry_price) : null,
        tradeOut:
          lastClosed?.exit_ts && lastClosed.exit_price
            ? formatPoint(lastClosed.exit_ts, lastClosed.exit_price)
            : null,
      };
    });

  const tradedRows = rows.filter((r) => r.trips.length > 0);
  if (tradedRows.length === 0) return null;

  const eventTotal = tradedRows.reduce((acc, r) => acc + r.pnl, 0);

  return (
    <section className="mb-6">
      <h2 className="mb-2 text-sm font-semibold text-ink-200">
        Strike summary · <span className="font-mono text-ink-400">{eventTicker}</span>
      </h2>
      <div className="overflow-x-auto rounded-lg border border-ink-800 bg-ink-950/50">
        <table className="w-full min-w-[640px] text-left text-xs">
          <thead>
            <tr className="border-b border-ink-800 bg-ink-900/70 text-[10px] uppercase tracking-wide text-ink-500">
              <th className="px-3 py-2 font-medium">Strike</th>
              <th className="px-3 py-2 text-right font-medium">Vol</th>
              <th className="px-3 py-2 font-medium">Trade in</th>
              <th className="px-3 py-2 font-medium">Trade out</th>
              <th className="px-3 py-2 text-right font-medium">Net P/L</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-800/70">
            {tradedRows.map(({ market, tradeIn, tradeOut, pnl, trips }) => (
              <tr key={market.ticker} className="text-ink-300">
                <td className="px-3 py-2">
                  <div className="font-mono text-ink-200">{market.ticker}</div>
                  <div className="text-[10px] text-ink-500">
                    {formatStrike(market.floor_strike, market.cap_strike)}
                    {trips.length > 1 ? ` · ${trips.length} trades` : ""}
                  </div>
                </td>
                <td className="px-3 py-2 text-right font-mono text-ink-400">
                  {formatVolume(market.volume)}
                </td>
                <td className="px-3 py-2 font-mono text-emerald-400/90">{tradeIn ?? "—"}</td>
                <td className="px-3 py-2 font-mono text-amber-300/90">{tradeOut ?? "—"}</td>
                <td className={`px-3 py-2 text-right font-mono ${pnlColorClass(pnlTone(pnl))}`}>
                  {formatPnl(pnl)}
                </td>
              </tr>
            ))}
          </tbody>
          {tradedRows.length > 1 ? (
            <tfoot>
              <tr className="border-t border-ink-700 bg-ink-900/50">
                <td colSpan={4} className="px-3 py-2 text-right text-[10px] uppercase text-ink-500">
                  Event total
                </td>
                <td className={`px-3 py-2 text-right font-mono ${pnlColorClass(pnlTone(eventTotal))}`}>
                  {formatPnl(eventTotal)}
                </td>
              </tr>
            </tfoot>
          ) : null}
        </table>
      </div>
    </section>
  );
}
