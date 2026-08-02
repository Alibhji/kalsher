import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { tradeLabel, type Order, type TradeSide } from "../api/trading";
import { formatPnl, formatPnlPct, pnlColorClass, pnlPctFromBasis, pnlTone } from "../lib/pnl";
import { marketStore } from "../store/marketStore";
import { tradingStore } from "../store/tradingStore";
import { useMarketListVersion } from "../store/useMarketStore";
import { useTradingStore } from "../store/useTradingStore";

const STORAGE_KEY = "polymarketer.exposurePanelOpen";
const POS_KEY = "polymarketer.exposurePanelPos";
const SIDEBAR_W = 288; // lg:w-72
const PANEL_MAX_W = 1152; // max-w-6xl

type Point = { x: number; y: number };

function sidebarOffset(): number {
  return window.innerWidth >= 1024 ? SIDEBAR_W : 0;
}

function defaultPosition(): Point {
  const panelW = Math.min(window.innerWidth - 16, PANEL_MAX_W);
  const x = sidebarOffset() + Math.max(8, (window.innerWidth - sidebarOffset() - panelW) / 2);
  return { x, y: 8 };
}

function loadPosition(): Point {
  try {
    const raw = localStorage.getItem(POS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Point;
      if (typeof parsed.x === "number" && typeof parsed.y === "number") {
        return parsed;
      }
    }
  } catch {
    // ignore
  }
  return defaultPosition();
}

function clampPosition(point: Point, width: number, height: number): Point {
  const minX = sidebarOffset() + 4;
  const maxX = Math.max(minX, window.innerWidth - width - 4);
  const minY = 4;
  const maxY = Math.max(minY, window.innerHeight - height - 4);
  return {
    x: Math.min(maxX, Math.max(minX, point.x)),
    y: Math.min(maxY, Math.max(minY, point.y)),
  };
}

function marketLabel(ticker: string): string {
  const row = marketStore.getRow(ticker);
  const title = row?.title ?? row?.event_title;
  if (title) return title.length > 48 ? `${title.slice(0, 48)}…` : title;
  return ticker.length > 22 ? `${ticker.slice(0, 22)}…` : ticker;
}

function orderRemainingQty(order: Order): number {
  return Number(order.qty) - Number(order.filled_qty);
}

function isRestingLimit(order: Order): boolean {
  return order.type === "limit" && orderRemainingQty(order) > 0;
}

function orderActionLabel(order: Order, heldQty: number): string {
  if (isRestingLimit(order)) return "Cancel";
  if (heldQty > 0) return order.action === "buy" ? "Sell" : "Buy";
  return "Cancel";
}

function positionKey(ticker: string, side: TradeSide): string {
  return `${ticker}:${side}`;
}

function DragGrip() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 10 16"
      className="h-4 w-2.5 shrink-0 text-ink-600"
      fill="currentColor"
    >
      <circle cx="2" cy="2" r="1.2" />
      <circle cx="8" cy="2" r="1.2" />
      <circle cx="2" cy="8" r="1.2" />
      <circle cx="8" cy="8" r="1.2" />
      <circle cx="2" cy="14" r="1.2" />
      <circle cx="8" cy="14" r="1.2" />
    </svg>
  );
}

export function OpenExposurePanel() {
  const { profile, openOrders, selectedTicker, activeExperimentId, experiments } = useTradingStore();
  useMarketListVersion();

  const panelRef = useRef<HTMLDivElement>(null);
  const posRef = useRef<Point>(loadPosition());
  const dragRef = useRef<{ startX: number; startY: number; originX: number; originY: number } | null>(
    null,
  );

  const [expanded, setExpanded] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) !== "0";
    } catch {
      return true;
    }
  });
  const [pos, setPos] = useState<Point>(() => posRef.current);
  const [dragging, setDragging] = useState(false);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [closingKey, setClosingKey] = useState<string | null>(null);

  const active = experiments.find((e) => e.id === activeExperimentId);
  const isLive = active?.mode === "live";
  const openPositions = (profile?.positions ?? []).filter((p) => Number(p.qty) > 0);
  const visible = openPositions.length > 0 || openOrders.length > 0;

  const syncClampedPosition = useCallback(() => {
    const el = panelRef.current;
    const width = el?.offsetWidth ?? Math.min(window.innerWidth - 16, PANEL_MAX_W);
    const height = el?.offsetHeight ?? 48;
    const next = clampPosition(posRef.current, width, height);
    posRef.current = next;
    setPos(next);
  }, []);

  useEffect(() => {
    syncClampedPosition();
    const onResize = () => syncClampedPosition();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [syncClampedPosition, expanded, visible]);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: PointerEvent) => {
      if (!dragRef.current) return;
      const el = panelRef.current;
      const width = el?.offsetWidth ?? Math.min(window.innerWidth - 16, PANEL_MAX_W);
      const height = el?.offsetHeight ?? 48;
      const dx = e.clientX - dragRef.current.startX;
      const dy = e.clientY - dragRef.current.startY;
      const next = clampPosition(
        { x: dragRef.current.originX + dx, y: dragRef.current.originY + dy },
        width,
        height,
      );
      posRef.current = next;
      setPos(next);
    };
    const onUp = () => {
      dragRef.current = null;
      setDragging(false);
      try {
        localStorage.setItem(POS_KEY, JSON.stringify(posRef.current));
      } catch {
        // ignore
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [dragging]);

  function toggleExpanded() {
    setExpanded((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        // ignore
      }
      return next;
    });
  }

  function onDragStart(e: React.PointerEvent<HTMLDivElement>) {
    if (e.button !== 0) return;
    e.preventDefault();
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      originX: posRef.current.x,
      originY: posRef.current.y,
    };
    setDragging(true);
  }

  function heldQty(ticker: string, side: TradeSide): number {
    const pos = openPositions.find((p) => p.ticker === ticker && p.side === side);
    return pos ? Number(pos.qty) : 0;
  }

  function focusPosition(ticker: string, side: TradeSide, qty: number) {
    tradingStore.prepareTrade(ticker, side, "sell", qty);
  }

  if (!visible) return null;

  return createPortal(
    <div
      ref={panelRef}
      aria-label="Portfolio overlay"
      className="fixed z-[400] w-[min(calc(100vw-16px),72rem)] select-none"
      style={{ left: pos.x, top: pos.y }}
    >
      <div className="overflow-hidden rounded-lg border border-ink-600/90 bg-[#0b1220]/98 shadow-2xl shadow-black/60 ring-1 ring-white/5 backdrop-blur-md">
        <div className="flex items-stretch border-b border-ink-800/80">
          <div
            data-drag-handle
            role="presentation"
            onPointerDown={onDragStart}
            title="Drag portfolio panel"
            className={`flex shrink-0 cursor-grab items-center border-r border-ink-800/60 px-2.5 text-ink-500 transition-colors hover:bg-ink-900/60 hover:text-ink-300 active:cursor-grabbing ${
              dragging ? "cursor-grabbing bg-ink-900/60" : ""
            }`}
          >
            <DragGrip />
          </div>
          <div className="flex min-w-0 flex-1 items-center justify-between gap-3 px-3 py-2">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-xs font-semibold uppercase tracking-wide text-accent">Portfolio</span>
              <span className="text-xs text-ink-300">
                {openPositions.length} position{openPositions.length === 1 ? "" : "s"}
                <span className="mx-1.5 text-ink-700">·</span>
                {openOrders.length} order{openOrders.length === 1 ? "" : "s"}
              </span>
              {!expanded ? (
                <span className="hidden truncate text-[11px] text-ink-500 sm:inline">
                  {openPositions
                    .slice(0, 2)
                    .map((p) => `${p.side.toUpperCase()} ${p.ticker.slice(0, 12)}`)
                    .join(" · ")}
                </span>
              ) : null}
            </div>
            <button
              type="button"
              onClick={toggleExpanded}
              className="shrink-0 rounded border border-ink-700 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-400 transition-colors hover:border-ink-500 hover:text-ink-200"
            >
              {expanded ? "Collapse" : "Expand"}
            </button>
          </div>
        </div>

        {expanded ? (
          <div className="max-h-[min(52vh,420px)] overflow-auto select-text">
            {openPositions.length > 0 ? (
              <section className="border-b border-ink-800/60">
                <p className="sticky top-0 z-[1] bg-[#0b1220]/95 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-ink-500">
                  Positions
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-xs">
                    <thead className="text-[10px] uppercase tracking-wide text-ink-600">
                      <tr className="border-b border-ink-800/60">
                        <th className="px-3 py-1.5 font-medium">Market</th>
                        <th className="px-2 py-1.5 font-medium">Side</th>
                        <th className="px-2 py-1.5 font-medium text-right">Qty</th>
                        <th className="px-2 py-1.5 font-medium text-right">Avg</th>
                        <th className="px-2 py-1.5 font-medium text-right">Mark</th>
                        <th className="px-2 py-1.5 font-medium text-right">P&amp;L</th>
                        <th className="px-3 py-1.5 font-medium text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {openPositions.map((pos) => {
                        const qty = Number(pos.qty);
                        const avgCents = Math.round(Number(pos.avg_price) * 100);
                        const markCents =
                          pos.mark_price != null ? Math.round(Number(pos.mark_price) * 100) : null;
                        const unreal = pos.unrealized_pnl != null ? Number(pos.unrealized_pnl) : null;
                        const basis = pos.cost_basis != null ? Number(pos.cost_basis) : null;
                        const unrealPct =
                          unreal != null && basis != null && basis > 0
                            ? pnlPctFromBasis(unreal, basis)
                            : null;
                        const key = positionKey(pos.ticker, pos.side);
                        const selected = selectedTicker === pos.ticker;
                        return (
                          <tr
                            key={key}
                            className={`border-b border-ink-900/80 ${selected ? "bg-accent/10" : "hover:bg-ink-900/40"}`}
                          >
                            <td className="max-w-[220px] px-3 py-2">
                              <button
                                type="button"
                                className="block max-w-full truncate text-left text-ink-100 hover:text-accent"
                                title={marketStore.getRow(pos.ticker)?.title ?? pos.ticker}
                                onClick={() => focusPosition(pos.ticker, pos.side, qty)}
                              >
                                {marketLabel(pos.ticker)}
                              </button>
                              <span className="font-mono text-[10px] text-ink-600">{pos.ticker}</span>
                            </td>
                            <td className="px-2 py-2 font-semibold text-emerald-400">
                              {pos.side.toUpperCase()}
                            </td>
                            <td className="px-2 py-2 text-right font-mono text-ink-200">{qty}</td>
                            <td className="px-2 py-2 text-right font-mono text-ink-400">{avgCents}¢</td>
                            <td className="px-2 py-2 text-right font-mono text-ink-400">
                              {markCents != null ? `${markCents}¢` : "—"}
                            </td>
                            <td
                              className={`px-2 py-2 text-right font-mono ${unreal != null ? pnlColorClass(pnlTone(unreal)) : "text-ink-600"}`}
                            >
                              {unreal != null ? (
                                <>
                                  {formatPnl(unreal)}
                                  {unrealPct != null ? (
                                    <span className="ml-1 text-[10px] opacity-90">
                                      {formatPnlPct(unrealPct)}
                                    </span>
                                  ) : null}
                                </>
                              ) : (
                                "—"
                              )}
                            </td>
                            <td className="px-3 py-2 text-right">
                              <button
                                type="button"
                                title={`Close with market ${pos.side === "yes" ? "sell" : "buy"}`}
                                disabled={closingKey === key}
                                onClick={() => {
                                  setClosingKey(key);
                                  void tradingStore.closePosition(pos.ticker, pos.side, isLive).finally(() => {
                                    setClosingKey(null);
                                  });
                                }}
                                className="rounded border border-ink-700 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-300 transition-colors hover:border-red-700 hover:bg-red-950/50 hover:text-red-300 disabled:opacity-40"
                              >
                                {closingKey === key ? "…" : pos.side === "yes" ? "Sell" : "Buy"}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}

            {openOrders.length > 0 ? (
              <section>
                <p className="sticky top-0 z-[1] bg-[#0b1220]/95 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-ink-500">
                  Open orders
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-xs">
                    <thead className="text-[10px] uppercase tracking-wide text-ink-600">
                      <tr className="border-b border-ink-800/60">
                        <th className="px-3 py-1.5 font-medium">Market</th>
                        <th className="px-2 py-1.5 font-medium">Order</th>
                        <th className="px-2 py-1.5 font-medium">Type</th>
                        <th className="px-2 py-1.5 font-medium text-right">Remaining</th>
                        <th className="px-2 py-1.5 font-medium text-right">Price</th>
                        <th className="px-3 py-1.5 font-medium text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {openOrders.map((order) => {
                        const remaining = orderRemainingQty(order);
                        const priceLabel =
                          order.type === "limit" && order.limit_price
                            ? `${Math.round(Number(order.limit_price) * 100)}¢`
                            : "MKT";
                        const selected = selectedTicker === order.ticker;
                        const actionLabel = orderActionLabel(order, heldQty(order.ticker, order.side));
                        return (
                          <tr
                            key={order.id}
                            className={`border-b border-ink-900/80 ${selected ? "bg-accent/10" : "hover:bg-ink-900/40"}`}
                          >
                            <td className="max-w-[220px] px-3 py-2">
                              <button
                                type="button"
                                className="block max-w-full truncate text-left text-ink-100 hover:text-accent"
                                title={marketStore.getRow(order.ticker)?.title ?? order.ticker}
                                onClick={() => tradingStore.focusMarket(order.ticker)}
                              >
                                {marketLabel(order.ticker)}
                              </button>
                              <span className="font-mono text-[10px] text-ink-600">{order.ticker}</span>
                            </td>
                            <td className="px-2 py-2 font-semibold text-ink-100">
                              {tradeLabel(order.side, order.action)}
                            </td>
                            <td className="px-2 py-2 capitalize text-ink-400">
                              {order.type}
                              {order.mode === "live" ? (
                                <span className="ml-1 text-[10px] text-amber-400">live</span>
                              ) : null}
                            </td>
                            <td className="px-2 py-2 text-right font-mono text-ink-200">{remaining}</td>
                            <td className="px-2 py-2 text-right font-mono text-ink-400">{priceLabel}</td>
                            <td className="px-3 py-2 text-right">
                              <button
                                type="button"
                                title={
                                  isRestingLimit(order)
                                    ? "Cancel resting limit order"
                                    : heldQty(order.ticker, order.side) > 0
                                      ? `Close ${order.action === "buy" ? "long" : "short"} with market ${order.action === "buy" ? "sell" : "buy"}`
                                      : "Cancel resting order"
                                }
                                disabled={cancellingId === order.id}
                                onClick={() => {
                                  setCancellingId(order.id);
                                  void tradingStore.closeOpenOrder(order, isLive).finally(() => {
                                    setCancellingId(null);
                                  });
                                }}
                                className="rounded border border-ink-700 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-300 transition-colors hover:border-red-700 hover:bg-red-950/50 hover:text-red-300 disabled:opacity-40"
                              >
                                {cancellingId === order.id ? "…" : actionLabel}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
