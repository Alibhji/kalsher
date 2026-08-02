import { useEffect, useMemo, useRef, useState } from "react";
import {
  tradeLabel,
  type Order,
  type OrderType,
  type TradeAction,
  type TradeSide,
} from "../api/trading";
import { formatCloseDate, formatPreviewCents, formatUsd } from "../lib/format";
import {
  computeDefaultLimitPrice,
  computeOrderPreview,
  DEFAULT_LIMIT_OFFSET,
  formatLimitPrice,
  referenceMarketPrice,
  resolveOrderPrice,
} from "../lib/orderPreview";
import {
  canAffordOrder,
  estimateOrderCostUsd,
  liveAvailableFunds,
  liveFundsBanner,
  parseTradingError,
} from "../lib/tradingAlerts";
import { experimentReturn, formatPnl, formatPnlPct, pnlColorClass, pnlPctFromBasis, pnlTone } from "../lib/pnl";
import { parseTagInput, TagEditor } from "./TagList";
import { notifyError, notifyWarning } from "../store/notificationStore";
import { tradingStore } from "../store/tradingStore";
import { useTradingField, useTradingStore } from "../store/useTradingStore";
import { useMarketRow } from "../store/useMarketStore";

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
  const [limitOffset, setLimitOffset] = useState(String(DEFAULT_LIMIT_OFFSET));
  const limitPriceManual = useRef(false);
  const [confirmLive, setConfirmLive] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [closingPosKey, setClosingPosKey] = useState<string | null>(null);
  const [newPaperTags, setNewPaperTags] = useState("");
  const [savingTags, setSavingTags] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [closedOnly, setClosedOnly] = useState(false);
  const [showOrderPreview, setShowOrderPreview] = useState(() => {
    try {
      return localStorage.getItem("polymarketer.showOrderPreview") !== "0";
    } catch {
      return true;
    }
  });

  const openPositions = (profile?.positions ?? []).filter((p) => Number(p.qty) > 0);
  // Closed trades can sit far down the chronological list, so the P&L view is not capped.
  const visibleFills = closedOnly ? fills.filter((f) => f.trade_pnl != null) : fills.slice(0, 20);

  function positionQty(ticker: string, side: TradeSide): number {
    const pos = openPositions.find((p) => p.ticker === ticker && p.side === side);
    return pos ? Number(pos.qty) : 0;
  }

  function orderRemainingQty(order: Order): number {
    return Number(order.qty) - Number(order.filled_qty);
  }

  function isRestingLimit(order: Order): boolean {
    return order.type === "limit" && orderRemainingQty(order) > 0;
  }

  function closeLabel(order: Order): string {
    if (isRestingLimit(order)) return "Cancel";
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
  const heldQty = ticker ? positionQty(ticker, side) : 0;
  const canSell = heldQty > 0;

  function selectSellAll(nextSide: TradeSide = side) {
    const held = ticker ? positionQty(ticker, nextSide) : 0;
    if (held <= 0) return;
    setAction("sell");
    setQty(String(held));
  }

  function handleActionChange(next: TradeAction) {
    resetLimitPriceTracking();
    if (next === "sell") {
      if (!canSell) return;
      selectSellAll();
      return;
    }
    setAction("buy");
  }

  function handleSideChange(next: TradeSide) {
    resetLimitPriceTracking();
    setSide(next);
    if (action !== "sell") return;
    const held = ticker ? positionQty(ticker, next) : 0;
    if (held > 0) {
      setQty(String(held));
    } else {
      setAction("buy");
    }
  }

  function focusPosition(posTicker: string, posSide: TradeSide, posQty: number) {
    resetLimitPriceTracking();
    tradingStore.prepareTrade(posTicker, posSide, "sell", posQty);
  }

  const tradeSetupSeq = useTradingField("tradeSetupSeq");
  useEffect(() => {
    const setup = tradingStore.getTradeSetup();
    if (!setup) return;
    resetLimitPriceTracking();
    setSide(setup.side);
    setAction(setup.action);
    setQty(setup.qty);
  }, [tradeSetupSeq]);

  useEffect(() => {
    if (action !== "sell" || !ticker) return;
    if (heldQty > 0) {
      setQty(String(heldQty));
    } else {
      setAction("buy");
    }
  }, [ticker]); // eslint-disable-line react-hooks/exhaustive-deps -- reset sell qty when switching markets

  const market = useMarketRow(ticker);
  const qtyNum = Number(qty);
  const limitNum = Number(limitPrice);
  const limitOffsetNum = Number(limitOffset);
  const referencePrice = useMemo(
    () => referenceMarketPrice(side, action, market),
    [side, action, market],
  );
  const suggestedLimitPrice = useMemo(
    () =>
      computeDefaultLimitPrice(
        side,
        action,
        market,
        Number.isFinite(limitOffsetNum) ? limitOffsetNum : DEFAULT_LIMIT_OFFSET,
      ),
    [side, action, market, limitOffsetNum],
  );

  function applySuggestedLimitPrice() {
    if (suggestedLimitPrice == null) return;
    limitPriceManual.current = false;
    setLimitPrice(formatLimitPrice(suggestedLimitPrice));
  }

  function resetLimitPriceTracking() {
    limitPriceManual.current = false;
  }

  useEffect(() => {
    resetLimitPriceTracking();
  }, [ticker, side, action, orderType]);

  useEffect(() => {
    if (orderType !== "limit" || limitPriceManual.current || suggestedLimitPrice == null) return;
    setLimitPrice(formatLimitPrice(suggestedLimitPrice));
  }, [orderType, suggestedLimitPrice, market?.yes_bid_cents, market?.yes_ask_cents, market?.no_bid_cents, market?.no_ask_cents]);

  const availableFunds = liveAvailableFunds(profile);
  const preview = useMemo(
    () =>
      computeOrderPreview({
        side,
        action,
        orderType,
        qty: qtyNum,
        limitPrice: limitNum,
        market,
      }),
    [side, action, orderType, qtyNum, limitNum, market],
  );
  const liveReady = tradingConfig?.live_trading_enabled && tradingConfig?.kalshi_configured;
  const totalReturn = profile ? experimentReturn(profile) : null;

  function handleOrderTypeChange(next: OrderType) {
    setOrderType(next);
    if (next === "limit") {
      applySuggestedLimitPrice();
    }
  }

  function handleLimitOffsetChange(value: string) {
    setLimitOffset(value);
    limitPriceManual.current = false;
    const offset = Number(value);
    const next = computeDefaultLimitPrice(
      side,
      action,
      market,
      Number.isFinite(offset) ? offset : DEFAULT_LIMIT_OFFSET,
    );
    if (next != null) setLimitPrice(formatLimitPrice(next));
  }

  function toggleOrderPreview() {
    setShowOrderPreview((current) => {
      const next = !current;
      try {
        localStorage.setItem("polymarketer.showOrderPreview", next ? "1" : "0");
      } catch {
        /* ignore storage errors */
      }
      return next;
    });
  }

  const actionToggleValue = action === "sell" && !canSell ? "buy" : action;

  async function handleModeSwitch(mode: "paper" | "live") {
    if (mode === preferredMode) return;
    await tradingStore.switchMode(mode);
  }

  async function handleSubmit() {
    if (!ticker || Number(qty) <= 0) return;
    if (action === "sell" && Number(qty) > heldQty) {
      const msg = `You only hold ${heldQty} contract${heldQty === 1 ? "" : "s"} to sell.`;
      setSubmitError(msg);
      notifyWarning("Insufficient position", msg);
      return;
    }
    if (isLive && !confirmLive) {
      const msg = "Check “I confirm real money” before submitting a live order.";
      setSubmitError(msg);
      notifyWarning("Live confirmation required", msg);
      return;
    }
    if (action === "buy") {
      const estPrice = resolveOrderPrice(side, action, orderType, limitNum, market) ?? 0.5;
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
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-medium text-ink-400">Order ticket</p>
            <button
              type="button"
              title={showOrderPreview ? "Hide cost preview" : "Show cost preview"}
              aria-pressed={showOrderPreview}
              onClick={toggleOrderPreview}
              className={`rounded px-1 py-0 text-[9px] font-semibold uppercase leading-none tracking-wide transition-colors ${
                showOrderPreview ? "text-accent/80 hover:text-accent" : "text-ink-600 hover:text-ink-400"
              }`}
            >
              $
            </button>
          </div>
          <p className="truncate font-mono text-xs text-ink-500">{ticker || "Expand a market chart"}</p>

          <ToggleRow
            options={[
              ["yes", "YES"],
              ["no", "NO"],
            ]}
            value={side}
            onChange={(v) => handleSideChange(v as TradeSide)}
          />
          <ToggleRow
            options={[
              ["buy", "Buy"],
              ["sell", "Sell"],
            ]}
            value={actionToggleValue}
            disabledIds={canSell ? [] : ["sell"]}
            onChange={(v) => handleActionChange(v as TradeAction)}
          />
          <ToggleRow
            options={[
              ["market", "Market"],
              ["limit", "Limit"],
            ]}
            value={orderType}
            onChange={(v) => handleOrderTypeChange(v as OrderType)}
          />

          {orderType === "limit" ? (
            <div className="space-y-2">
              {referencePrice != null ? (
                <p className="text-[10px] text-ink-600">
                  Market {formatPreviewCents(referencePrice * 100)}
                  {action === "buy" ? " · limit below" : " · limit above"}
                </p>
              ) : (
                <p className="text-[10px] text-ink-600">Waiting for market quotes…</p>
              )}
              <label className="block text-[10px] text-ink-500">
                Offset (0.05 = 5%)
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  max="0.5"
                  className="mt-0.5 w-full rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm"
                  value={limitOffset}
                  onChange={(e) => handleLimitOffsetChange(e.target.value)}
                />
              </label>
              <label className="block text-[10px] text-ink-500">
                Limit $
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  max="0.99"
                  className="mt-0.5 w-full rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm"
                  value={limitPrice}
                  onChange={(e) => {
                    limitPriceManual.current = true;
                    setLimitPrice(e.target.value);
                  }}
                  placeholder="Limit $"
                />
              </label>
              <button
                type="button"
                className="text-[10px] text-accent hover:underline"
                onClick={applySuggestedLimitPrice}
                disabled={suggestedLimitPrice == null}
              >
                Reset to market ± offset
              </button>
            </div>
          ) : null}

          <input
            type="number"
            min="1"
            max={action === "sell" && canSell ? heldQty : undefined}
            className="w-full rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            placeholder="Qty"
          />
          {canSell ? (
            <p className="text-[10px] text-ink-600">
              {heldQty} contract{heldQty === 1 ? "" : "s"} available to sell
            </p>
          ) : null}

          {showOrderPreview ? (
            preview ? (
              <OrderPreviewPanel
                preview={preview}
                action={action}
                isLive={isLive}
                availableFunds={availableFunds}
              />
            ) : qtyNum > 0 && ticker ? (
              <p className="text-xs text-ink-600">Waiting for market quotes…</p>
            ) : null
          ) : null}

          {isLive ? (
            <label className="flex items-center gap-2 text-xs text-red-300">
              <input type="checkbox" checked={confirmLive} onChange={(e) => setConfirmLive(e.target.checked)} />
              I confirm real money
            </label>
          ) : null}

          {submitError ? <InlineAlert level="error" title="Order rejected" message={submitError} compact /> : null}

          <button
            type="button"
            disabled={!ticker || submitting || (action === "sell" && !canSell)}
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
                        onClick={() => focusPosition(pos.ticker, pos.side, qty)}
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
                          isRestingLimit(order)
                            ? "Cancel resting limit order"
                            : positionQty(order.ticker, order.side) > 0
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

function OrderPreviewPanel({
  preview,
  action,
  isLive,
  availableFunds,
}: {
  preview: NonNullable<ReturnType<typeof computeOrderPreview>>;
  action: TradeAction;
  isLive: boolean;
  availableFunds: number;
}) {
  const costOrProceeds = action === "buy" ? preview.totalCostUsd : preview.proceedsUsd;
  const insufficient = action === "buy" && costOrProceeds > availableFunds;

  return (
    <div className="space-y-2.5 rounded-lg border border-ink-700/80 bg-ink-900/70 px-3 py-3">
      <p className="text-xs text-ink-400">
        {isLive ? "Predictions account" : "Paper account"}
        <span className="text-ink-600"> · </span>
        <span className="font-medium text-ink-200">{formatUsd(availableFunds)} available</span>
      </p>

      <PreviewRow label="Average price" value={formatPreviewCents(preview.priceCents)} large />

      <PreviewRow
        label={action === "buy" ? "Cost" : "Proceeds"}
        value={formatUsd(costOrProceeds)}
        large
      />

      {preview.feeUsd > 0 ? (
        <p className="text-[10px] text-ink-600">Includes {formatUsd(preview.feeUsd)} est. taker fee</p>
      ) : null}

      {action === "buy" ? (
        <div>
          <p className="text-xs text-ink-500">Max payout</p>
          <p className="text-xs text-ink-500">{formatCloseDate(preview.closeDate)}</p>
          <p className="font-mono text-lg font-medium text-ink-100">{formatUsd(preview.maxPayoutUsd)}</p>
        </div>
      ) : null}

      {insufficient ? (
        <p className="text-xs text-red-400">
          Need {formatUsd(costOrProceeds)} — only {formatUsd(availableFunds)} available
        </p>
      ) : null}
    </div>
  );
}

function PreviewRow({ label, value, large = false }: { label: string; value: string; large?: boolean }) {
  return (
    <div>
      <p className="text-xs text-ink-500">{label}</p>
      <p className={`font-mono ${large ? "text-lg font-medium text-ink-100" : "text-sm text-ink-200"}`}>{value}</p>
    </div>
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
  disabledIds = [],
}: {
  options: [string, string][];
  value: string;
  onChange: (v: string) => void;
  disabledIds?: string[];
}) {
  return (
    <div className="flex gap-1">
      {options.map(([id, label]) => {
        const disabled = disabledIds.includes(id);
        return (
          <button
            key={id}
            type="button"
            disabled={disabled}
            onClick={() => {
              if (!disabled) onChange(id);
            }}
            className={`flex-1 rounded px-2 py-1 text-xs font-medium ${
              disabled
                ? "cursor-not-allowed bg-ink-900/50 text-ink-700"
                : value === id
                  ? "bg-accent/20 text-accent"
                  : "bg-ink-900 text-ink-500"
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
