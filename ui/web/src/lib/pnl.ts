export function formatPnl(usd: number): string {
  if (usd > 0) return `+$${usd.toFixed(2)}`;
  if (usd < 0) return `-$${Math.abs(usd).toFixed(2)}`;
  return "$0.00";
}

export function formatPnlPct(pct: number): string {
  if (pct > 0) return `+${pct.toFixed(1)}%`;
  if (pct < 0) return `-${Math.abs(pct).toFixed(1)}%`;
  return "0.0%";
}

export function pnlTone(value: number): "profit" | "loss" | "flat" {
  if (value > 0) return "profit";
  if (value < 0) return "loss";
  return "flat";
}

export function pnlPctFromBasis(usd: number, basis: number): number | null {
  if (basis <= 0) return null;
  return (usd / basis) * 100;
}

export function pnlColorClass(tone: "profit" | "loss" | "flat"): string {
  if (tone === "profit") return "text-emerald-400";
  if (tone === "loss") return "text-red-400";
  return "text-ink-300";
}

export type ProfileLike = {
  initial_capital: string;
  equity: string;
  total_pnl?: string | null;
  pnl_pct?: string | null;
  capital_invested?: string | null;
};

/** Total return vs invested capital (deposits for live, initial for paper). */
export function experimentReturn(profile: ProfileLike): { totalUsd: number; pct: number } {
  if (profile.total_pnl != null && profile.pnl_pct != null) {
    return { totalUsd: Number(profile.total_pnl), pct: Number(profile.pnl_pct) };
  }
  const invested = Number(profile.capital_invested ?? profile.initial_capital);
  const equity = Number(profile.equity);
  const totalUsd = equity - invested;
  const pct = invested > 0 ? (totalUsd / invested) * 100 : 0;
  return { totalUsd, pct };
}

/** YES-chart cents for a round-trip marker price */
export function chartCentsForSide(side: "yes" | "no", priceDollars: number): number {
  if (side === "yes") return priceDollars * 100;
  return (1 - priceDollars) * 100;
}
