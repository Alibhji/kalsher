import type { Profile } from "../api/trading";
import { formatUsd } from "./format";

export const LIVE_LOW_FUNDS_USD = 5;
export const LIVE_CRITICAL_FUNDS_USD = 1;

export type LiveFundsStatus = "ok" | "warning" | "critical" | "empty";

export function liveAvailableFunds(profile: Profile | null): number {
  if (!profile) return 0;
  const raw = profile.available_funds ?? profile.cash;
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

export function liveFundsStatus(profile: Profile | null): LiveFundsStatus {
  const available = liveAvailableFunds(profile);
  if (available <= 0) return "empty";
  if (available < LIVE_CRITICAL_FUNDS_USD) return "critical";
  if (available < LIVE_LOW_FUNDS_USD) return "warning";
  return "ok";
}

export type LiveFundsBanner = { title: string; message: string; level: Exclude<LiveFundsStatus, "ok"> };

export function liveFundsBanner(profile: Profile | null): LiveFundsBanner | null {
  const status = liveFundsStatus(profile);
  const available = liveAvailableFunds(profile);
  if (status === "ok") return null;

  if (status === "empty") {
    return {
      level: "empty",
      title: "No available funds",
      message: "Your Kalshi account has $0 available. Deposit funds before placing live orders.",
    };
  }
  if (status === "critical") {
    return {
      level: "critical",
      title: "Insufficient funds",
      message: `Only ${formatUsd(available)} available — too low for most live orders. Add funds to continue trading.`,
    };
  }
  return {
    level: "warning",
    title: "Low balance",
    message: `${formatUsd(available)} available. Consider adding funds before larger live orders.`,
  };
}

export function estimateOrderCostUsd(qty: number, price: number, action: "buy" | "sell"): number {
  if (action === "sell") return 0;
  return qty * price;
}

export function canAffordOrder(profile: Profile | null, costUsd: number): { ok: boolean; message?: string } {
  const available = liveAvailableFunds(profile);
  if (costUsd <= available) return { ok: true };
  return {
    ok: false,
    message: `Order requires ~${formatUsd(costUsd)} but only ${formatUsd(available)} is available.`,
  };
}

export function parseTradingError(err: unknown): { title: string; message: string } {
  const raw = err instanceof Error ? err.message : String(err);
  const lower = raw.toLowerCase();

  if (lower.includes("x-confirm-live") || lower.includes("confirm live")) {
    return {
      title: "Live confirmation required",
      message: "Check “I confirm real money” before submitting a live order.",
    };
  }
  if (lower.includes("trading_live_enabled")) {
    return {
      title: "Live trading disabled",
      message: "Set TRADING_LIVE_ENABLED=true on the trader service to enable real-money orders.",
    };
  }
  if (lower.includes("insufficient position")) {
    return {
      title: "Insufficient position",
      message: raw.replace(/^.*?:\s*/i, "") || "You do not hold enough contracts to sell.",
    };
  }
  if (lower.includes("insufficient") && (lower.includes("fund") || lower.includes("balance") || lower.includes("cash"))) {
    return {
      title: "Insufficient funds",
      message: "Your Kalshi balance is too low for this order. Add funds or reduce quantity.",
    };
  }
  if (lower.includes("max_order_qty") || lower.includes("qty exceeds")) {
    return {
      title: "Order size rejected",
      message: "Quantity exceeds the configured maximum order size.",
    };
  }
  if (lower.includes("max_position")) {
    return {
      title: "Position limit exceeded",
      message: "This order would exceed the maximum position size for this market.",
    };
  }
  if (lower.includes("book_stale") || lower.includes("stale")) {
    return {
      title: "Market data stale",
      message: "Order book data is outdated. Wait a moment and try again.",
    };
  }
  if (lower.includes("trader unavailable") || lower.includes("502")) {
    return {
      title: "Trading service offline",
      message: "Could not reach the trader API. Check that the trader container is running.",
    };
  }
  if (lower.includes("kalshi api keys")) {
    return {
      title: "Kalshi not configured",
      message: "Add Kalshi API credentials to enable live trading.",
    };
  }
  if (lower.includes("410 gone") || lower.includes("/portfolio/orders")) {
    return {
      title: "Order API outdated",
      message: "Kalshi rejected the order endpoint. Restart the trader service after updating to the V2 orders API.",
    };
  }
  if (lower.includes("403")) {
    return {
      title: "Live order blocked",
      message: raw,
    };
  }

  return {
    title: "Order failed",
    message: raw || "An unexpected error occurred.",
  };
}
