import type { MarketRow } from "../api";
import type { OrderType, TradeAction, TradeSide } from "../api/trading";

/** Kalshi taker fee: ceil to cent of 0.07 × qty × P × (1 − P). */
export function kalshiTakerFee(qty: number, priceDollars: number): number {
  if (qty <= 0 || priceDollars <= 0 || priceDollars >= 1) return 0;
  const raw = 0.07 * qty * priceDollars * (1 - priceDollars);
  return Math.ceil(raw * 100) / 100;
}

function centsToDollars(cents: number | null | undefined): number | null {
  if (cents == null) return null;
  return cents / 100;
}

function mid(bid: number | null, ask: number | null): number | null {
  if (bid != null && ask != null) return (bid + ask) / 2;
  return bid ?? ask;
}

export function resolveOrderPrice(
  side: TradeSide,
  action: TradeAction,
  orderType: OrderType,
  limitPrice: number,
  market: MarketRow | undefined,
): number | null {
  if (orderType === "limit" && Number.isFinite(limitPrice) && limitPrice > 0 && limitPrice < 1) {
    return limitPrice;
  }
  return referenceMarketPrice(side, action, market);
}

/** Current quote used as the limit anchor (ask for buys, bid for sells). */
export function referenceMarketPrice(
  side: TradeSide,
  action: TradeAction,
  market: MarketRow | undefined,
): number | null {
  if (!market) return null;

  const yesBid = centsToDollars(market.yes_bid_cents);
  const yesAsk = centsToDollars(market.yes_ask_cents);
  const noBid = centsToDollars(market.no_bid_cents);
  const noAsk = centsToDollars(market.no_ask_cents);

  if (side === "yes") {
    if (action === "buy") return yesAsk ?? mid(yesBid, yesAsk) ?? 0.5;
    return yesBid ?? mid(yesBid, yesAsk) ?? 0.5;
  }
  if (action === "buy") return noAsk ?? mid(noBid, noAsk) ?? (yesBid != null ? 1 - yesBid : 0.5);
  return noBid ?? mid(noBid, noAsk) ?? (yesAsk != null ? 1 - yesAsk : 0.5);
}

/** Default offset fraction: 0.05 = 5% below (buy) or above (sell) the reference quote. */
export const DEFAULT_LIMIT_OFFSET = 0.05;

export function computeDefaultLimitPrice(
  side: TradeSide,
  action: TradeAction,
  market: MarketRow | undefined,
  offsetFraction: number = DEFAULT_LIMIT_OFFSET,
): number | null {
  const ref = referenceMarketPrice(side, action, market);
  if (ref == null || !Number.isFinite(ref)) return null;

  const pct = Math.max(0, Math.min(0.5, offsetFraction));
  const raw = action === "buy" ? ref * (1 - pct) : ref * (1 + pct);
  const clamped = Math.min(0.99, Math.max(0.01, raw));
  return Math.round(clamped * 100) / 100;
}

export function formatLimitPrice(value: number): string {
  return value.toFixed(2);
}

export type OrderPreview = {
  qty: number;
  priceDollars: number;
  priceCents: number;
  notionalUsd: number;
  feeUsd: number;
  totalCostUsd: number;
  proceedsUsd: number;
  maxPayoutUsd: number;
  closeDate: string | null;
};

export function computeOrderPreview(params: {
  side: TradeSide;
  action: TradeAction;
  orderType: OrderType;
  qty: number;
  limitPrice: number;
  market: MarketRow | undefined;
}): OrderPreview | null {
  const { side, action, orderType, qty, limitPrice, market } = params;
  if (!Number.isFinite(qty) || qty <= 0) return null;

  const priceDollars = resolveOrderPrice(side, action, orderType, limitPrice, market);
  if (priceDollars == null || priceDollars <= 0) return null;

  const notionalUsd = qty * priceDollars;
  const feeUsd = kalshiTakerFee(qty, priceDollars);
  const priceCents = priceDollars * 100;

  return {
    qty,
    priceDollars,
    priceCents,
    notionalUsd,
    feeUsd,
    totalCostUsd: action === "buy" ? notionalUsd + feeUsd : 0,
    proceedsUsd: action === "sell" ? notionalUsd - feeUsd : 0,
    maxPayoutUsd: qty,
    closeDate: market?.close_time ?? null,
  };
}
