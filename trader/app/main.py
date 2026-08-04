from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable

import asyncpg
import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI

from common.logging import get_logger, setup_logging
from common.settings import TraderSettings
from trader.app.api import create_router
from trader.app.engine.live import LiveEngine
from trader.app.engine.paper import PaperEngine
from trader.app.experiments import ExperimentService
from trader.app.pnl import mark_equity_loop
from trader.app.order_expiry import cancel_expired_open_orders, cancel_open_orders_for_ticker
from trader.app.settlement import (
    SETTLE_CHANNEL,
    settle_all_active_experiments,
    settle_ticker_all_experiments,
    fetch_kalshi_position_map,
)
from trader.app.store import TradingStore

log = get_logger(__name__)


class AppState:
    def __init__(
        self,
        settings: TraderSettings,
        pool: asyncpg.Pool,
        redis: aioredis.Redis,
    ) -> None:
        self.settings = settings
        self.pool = pool
        self.redis = redis
        self.store = TradingStore(pool)
        self.exp_svc = ExperimentService(self.store)
        self.paper_engine = PaperEngine(pool, redis, settings)
        self.live_engine = LiveEngine(pool, settings, redis)
        self._running = True

    def running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self._running = False

    def kalshi_client(self):
        if not self.settings.kalshi_key_id:
            return None
        try:
            return self.live_engine._client()
        except Exception:
            return None

    async def settle_expired_positions(self) -> int:
        return await settle_all_active_experiments(self.pool, self.store, self.kalshi_client())

    async def cancel_expired_open_orders(self) -> int:
        return await cancel_expired_open_orders(
            self.pool,
            self.store,
            self.paper_engine,
            self.live_engine,
        )


async def _every(name: str, state: AppState, interval: float, work: Callable[[], Awaitable[Any]]) -> None:
    while state.running():
        try:
            await work()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("bg_loop_failed", loop=name, error=str(exc))
        await asyncio.sleep(interval)


async def _settle_listener(state: AppState) -> None:
    """Settle positions the moment a market result is published (no 30s wait)."""
    pubsub = state.redis.pubsub()
    await pubsub.subscribe(SETTLE_CHANNEL)
    try:
        while state.running():
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not msg or msg.get("type") != "message":
                continue
            ticker = msg.get("data")
            if not ticker:
                continue
            client = state.kalshi_client()
            kalshi_map = None
            if client and state.settings.trading_live_enabled:
                try:
                    kalshi_map = await fetch_kalshi_position_map(client)
                except Exception:
                    kalshi_map = {}
            n = await settle_ticker_all_experiments(
                state.pool,
                state.store,
                str(ticker),
                client,
                kalshi_map=kalshi_map,
            )
            await cancel_open_orders_for_ticker(
                state.pool,
                state.store,
                state.paper_engine,
                state.live_engine,
                str(ticker),
            )
            if n:
                log.info("settled_on_signal", ticker=ticker, count=n)
    finally:
        await pubsub.unsubscribe(SETTLE_CHANNEL)
        await pubsub.aclose()


def create_app(settings: TraderSettings | None = None) -> FastAPI:
    settings = settings or TraderSettings.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_logging(debug=settings.debug)
        pool = await asyncpg.create_pool(settings.timescale_dsn, min_size=2, max_size=10)
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        state = AppState(settings, pool, redis)
        app.state.app_state = state
        app.include_router(create_router(state))
        tasks = [
            asyncio.create_task(mark_equity_loop(pool, redis, settings.mark_interval_sec, state.running)),
            asyncio.create_task(_every("limits", state, 0.5, state.paper_engine.check_open_limits)),
            asyncio.create_task(_every("fill_sync", state, 2.0, state.live_engine.sync_open_orders)),
            asyncio.create_task(_every("settle", state, 10.0, state.settle_expired_positions)),
            asyncio.create_task(_every("order_expiry", state, 10.0, state.cancel_expired_open_orders)),
            # Startup + every 5m: keep local live positions aligned with Kalshi after restarts.
            asyncio.create_task(_every("reconcile", state, 300.0, state.live_engine.reconcile_positions)),
            asyncio.create_task(_settle_listener(state)),
        ]
        try:
            yield
        finally:
            state.stop()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await redis.aclose()
            await pool.close()

    return FastAPI(title="Kalshi Trader", lifespan=lifespan)


def main() -> None:
    settings = TraderSettings.load()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
