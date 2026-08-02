from __future__ import annotations

from typing import Any, TYPE_CHECKING

import asyncpg

from common.logging import get_logger
from trader.app.settlement import _market_may_be_settled
from trader.app.store import TradingStore

if TYPE_CHECKING:
    from trader.app.engine.live import LiveEngine
    from trader.app.engine.paper import PaperEngine

log = get_logger(__name__)


async def _cancel_one(
    order: dict[str, Any],
    *,
    store: TradingStore,
    paper_engine: PaperEngine,
    live_engine: LiveEngine,
) -> bool:
    mode = str(order.get("mode") or "paper")
    engine = live_engine if mode == "live" else paper_engine
    try:
        await engine.cancel_order(order, reason="expired")
    except Exception as exc:
        log.warning(
            "order_expiry_cancel_failed",
            order_id=str(order["id"]),
            ticker=order.get("ticker"),
            error=str(exc),
        )
        await store.update_order(order["id"], status="cancelled", reason="expired")
    return True


async def cancel_open_orders_for_ticker(
    pool: asyncpg.Pool,
    store: TradingStore,
    paper_engine: PaperEngine,
    live_engine: LiveEngine,
    ticker: str,
) -> int:
    """Cancel resting orders when a market has expired or finalized."""
    if not await _market_may_be_settled(pool, ticker):
        return 0
    cancelled = 0
    for order in await store.list_open_orders():
        if str(order["ticker"]) != ticker:
            continue
        if await _cancel_one(order, store=store, paper_engine=paper_engine, live_engine=live_engine):
            cancelled += 1
            log.info("order_expired_cancelled", order_id=str(order["id"]), ticker=ticker)
    return cancelled


async def cancel_expired_open_orders(
    pool: asyncpg.Pool,
    store: TradingStore,
    paper_engine: PaperEngine,
    live_engine: LiveEngine,
) -> int:
    """Background sweep: cancel open orders on expired/finalized markets."""
    cancelled = 0
    seen_tickers: set[str] = set()
    for order in await store.list_open_orders():
        ticker = str(order["ticker"])
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        if not await _market_may_be_settled(pool, ticker):
            continue
        cancelled += await cancel_open_orders_for_ticker(
            pool, store, paper_engine, live_engine, ticker
        )
    return cancelled
