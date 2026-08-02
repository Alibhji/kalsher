from __future__ import annotations

import asyncio

import asyncpg
import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI

from common.logging import setup_logging
from common.settings import TraderSettings
from trader.app.api import create_router
from trader.app.engine.live import LiveEngine
from trader.app.engine.paper import PaperEngine
from trader.app.experiments import ExperimentService
from trader.app.pnl import mark_equity_loop
from trader.app.store import TradingStore


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


async def _limit_checker(state: AppState) -> None:
    while state.running():
        try:
            await state.paper_engine.check_open_limits()
        except Exception:
            pass
        await asyncio.sleep(0.5)


async def _reconcile_loop(state: AppState) -> None:
    while state.running():
        try:
            await state.live_engine.reconcile_positions()
        except Exception:
            pass
        await asyncio.sleep(30)


def create_app(settings: TraderSettings | None = None) -> FastAPI:
    settings = settings or TraderSettings.load()
    app = FastAPI(title="Kalshi Trader")
    bg_tasks: list[asyncio.Task] = []

    @app.on_event("startup")
    async def startup() -> None:
        setup_logging(debug=settings.debug)
        pool = await asyncpg.create_pool(settings.timescale_dsn, min_size=2, max_size=10)
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        state = AppState(settings, pool, redis)
        app.state.app_state = state
        app.include_router(create_router(state))
        bg_tasks.extend(
            [
                asyncio.create_task(
                    mark_equity_loop(pool, redis, settings.mark_interval_sec, state.running)
                ),
                asyncio.create_task(_limit_checker(state)),
                asyncio.create_task(_reconcile_loop(state)),
            ]
        )

    @app.on_event("shutdown")
    async def shutdown() -> None:
        state: AppState = app.state.app_state
        state.stop()
        for t in bg_tasks:
            t.cancel()
        await state.redis.aclose()
        await state.pool.close()

    return app


def main() -> None:
    settings = TraderSettings.load()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
