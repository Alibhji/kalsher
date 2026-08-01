from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import msgspec
import redis.asyncio as aioredis

from common.logging import get_logger
from common.settings import UiSettings
from ui.server.hub import MarketHub
from ui.server.markets import UNIVERSE_KEY, fetch_markets

log = get_logger(__name__)

LIVE_CHANNEL = "kalshi:live"

StructureCallback = Callable[..., Awaitable[None]]


class LiveFeed:
    def __init__(
        self,
        redis: aioredis.Redis,
        pool: Any,
        hub: MarketHub,
        settings: UiSettings,
        *,
        redis_url: str,
    ) -> None:
        self._redis = redis
        self._redis_url = redis_url
        self._pool = pool
        self._hub = hub
        self._settings = settings
        self._decoder = msgspec.msgpack.Decoder()
        self._running = False
        self._on_tick: Any | None = None
        self._on_structure_change: StructureCallback | None = None
        self.messages_received = 0
        self.last_message_at: datetime | None = None
        self.last_message_lag_ms: float | None = None

    async def run(self) -> None:
        self._running = True
        await self._cold_start()
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._live_loop())
            tg.create_task(self._reconcile_loop())

    async def stop(self) -> None:
        self._running = False

    def set_on_tick(self, callback: Any) -> None:
        self._on_tick = callback

    def set_on_structure_change(self, callback: StructureCallback | None) -> None:
        self._on_structure_change = callback

    async def _cold_start(self) -> None:
        payload = await fetch_markets(
            self._redis,
            self._pool,
            web_base=self._settings.kalshi_web_base,
            drop_no_liquidity=False,
            live_only=False,
        )
        self._hub.seed_rows(payload["markets"])
        log.critical("feed_cold_start", markets=len(payload["markets"]))

    async def _emit_structure(
        self,
        *,
        added: list[dict[str, Any]] | None = None,
        removed: list[str] | None = None,
        archived: list[str] | None = None,
    ) -> None:
        if not self._on_structure_change:
            return
        added = added or []
        removed = removed or []
        archived = archived or []
        if not added and not removed and not archived:
            return
        await self._on_structure_change(added=added, removed=removed, archived=archived)

    async def _reconcile_loop(self) -> None:
        while self._running:
            await asyncio.sleep(10.0)
            try:
                tickers = set(await self._redis.smembers(UNIVERSE_KEY))
                hub_tickers = {r["ticker"] for r in self._hub.all_rows()}
                removed = sorted(hub_tickers - tickers)
                for ticker in removed:
                    self._hub.remove(ticker)

                missing = tickers - hub_tickers
                added: list[dict[str, Any]] = []
                if missing:
                    payload = await fetch_markets(
                        self._redis,
                        self._pool,
                        web_base=self._settings.kalshi_web_base,
                        drop_no_liquidity=False,
                        live_only=False,
                    )
                    by_ticker = {r["ticker"]: r for r in payload["markets"]}
                    for ticker in sorted(missing):
                        row = by_ticker.get(ticker)
                        if row:
                            self._hub.upsert_meta_row(row)
                            added.append(row)

                if removed or added:
                    await self._emit_structure(added=added, removed=removed, archived=removed)
            except Exception as exc:
                log.warning("feed_reconcile_failed", error=str(exc))

    async def _live_loop(self) -> None:
        pubsub_redis = aioredis.from_url(self._redis_url, decode_responses=False)
        pubsub = pubsub_redis.pubsub()
        await pubsub.subscribe(LIVE_CHANNEL)
        log.critical("feed_subscribed", channel=LIVE_CHANNEL)
        try:
            while self._running:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message or message.get("type") != "message":
                    continue
                data = message.get("data")
                if not isinstance(data, (bytes, bytearray)):
                    continue
                try:
                    frame = self._decoder.decode(data)
                except Exception as exc:
                    log.warning("feed_decode_failed", error=str(exc))
                    continue
                await self._apply_frame(frame)
        finally:
            await pubsub.unsubscribe(LIVE_CHANNEL)
            await pubsub_redis.aclose()

    async def _apply_frame(self, frame: dict[str, Any]) -> None:
        self.messages_received += 1
        self.last_message_at = datetime.now(timezone.utc)
        kind = frame.get("kind")
        ticker = frame.get("ticker")
        payload = frame.get("payload") or {}
        if not ticker:
            return

        if kind == "tick":
            if self._hub.apply_tick(ticker, payload) and self._on_tick:
                asyncio.create_task(self._on_tick(ticker))
        elif kind == "market_meta":
            was_new = self._hub.get_row(ticker) is None
            if self._hub.apply_market_meta(ticker, payload):
                if was_new:
                    row = self._hub.get_row(ticker)
                    if row:
                        await self._emit_structure(added=[row])
        elif kind == "lifecycle":
            event_type = payload.get("event_type")
            if event_type in ("close", "settled", "determined"):
                if self._hub.get_row(ticker) is not None:
                    self._hub.remove(ticker)
                    await self._emit_structure(removed=[ticker], archived=[ticker])

        source_ts = frame.get("source_ts")
        if source_ts:
            if isinstance(source_ts, datetime):
                src = source_ts if source_ts.tzinfo else source_ts.replace(tzinfo=timezone.utc)
            else:
                src = datetime.fromisoformat(str(source_ts).replace("Z", "+00:00"))
            self.last_message_lag_ms = (datetime.now(timezone.utc) - src).total_seconds() * 1000
        else:
            t_pub = frame.get("t_pub")
            if t_pub:
                self.last_message_lag_ms = (time.time() - float(t_pub)) * 1000
