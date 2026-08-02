from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from common.kalshi.rest import KalshiRest
from common.logging import get_logger
from common.models import EventKind, MarketMeta, NormalizedEvent, parse_decimal, parse_ts
from storage.clients.redis_store import RedisStore
from storage.clients.timescale_store import TimescaleStore

log = get_logger(__name__)

_EVENT_CACHE_TTL_SEC = 300.0
_SERIES_CACHE_TTL_SEC = 3600.0


class Enricher:
    def __init__(self, rest: KalshiRest, redis: RedisStore, timescale: TimescaleStore) -> None:
        self.rest = rest
        self.redis = redis
        self.timescale = timescale
        self._event_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._series_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

    async def enrich_from_markets(self, markets: list[dict[str, Any]]) -> list[NormalizedEvent]:
        if not markets:
            return []

        event_tickers = {m.get("event_ticker") for m in markets if m.get("event_ticker")}
        event_results = await asyncio.gather(
            *(self._event_cached(e) for e in event_tickers),
            return_exceptions=True,
        )
        events_by_ticker = {
            et: (None if isinstance(r, Exception) else r)
            for et, r in zip(event_tickers, event_results)
        }

        series_tickers: set[str] = set()
        for event in events_by_ticker.values():
            if event and event.get("series_ticker"):
                series_tickers.add(event["series_ticker"])
        for market in markets:
            st = market.get("series_ticker")
            if st:
                series_tickers.add(st)

        series_results = await asyncio.gather(
            *(self._series_cached(s) for s in series_tickers),
            return_exceptions=True,
        )
        series_by_ticker = {
            st: (None if isinstance(r, Exception) else r)
            for st, r in zip(series_tickers, series_results)
        }

        now = datetime.now(timezone.utc)
        normalized: list[NormalizedEvent] = []
        metas: list[MarketMeta] = []
        redis_payloads: list[tuple[str, dict[str, Any]]] = []

        for market in markets:
            ticker = market.get("ticker")
            if not ticker:
                continue
            try:
                meta = self._meta_from_listing(market, events_by_ticker, series_by_ticker)
                metas.append(meta)
                redis_payloads.append((ticker, meta.raw))
                normalized.append(
                    NormalizedEvent(
                        kind=EventKind.MARKET_META,
                        ticker=ticker,
                        ts=now,
                        payload=meta.raw,
                    )
                )
            except Exception as exc:
                log.warning("enrich_failed", ticker=ticker, error=str(exc))

        for meta in metas:
            try:
                await self.timescale.upsert_market(meta)
            except Exception as exc:
                log.warning("enrich_timescale_failed", ticker=meta.ticker, error=str(exc))

        if redis_payloads:
            pipe = self.redis.client.pipeline()
            for ticker, raw in redis_payloads:
                self._queue_meta(pipe, ticker, raw)
            await pipe.execute()

        return normalized

    async def _event_cached(self, event_ticker: str) -> dict[str, Any] | None:
        import time

        now = time.monotonic()
        cached = self._event_cache.get(event_ticker)
        if cached and now - cached[0] < _EVENT_CACHE_TTL_SEC:
            return cached[1]
        try:
            data = await self.rest.get_event(event_ticker)
            event = data.get("event", data)
            self._event_cache[event_ticker] = (now, event)
            return event
        except Exception as exc:
            log.warning("enrich_event_failed", event_ticker=event_ticker, error=str(exc))
            self._event_cache[event_ticker] = (now, None)
            return None

    async def _series_cached(self, series_ticker: str) -> dict[str, Any] | None:
        import time

        now = time.monotonic()
        cached = self._series_cache.get(series_ticker)
        if cached and now - cached[0] < _SERIES_CACHE_TTL_SEC:
            return cached[1]
        try:
            data = await self.rest.get_series(series_ticker)
            series = data.get("series", data)
            self._series_cache[series_ticker] = (now, series)
            return series
        except Exception as exc:
            log.warning("enrich_series_failed", series_ticker=series_ticker, error=str(exc))
            self._series_cache[series_ticker] = (now, None)
            return None

    def _meta_from_listing(
        self,
        market: dict[str, Any],
        events_by_ticker: dict[str, dict[str, Any] | None],
        series_by_ticker: dict[str, dict[str, Any] | None],
    ) -> MarketMeta:
        ticker = market["ticker"]
        event_ticker = market.get("event_ticker", "")
        event = events_by_ticker.get(event_ticker) if event_ticker else None
        category = event.get("category") if event else None
        series_ticker = market.get("series_ticker") or (event.get("series_ticker") if event else None)
        extra: dict[str, Any] = {"market": market}
        if event:
            extra["event"] = event
        if series_ticker:
            series = series_by_ticker.get(series_ticker)
            if series:
                extra["series"] = series

        return MarketMeta(
            ticker=ticker,
            event_ticker=event_ticker,
            series_ticker=series_ticker,
            title=market.get("title"),
            yes_sub_title=market.get("yes_sub_title"),
            no_sub_title=market.get("no_sub_title"),
            status=market.get("status"),
            open_time=parse_ts(market.get("open_time")),
            close_time=parse_ts(market.get("close_time")),
            expected_expiration_time=parse_ts(market.get("expected_expiration_time")),
            latest_expiration_time=parse_ts(market.get("latest_expiration_time")),
            yes_bid_dollars=parse_decimal(market.get("yes_bid_dollars")),
            yes_ask_dollars=parse_decimal(market.get("yes_ask_dollars")),
            no_bid_dollars=parse_decimal(market.get("no_bid_dollars")),
            no_ask_dollars=parse_decimal(market.get("no_ask_dollars")),
            last_price_dollars=parse_decimal(market.get("last_price_dollars")),
            volume_fp=parse_decimal(market.get("volume_fp")),
            volume_24h_fp=parse_decimal(market.get("volume_24h_fp")),
            open_interest_fp=parse_decimal(market.get("open_interest_fp")),
            category=category,
            raw=extra,
        )

    def _queue_meta(self, pipe: Any, ticker: str, fields: dict[str, Any]) -> None:
        import json

        from storage.clients.redis_store import _json_default

        flat = {
            k: json.dumps(v, default=_json_default) if isinstance(v, (dict, list)) else str(v)
            for k, v in fields.items()
            if v is not None
        }
        if flat:
            pipe.hset(f"kalshi:market:{ticker}", mapping=flat)

    async def resync_orderbook(self, ticker: str) -> list[NormalizedEvent]:
        """Rebuild a gapped book from REST and return snapshot events for the sinks."""
        try:
            ob = await self.rest.get_orderbook(ticker)
        except Exception as exc:
            log.warning("orderbook_resync_failed", ticker=ticker, error=str(exc))
            return []

        book = ob.get("orderbook") or ob
        now = datetime.now(timezone.utc)
        events: list[NormalizedEvent] = []
        for side in ("yes", "no"):
            raw_levels = book.get(side) or book.get(f"{side}_dollars") or []
            levels = [
                {"price": parse_decimal(item[0]), "size": parse_decimal(item[1])}
                for item in raw_levels
                if isinstance(item, (list, tuple)) and len(item) >= 2
            ]
            events.append(
                NormalizedEvent(
                    kind=EventKind.BOOK_SNAPSHOT,
                    ticker=ticker,
                    ts=now,
                    payload={"side": side, "levels": levels, "seq": None, "resync": True},
                )
            )
        log.debug("orderbook_resync", ticker=ticker, levels=sum(len(e.payload["levels"]) for e in events))
        return events
