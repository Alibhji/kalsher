import { useEffect, useState } from "react";
import {
  tradeLabel,
  type Order,
  type OrderType,
  type TradeAction,
  type TradeSide,
} from "../api/trading";
import { formatUsd } from "../lib/format";
import {
  canAffordOrder,
  estimateOrderCostUsd,
  liveFundsBanner,
  parseTradingError,
} from "../lib/tradingAlerts";
import { experimentReturn, formatPnl, formatPnlPct, pnlColorClass, pnlPctFromBasis, pnlTone } from "../lib/pnl";
import { parseTagInput, TagEditor } from "./TagList";
import { notifyError, notifyWarning } from "../store/notificationStore";
import { tradingStore } from "../store/tradingStore";
import { useTradingStore } from "../store/useTradingStore";

type Props = {
  mobileOpen?: boolean;
  onCloseMobile?: () => void;
};

export function TradingSidebar({ mobileOpen = true, onCloseMobile }: Props) {
  const {
    experiments,
    profile,
    fills,
    openOrders,
    activeExperimentId,
    selectedTicker,
    loading,
    error,
    tradingConfig,
    preferredMode,
  } = useTradingStore();
  const active = experiments.find((e) => e.id === activeExperimentId);

  const [side, setSide] = useState<TradeSide>("yes");
  const [action, setAction] = useState<TradeAction>("buy");
  const [orderType, setOrderType] = useState<OrderType>("market");
  const [qty, setQty] = useState("10");
  const [limitPrice, setLimitPrice] = useState("0.50");
  const [confirmLive, setConfirmLive] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [closingPosKey, setClosingPosKey] = useState<string | null>(null);
  const [newPaperTags, setNewPaperTags] = useState("");
  const [savingTags, setSavingTags] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [closedOnly, setClosedOnly] = useState(false);

  const openPositions = (profile?.positions ?? []).filter((p) => Number(p.qty) > 0);
  // Closed trades can sit far down the chronological list, so the P&L view is not capped.
  const visibleFills = closedOnly ? fills.filter((f) => f.trade_pnl != null) : fills.slice(0, 20);

  function positionQty(ticker: string, side: TradeSide): number {
    const pos = profile?.positions.find((p) => p.ticker === ticker && p.side === side);
    return pos ? Number(pos.qty) : 0;
  }

  function closeLabel(order: Order): string {
    const held = positionQty(order.ticker, order.side);
    if (held > 0) {
      return order.action === "buy" ? "Sell" : "Buy";
    }
    return "Cancel";
  }

  function positionKey(ticker: string, side: TradeSide): string {
    return `${ticker}:${side}`;
  }

  useEffect(() => {
    void tradingStore.bootstrap();
    return () => tradingStore.stopPolling();
  }, []);

  const isLive = active?.mode === "live";
  const ticker = selectedTicker ?? "";
  const liveReady = tradingConfig?.live_trading_enabled && tradingConfig?.kalshi_configured;
  const totalReturn = profile ? experimentReturn(profile) : null;

  async function handleModeSwitch(mode: "paper" | "live") {
    if (mode === preferredMode) return;
    await tradingStore.switchMode(mode);
  }

  async function handleSubmit() {
    if (!ticker || Number(qty) <= 0) return;
    if (isLive && !confirmLive) {
      const msg = "Check “I confirm real money” before submitting a live order.";
      setSubmitError(msg);
      notifyWarning("Live confirmation required", msg);
      return;
    }
    if (isLive && action === "buy") {
      const estPrice = orderType === "limit" ? Number(limitPrice) : 0.5;
      const cost = estimateOrderCostUsd(Number(qty), estPrice, "buy");
      const afford = canAffordOrder(profile, cost);
      if (!afford.ok) {
        setSubmitError(afford.message ?? "Insufficient funds");
        notifyError("Insufficient funds", afford.message);
        return;
      }
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      await tradingStore.submitOrder(
        {
          ticker,
          side,
          action,
          type: orderType,
          qty: Number(qty),
          limit_price: orderType === "limit" ? Number(limitPrice) : undefined,
        },
        isLive,
      );
    } catch (err) {
      const parsed = parseTradingError(err);
      setSubmitError(parsed.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleClosePosition() {
    if (!ticker) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await tradingStore.closePosition(ticker, side, isLive);
    } catch (err) {
      const parsed = parseTradingError(err);
      setSubmitError(parsed.message);
    } finally {
      setSubmitting(false);
    }
  }

  const fundsBanner = isLive ? liveFundsBanner(profile) : null;

  const panelClass = mobileOpen
    ? "flex w-72 shrink-0 flex-col border-r border-ink-800 bg-ink-950/95"
    : "hidden lg:flex w-72 shrink-0 flex-col border-r border-ink-800 bg-ink-950/95";

  return (
    <aside className={panelClass}>
      <div className="flex items-center justify-between border-b border-ink-800 px-4 py-3">
        <h2 className="text-sm font-semibold text-ink-100">Trade</h2>
        {onCloseMobile ? (
          <button type="button" className="text-xs text-ink-500 lg:hidden" onClick={onCloseMobile}>
            Close
          </button>
        ) : null}
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {loading ? <p className="text-xs text-ink-500">Loading trading…</p> : null}

        <div>
          <label className="mb-1 block text-xs text-ink-500">Experiment</label>
          <select
            className="w-full rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm text-ink-100"
            value={activeExperimentId ?? ""}
            onChange={(e) => void tradingStore.setActiveExperiment(e.target.value)}
          >
            {experiments.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name} ({e.mode})
                {(e.tags?.length ?? 0) > 0 ? ` · ${e.tags!.join(", ")}` : ""}
              </option>
            ))}
          </select>
          {!isLive ? (
            <div className="mt-2 space-y-2">
              <label className="block text-xs text-ink-500">
                Tags for new experiment
                <input
                  type="text"
                  value={newPaperTags}
                  onChange={(e) => setNewPaperTags(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void tradingStore
                        .createPaperExperiment(undefined, parseTagInput(newPaperTags))
                        .then(() => setNewPaperTags(""));
                    }
                  }}
                  placeholder="Add tags, press Enter to create"
                  className="mt-1 w-full rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm text-ink-100"
                />
              </label>
              <button
                type="button"
                className="text-xs text-accent hover:underline"
                onClick={() =>
                  void tradingStore.createPaperExperiment(undefined, parseTagInput(newPaperTags)).then(() =>
                    setNewPaperTags(""),
                  )
                }
              >
                + New paper experiment
              </button>
              {active ? (
                <div>
                  <p className="mb-1 text-xs text-ink-500">Experiment tags</p>
                  <TagEditor
                    tags={active.tags ?? []}
                    saving={savingTags}
                    size="sm"
                    onSave={async (tags) => {
                      setSavingTags(true);
                      try {
                        await tradingStore.updatePaperTags(active.id, tags);
                      } finally {
                        setSavingTags(false);
                      }
                    }}
                  />
                  <div className="mt-2">
                    <button
                      type="button"
                      disabled={deleting}
                      className="rounded border border-red-900/60 px-2 py-1 text-xs text-red-400 hover:bg-red-950/40"
                      onClick={() => {
                        if (
                          !window.confirm(
                            `Delete paper experiment "${active.name}" permanently? All fills and history will be removed from the database.`,
                          )
                        ) {
                          return;
                        }
                        setDeleting(true);
                        void tradingStore.deletePaperExperiment(active.id).finally(() => setDeleting(false));
                      }}
                    >
                      {deleting ? "Deleting…" : "Delete"}
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <button
              type="button"
              className="mt-2 text-xs text-accent hover:underline"
              onClick={() => void tradingStore.createPaperExperiment()}
            >
              + New paper experiment
            </button>
          )}
          <a
            href={activeExperimentId ? `#/history/${activeExperimentId}` : "#/history"}
            className="mt-1 block text-xs text-ink-500 hover:text-accent"
          >
            View experiment history →
          </a>
        </div>

        <div className="space-y-2">
          <ToggleRow
            options={[
              ["paper", "Paper"],
              ["live", "Live"],
            ]}
            value={preferredMode}
            onChange={(v) => void handleModeSwitch(v as "paper" | "live")}
          />
          {preferredMode === "live" && !liveReady ? (
            <p className="text-xs text-amber-400">
              Live requires TRADING_LIVE_ENABLED=true and Kalshi API keys.
            </p>
          ) : null}
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`rounded px-2 py-0.5 text-xs font-bold uppercase ${
              isLive ? "animate-pulse border border-red-500 bg-red-950 text-red-300" : "bg-emerald-950 text-emerald-300"
            }`}
          >
            {isLive ? "LIVE" : "PAPER"}
          </span>
        </div>

        {fundsBanner ? (
          <FundsAlert banner={fundsBanner} />
        ) : null}

        {error ? <InlineAlert level="error" title="Trading error" message={error} /> : null}

        {profile ? (
          <div className="grid grid-cols-2 gap-2 text-xs">
            {isLive && profile.available_funds != null ? (
              <Stat label="Available" value={formatUsd(Number(profile.available_funds))} />
            ) : (
              <Stat label="Cash" value={formatUsd(Number(profile.cash))} />
            )}
            <Stat label="Equity" value={formatUsd(Number(profile.equity))} />
            {isLive && profile.portfolio_value != null ? (
              <Stat label="Positions" value={formatUsd(Number(profile.portfolio_value))} />
            ) : null}
            {isLive && profile.capital_invested != null ? (
              <Stat label="Invested" value={formatUsd(Number(profile.capital_invested))} />
            ) : null}
            {totalReturn ? (
              <PnlStat label="Total P&L" usd={totalReturn.totalUsd} pct={totalReturn.pct} />
            ) : null}
            <PnlStat
              label="Realized"
              usd={Number(profile.realized_pnl)}
              pct={pnlPctFromBasis(
                Number(profile.realized_pnl),
                Number(profile.capital_invested ?? profile.initial_capital),
              )}
            />
            <PnlStat
              label="Unrealized"
              usd={Number(profile.unrealized_pnl)}
              pct={pnlPctFromBasis(
                Number(profile.unrealized_pnl),
                Number(profile.capital_invested ?? profile.initial_capital),
              )}
            />
            <Stat label="Fees" value={formatUsd(Number(profile.fees_paid))} />
          </div>
        ) : null}

        <div className="space-y-3 rounded-lg border border-ink-800 p-3">
          <p className="text-xs font-medium text-ink-400">Order ticket</p>
          <p className="truncate font-mono text-xs text-ink-500">{ticker || "Expand a market chart"}</p>

          <ToggleRow
            options={[
              ["yes", "YES"],
              ["no", "NO"],
            ]}
            value={side}
            onChange={(v) => setSide(v as TradeSide)}
          />
          <ToggleRow
            options={[
              ["buy", "Buy"],
              ["sell", "Sell"],
            ]}
            value={action}
            onChange={(v) => setAction(v as TradeAction)}
          />
          <ToggleRow
            options={[
              ["market", "Market"],
              ["limit", "Limit"],
            ]}
            value={orderType}
            onChange={(v) => setOrderType(v as OrderType)}
          />

          {orderType === "limit" ? (
            <input
              type="number"
              step="0.01"
              min="0.01"
              max="0.99"
              className="w-full rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm"
              value={limitPrice}
              onChange={(e) => setLimitPrice(e.target.value)}
              placeholder="Limit $"
            />
          ) : null}

          <input
            type="number"
            min="1"
            className="w-full rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            placeholder="Qty"
          />

          {isLive ? (
            <label className="flex items-center gap-2 text-xs text-red-300">
              <input type="checkbox" checked={confirmLive} onChange={(e) => setConfirmLive(e.target.checked)} />
              I confirm real money
            </label>
          ) : null}

          {submitError ? <InlineAlert level="error" title="Order rejected" message={submitError} compact /> : null}

          <button
            type="button"
            disabled={!ticker || submitting}
            onClick={() => void handleSubmit()}
            className="w-full rounded bg-accent px-3 py-2 text-sm font-medium text-ink-950 disabled:opacity-40"
          >
            {submitting ? "Submitting…" : `${action.toUpperCase()} ${side.toUpperCase()}`}
          </button>

          <button
            type="button"
            disabled={!ticker || submitting || action !== "sell"}
            onClick={() => void handleClosePosition()}
            className="w-full rounded border border-ink-600 px-3 py-1.5 text-xs text-ink-300 disabled:opacity-40"
          >
            Close {side.toUpperCase()} position
          </button>
        </div>

        <div>
          <p className="mb-2 text-xs font-medium text-ink-400">
            Open positions{openPositions.length > 0 ? ` (${openPositions.length})` : ""}
          </p>
          <ul className="max-h-44 space-y-2 overflow-y-auto text-xs">
            {openPositions.length === 0 ? (
              <li className="text-ink-600">No open positions</li>
            ) : (
              openPositions.map((pos) => {
                const qty = Number(pos.qty);
                const avgCents = Math.round(Number(pos.avg_price) * 100);
                const markCents = pos.mark_price != null ? Math.round(Number(pos.mark_price) * 100) : null;
                const unreal = pos.unrealized_pnl != null ? Number(pos.unrealized_pnl) : null;
                const basis = pos.cost_basis != null ? Number(pos.cost_basis) : null;
                const unrealPct =
                  unreal != null && basis != null && basis > 0 ? pnlPctFromBasis(unreal, basis) : null;
                const isSelected = selectedTicker === pos.ticker;
                const key = positionKey(pos.ticker, pos.side);
                return (
                  <li
                    key={key}
                    className={`rounded border px-2 py-1.5 ${
                      isSelected
                        ? "border-accent/50 bg-accent/10"
                        : "border-ink-800/80 bg-ink-900/40"
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <button
                        type="button"
                        className="min-w-0 flex-1 text-left"
                        onClick={() => tradingStore.focusMarket(pos.ticker)}
                      >
                        <span className="font-semibold text-emerald-400">
                          LONG {pos.side.toUpperCase()}
                        </span>
                        <span className="text-ink-500"> · </span>
                        <span className="text-ink-200">{qty} ct</span>
                        <br />
                        <span className="font-mono text-ink-500">{pos.ticker.slice(0, 20)}…</span>
                        <br />
                        <span className="text-ink-600">
                          avg {avgCents}¢
                          {markCents != null ? ` · mark ${markCents}¢` : ""}
                        </span>
                        {unreal != null ? (
                          <>
                            <br />
                            <span className={pnlColorClass(pnlTone(unreal))}>
                              {formatPnl(unreal)}
                              {unrealPct != null ? (
                                <span className="ml-1 text-[10px] opacity-90">{formatPnlPct(unrealPct)}</span>
                              ) : null}
                              <span className="ml-1 text-ink-600">unrealized</span>
                            </span>
                          </>
                        ) : null}
                      </button>
                      <button
                        type="button"
                        title={`Close with market ${pos.side === "yes" ? "sell" : "buy"}`}
                        disabled={closingPosKey === key}
                        onClick={(e) => {
                          e.stopPropagation();
                          setClosingPosKey(key);
                          void tradingStore.closePosition(pos.ticker, pos.side, isLive).finally(() => {
                            setClosingPosKey(null);
                          });
                        }}
                        className="shrink-0 rounded border border-ink-700 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-400 transition-colors hover:border-red-700 hover:bg-red-950/50 hover:text-red-300 disabled:opacity-40"
                      >
                        {closingPosKey === key ? "…" : pos.side === "yes" ? "Sell" : "Buy"}
                      </button>
                    </div>
                  </li>
                );
              })
            )}
          </ul>
        </div>

        <div>
          <p className="mb-2 text-xs font-medium text-ink-400">
            Open orders{openOrders.length > 0 ? ` (${openOrders.length})` : ""}
          </p>
          <ul className="max-h-40 space-y-2 overflow-y-auto text-xs">
            {openOrders.length === 0 ? (
              <li className="text-ink-600">No open orders</li>
            ) : (
              openOrders.map((order) => {
                const remaining = Number(order.qty) - Number(order.filled_qty);
                const priceLabel =
                  order.type === "limit" && order.limit_price
                    ? `${Math.round(Number(order.limit_price) * 100)}¢ limit`
                    : "market";
                const isSelected = selectedTicker === order.ticker;
                return (
                  <li
                    key={order.id}
                    className={`rounded border px-2 py-1.5 ${
                      isSelected
                        ? "border-accent/50 bg-accent/10"
                        : "border-ink-800/80 bg-ink-900/40"
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <button
                        type="button"
                        className="min-w-0 flex-1 text-left"
                        onClick={() => tradingStore.focusMarket(order.ticker)}
                      >
                        <span className="font-semibold text-ink-100">
                          {tradeLabel(order.side, order.action)}
                        </span>
                        <span className="text-ink-500"> · </span>
                        <span className="text-ink-400">{remaining} left</span>
                        <br />
                        <span className="font-mono text-ink-500">{order.ticker.slice(0, 20)}…</span>
                        <br />
                        <span className="text-ink-600">
                          {priceLabel}
                          {order.mode === "live" ? " · live" : ""}
                        </span>
                      </button>
                      <button
                        type="button"
                        title={
                          positionQty(order.ticker, order.side) > 0
                            ? `Close ${order.action === "buy" ? "long" : "short"} with market ${order.action === "buy" ? "sell" : "buy"}`
                            : "Cancel resting order"
                        }
                        disabled={cancellingId === order.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          setCancellingId(order.id);
                          void tradingStore.closeOpenOrder(order, isLive).finally(() => {
                            setCancellingId(null);
                          });
                        }}
                        className="shrink-0 rounded border border-ink-700 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-400 transition-colors hover:border-red-700 hover:bg-red-950/50 hover:text-red-300 disabled:opacity-40"
                      >
                        {cancellingId === order.id ? "…" : closeLabel(order)}
                      </button>
                    </div>
                  </li>
                );
              })
            )}
          </ul>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs font-medium text-ink-400">Recent fills</p>
            <button
              type="button"
              onClick={() => setClosedOnly((v) => !v)}
              className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                closedOnly ? "bg-accent/20 text-accent" : "bg-ink-900 text-ink-500"
              }`}
            >
              P&L only
            </button>
          </div>
          <ul className="max-h-48 space-y-2 overflow-y-auto text-xs">
            {visibleFills.length === 0 ? (
              <li className="text-ink-600">{closedOnly ? "No closed trades yet" : "No fills yet"}</li>
            ) : (
              visibleFills.map((f) => {
                const label = tradeLabel(f.side, f.action);
                const priceCents = Math.round(Number(f.price) * 100);
                const pnlUsd = f.trade_pnl != null ? Number(f.trade_pnl) : null;
                const pnlPct = f.trade_pnl_pct != null ? Number(f.trade_pnl_pct) : null;
                return (
                  <li key={f.id} className="text-ink-300">
                    <span className="font-semibold text-ink-100">{label}</span>
                    <span className="text-ink-500"> · </span>
                    <span className="font-mono text-ink-400">{f.ticker.slice(0, 18)}…</span>
                    <br />
                    <span className="text-ink-400">
                      {f.qty} @ {priceCents}¢ · cost {formatUsd(Number(f.cost))}
                    </span>
                    <span className="text-ink-600"> · {new Date(f.ts).toLocaleTimeString()}</span>
                    {pnlUsd != null ? (
                      <>
                        <br />
                        <span className={`font-mono ${pnlColorClass(pnlTone(pnlUsd))}`}>
                          {formatPnl(pnlUsd)}
                          {pnlPct != null ? (
                            <span className="ml-1 text-[10px] opacity-90">{formatPnlPct(pnlPct)}</span>
                          ) : null}
                          <span className="ml-1 text-ink-600">realized</span>
                        </span>
                      </>
                    ) : null}
                  </li>
                );
              })
            )}
          </ul>
        </div>
      </div>
    </aside>
  );
}

function FundsAlert({
  banner,
}: {
  banner: { title: string; message: string; level: "warning" | "critical" | "empty" };
}) {
  const isCritical = banner.level === "critical" || banner.level === "empty";
  return (
    <InlineAlert
      level={isCritical ? "error" : "warning"}
      title={banner.title}
      message={banner.message}
    />
  );
}

function InlineAlert({
  level,
  title,
  message,
  compact = false,
}: {
  level: "error" | "warning" | "info";
  title: string;
  message: string;
  compact?: boolean;
}) {
  const styles =
    level === "error"
      ? "border-red-800/60 bg-red-950/50 text-red-100"
      : level === "warning"
        ? "border-amber-800/60 bg-amber-950/50 text-amber-100"
        : "border-sky-800/60 bg-sky-950/50 text-sky-100";
  return (
    <div className={`rounded-lg border px-3 ${compact ? "py-2" : "py-2.5"} ${styles}`}>
      <p className={`font-semibold ${compact ? "text-xs" : "text-sm"}`}>{title}</p>
      <p className={`mt-0.5 leading-relaxed text-ink-300/90 ${compact ? "text-xs" : "text-xs"}`}>{message}</p>
    </div>
  );
}

function PnlStat({
  label,
  usd,
  pct,
}: {
  label: string;
  usd: number;
  pct?: number | null;
}) {
  const tone = pnlTone(usd);
  return (
    <div className="rounded border border-ink-800/80 bg-ink-900/50 px-2 py-1.5">
      <p className="text-ink-600">{label}</p>
      <p className={`font-mono ${pnlColorClass(tone)}`}>
        {formatPnl(usd)}
        {pct != null ? <span className="ml-1 text-[10px] opacity-90">{formatPnlPct(pct)}</span> : null}
      </p>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "profit" | "loss" | "flat";
}) {
  const color =
    tone === "profit" ? "text-emerald-400" : tone === "loss" ? "text-red-400" : "text-ink-200";
  return (
    <div className="rounded border border-ink-800/80 bg-ink-900/50 px-2 py-1.5">
      <p className="text-ink-600">{label}</p>
      <p className={`font-mono ${color}`}>{value}</p>
    </div>
  );
}

function ToggleRow({
  options,
  value,
  onChange,
}: {
  options: [string, string][];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex gap-1">
      {options.map(([id, label]) => (
        <button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          className={`flex-1 rounded px-2 py-1 text-xs font-medium ${
            value === id ? "bg-accent/20 text-accent" : "bg-ink-900 text-ink-500"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
