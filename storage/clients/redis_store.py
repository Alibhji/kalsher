from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import redis.asyncio as aioredis

from common.models import EventKind, NormalizedEvent


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Not serializable: {type(obj)}")


class RedisStore:
    UNIVERSE_KEY = "kalshi:universe"

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._client = aioredis.from_url(self._url, decode_responses=True)
        for stream in ("ticks", "trades", "book", "underlying", "lifecycle"):
            key = f"kalshi:stream:{stream}"
            try:
                await self._client.xgroup_create(key, "analyzers", id="0", mkstream=True)
            except aioredis.ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> aioredis.Redis:
        assert self._client is not None
        return self._client

    async def set_universe(self, tickers: set[str]) -> None:
        pipe = self.client.pipeline()
        pipe.delete(self.UNIVERSE_KEY)
        if tickers:
            pipe.sadd(self.UNIVERSE_KEY, *sorted(tickers))
        await pipe.execute()

    async def add_to_universe(self, ticker: str) -> None:
        await self.client.sadd(self.UNIVERSE_KEY, ticker)

    async def remove_from_universe(self, ticker: str) -> None:
        await self.client.srem(self.UNIVERSE_KEY, ticker)

    async def purge_market(self, ticker: str) -> None:
        """Drop hot Redis state for an expired/removed market."""
        pipe = self.client.pipeline()
        pipe.delete(f"kalshi:market:{ticker}")
        pipe.delete(f"kalshi:book:{ticker}:yes")
        pipe.delete(f"kalshi:book:{ticker}:no")
        await pipe.execute()

    async def purge_markets(self, tickers: set[str] | list[str]) -> None:
        if not tickers:
            return
        pipe = self.client.pipeline()
        for ticker in tickers:
            pipe.delete(f"kalshi:market:{ticker}")
            pipe.delete(f"kalshi:book:{ticker}:yes")
            pipe.delete(f"kalshi:book:{ticker}:no")
        await pipe.execute()

    async def get_market_snapshot(self, ticker: str) -> dict[str, str]:
        raw = await self.client.hgetall(f"kalshi:market:{ticker}")
        return raw or {}

    async def upsert_market_meta(self, ticker: str, fields: dict[str, Any]) -> None:
        flat = {k: json.dumps(v, default=_json_default) if isinstance(v, (dict, list)) else str(v) for k, v in fields.items() if v is not None}
        if flat:
            await self.client.hset(f"kalshi:market:{ticker}", mapping=flat)

    async def mark_book_stale(self, ticker: str) -> None:
        await self.client.hset(f"kalshi:market:{ticker}", "book_stale", "1")

    async def write_events(self, events: list[NormalizedEvent]) -> None:
        if not events:
            return
        pipe = self.client.pipeline()
        for ev in events:
            payload = json.dumps(
                {"kind": ev.kind.value, "ticker": ev.ticker, "ts": ev.ts.isoformat(), "payload": ev.payload},
                default=_json_default,
            )
            stream = self._stream_for(ev.kind)
            pipe.xadd(stream, {"data": payload}, maxlen=100_000, approximate=True)
            if ev.kind == EventKind.TICK:
                self._apply_tick(pipe, ev)
            elif ev.kind == EventKind.TRADE:
                pass
            elif ev.kind in (EventKind.BOOK_DELTA, EventKind.BOOK_SNAPSHOT):
                self._apply_book(pipe, ev)
            elif ev.kind == EventKind.LIFECYCLE:
                pipe.publish(f"kalshi:chan:{ev.ticker}", payload)
        await pipe.execute()

    def _stream_for(self, kind: EventKind) -> str:
        mapping = {
            EventKind.TICK: "kalshi:stream:ticks",
            EventKind.TRADE: "kalshi:stream:trades",
            EventKind.BOOK_DELTA: "kalshi:stream:book",
            EventKind.BOOK_SNAPSHOT: "kalshi:stream:book",
            EventKind.UNDERLYING: "kalshi:stream:underlying",
            EventKind.LIFECYCLE: "kalshi:stream:lifecycle",
            EventKind.MARKET_META: "kalshi:stream:lifecycle",
        }
        return mapping[kind]

    def _apply_tick(self, pipe: aioredis.client.Pipeline, ev: NormalizedEvent) -> None:
        p = ev.payload
        mapping = {}
        for k in ("yes_bid", "yes_ask", "no_bid", "no_ask", "last_price", "volume", "open_interest"):
            if k in p and p[k] is not None:
                mapping[k] = str(p[k])
        mapping["updated_at"] = ev.ts.isoformat()
        if mapping:
            pipe.hset(f"kalshi:market:{ev.ticker}", mapping=mapping)
        pipe.publish(f"kalshi:chan:{ev.ticker}", json.dumps({"kind": "tick", "ticker": ev.ticker}, default=_json_default))

    def _apply_book(self, pipe: aioredis.client.Pipeline, ev: NormalizedEvent) -> None:
        p = ev.payload
        side = p.get("side", "yes")
        key = f"kalshi:book:{ev.ticker}:{side}"
        if ev.kind == EventKind.BOOK_SNAPSHOT:
            pipe.delete(key)
            for level in p.get("levels", []):
                price, size = level.get("price"), level.get("size")
                if price is not None and size is not None and size > 0:
                    pipe.zadd(key, {str(price): float(size)})
        else:
            price = p.get("price")
            delta = p.get("delta")
            if price is not None:
                if delta is None or delta == 0:
                    pipe.zrem(key, str(price))
                else:
                    pipe.zadd(key, {str(price): float(delta)})
