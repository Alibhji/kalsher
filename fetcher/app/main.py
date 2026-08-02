from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone
from typing import Any

import uvloop
from aiohttp import web

from common.kalshi.auth import KalshiAuth
from common.kalshi.rest import KalshiRest
from common.kalshi.ws import WebSocketPool
from common.logging import debug_data, get_logger, setup_logging
from common.models import EventKind, NormalizedEvent
from common.settings import FetcherSettings

TERMINAL_STATUSES = frozenset({"finalized", "settled", "determined", "closed"})
from fetcher.app.discovery import Discovery
from fetcher.app.enrich import Enricher
from fetcher.app.handlers.lifecycle import handle_lifecycle
from fetcher.app.handlers.orderbook import OrderbookState
from fetcher.app.handlers.ticker import handle_ticker, handle_trade
from fetcher.app.handlers.underlying import handle_cfbenchmarks, handle_pyth
from fetcher.app.sinks.batching import BatchingSink
from fetcher.app.sinks.fanout_sink import FanoutSink
from fetcher.app.sinks.redis_sink import RedisSink
from fetcher.app.sinks.timescale_sink import TimescaleSink
from storage.clients.redis_store import RedisStore
from storage.clients.timescale_store import TimescaleStore

log = get_logger(__name__)
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

MARKET_CHANNELS = ["ticker", "trade", "orderbook_delta", "market_lifecycle_v2"]


class FetcherApp:
    def __init__(self, settings: FetcherSettings) -> None:
        self.settings = settings
        self.auth = KalshiAuth(settings.kalshi_key_id, settings.kalshi_private_key_path)
        self.rest = KalshiRest(settings.kalshi_rest_base, self.auth, settings.rest_rps)
        self.redis_store = RedisStore(settings.redis_url)
        self.timescale_store = TimescaleStore(settings.timescale_dsn)
        self.sink = BatchingSink(
            [RedisSink(self.redis_store), TimescaleSink(self.timescale_store)],
            batch_size=settings.sink_batch_size,
            flush_ms=settings.sink_flush_ms,
        )
        self.fanout = FanoutSink(self.redis_store) if settings.ui_fanout else None
        self.enricher = Enricher(self.rest, self.redis_store, self.timescale_store)
        self.orderbook = OrderbookState()
        self.ws_pool = WebSocketPool(
            settings.kalshi_ws_url,
            settings.kalshi_ws_path,
            self.auth,
            self._route_ws_message,
            settings.ws_shards,
            on_reconnect=self._on_ws_reconnect,
            queue_size=settings.ws_queue_size,
        )
        self.discovery = Discovery(self.rest, settings, on_change=self._on_universe_change)
        self._subscribed: dict[str, set[str]] = {str(i): set() for i in range(len(self.ws_pool.shards))}
        self._running = False
        self._tasks: set[asyncio.Task] = set()
        self._resyncing: set[str] = set()
        self._archiving: set[str] = set()
        self._runner: web.AppRunner | None = None
        self.messages_received = 0
        self.last_message_at: datetime | None = None

    def _spawn(self, coro: Any, *, name: str) -> None:
        """Fire-and-forget with the exception actually surfacing in the logs."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        def _log_failure(t: asyncio.Task) -> None:
            if not t.cancelled() and t.exception():
                log.error("background_task_failed", task=name, error=str(t.exception()))

        task.add_done_callback(_log_failure)

    async def _on_universe_change(
        self,
        universe: set[str],
        added: set[str],
        removed: set[str],
        added_markets: list[dict[str, Any]],
    ) -> None:
        await self.redis_store.set_universe(universe)
        if added:
            self._spawn(self._enrich_and_publish(added_markets), name="enrich")
            await self._subscribe_tickers(list(added), "add_markets")
        if removed:
            await self._subscribe_tickers(list(removed), "delete_markets")
            self._spawn(self._archive_and_purge_markets(removed), name="archive")

    async def _enrich_and_publish(self, markets: list[dict[str, Any]]) -> None:
        events = await self.enricher.enrich_from_markets(markets)
        if not events:
            return
        if self.fanout:
            await self.fanout.publish(events)
        await self.sink.enqueue(events)

    async def _on_ws_reconnect(self, shard_idx: int) -> None:
        key = str(shard_idx)
        tickers = list(self._subscribed.get(key, set()))
        if not tickers:
            return
        log.warning("ws_resubscribe", shard=shard_idx, tickers=len(tickers))
        # Only forget the old subscription state once the resubscribe succeeds,
        # otherwise a failure leaves us believing we are subscribed to nothing.
        previous = set(self._subscribed[key])
        self._subscribed[key].clear()
        try:
            await self._subscribe_tickers(tickers, "add_markets")
        except Exception:
            self._subscribed[key] = previous
            raise

    async def _subscribe_tickers(self, tickers: list[str], action: str) -> None:
        if not tickers:
            return
        by_shard: dict[int, list[str]] = {}
        for ticker in tickers:
            shard = hash(ticker) % len(self.ws_pool.shards)
            by_shard.setdefault(shard, []).append(ticker)
        for idx, batch in by_shard.items():
            ws = self.ws_pool.shards[idx]
            key = str(idx)
            if action == "add_markets":
                if not self._subscribed[key]:
                    await ws.subscribe(MARKET_CHANNELS, batch)
                    self._subscribed[key].update(batch)
                else:
                    updated = False
                    for channel in MARKET_CHANNELS:
                        sid = ws.sids.get(channel)
                        if sid is not None:
                            await ws.update_subscription(sid, "add_markets", batch)
                            updated = True
                    if not updated:
                        await ws.subscribe(MARKET_CHANNELS, batch)
                    self._subscribed[key].update(batch)
            else:
                for channel in MARKET_CHANNELS:
                    sid = ws.sids.get(channel)
                    if sid is not None:
                        await ws.update_subscription(sid, "delete_markets", batch)
                self._subscribed[key] -= set(batch)

    async def _archive_and_purge_market(self, ticker: str) -> None:
        # Lifecycle close and discovery removal can both fire for the same ticker.
        if ticker in self._archiving:
            return
        self._archiving.add(ticker)
        try:
            snapshot = await self.redis_store.get_market_snapshot(ticker)
            await self.timescale_store.mark_market_closed(ticker, snapshot=snapshot)
            await self._fetch_and_persist_result(ticker)
        except Exception as exc:
            log.warning("archive_market_failed", ticker=ticker, error=str(exc))
        finally:
            await self.redis_store.remove_from_universe(ticker)
            await self.redis_store.purge_market(ticker)
            self.orderbook.forget(ticker)
            self._archiving.discard(ticker)

    async def _fetch_and_persist_result(self, ticker: str, raw: dict[str, Any] | None = None) -> None:
        """Persist official result and nudge the trader to settle immediately."""
        result = str((raw or {}).get("result") or "").lower()
        status = str((raw or {}).get("event_type") or "").lower()
        if result not in ("yes", "no"):
            try:
                data = await self.rest.get_market(ticker)
                market = data.get("market") if isinstance(data.get("market"), dict) else data
                result = str(market.get("result") or "").lower()
                status = str(market.get("status") or status or "determined").lower()
            except Exception as exc:
                log.debug("market_result_fetch_failed", ticker=ticker, error=str(exc))
                return
        if result not in ("yes", "no"):
            return
        if status not in TERMINAL_STATUSES:
            status = "determined"
        await self.timescale_store.persist_market_result(ticker, status, result)
        await self.redis_store.publish_settle(ticker)

    async def _finalize_market(self, ticker: str, raw: dict[str, Any]) -> None:
        """Market result is official — persist it and settle any open paper/live positions."""
        await self._fetch_and_persist_result(ticker, raw)

    async def _resync_orderbook(self, ticker: str) -> None:
        """Runs off the WS read loop so REST latency never stalls ingestion."""
        if ticker in self._resyncing:
            return
        self._resyncing.add(ticker)
        try:
            await self.redis_store.mark_book_stale(ticker)
            events = await self.enricher.resync_orderbook(ticker)
            if events:
                if self.fanout:
                    await self.fanout.publish(events)
                await self.sink.enqueue(events)
                await self.redis_store.clear_book_stale(ticker)
        finally:
            # Re-baseline either way; holding deltas back forever is worse than a
            # brief inconsistency that the next WS snapshot repairs.
            self.orderbook.forget(ticker)
            self._resyncing.discard(ticker)

    async def _archive_and_purge_markets(self, tickers: set[str]) -> None:
        for ticker in tickers:
            await self._archive_and_purge_market(ticker)

    async def _route_ws_message(self, data: dict[str, Any]) -> None:
        self.messages_received += 1
        self.last_message_at = datetime.now(timezone.utc)
        msg_type = data.get("type")
        events: list[NormalizedEvent] = []

        if msg_type == "ticker":
            ev = handle_ticker(data)
            if ev:
                events.append(ev)
        elif msg_type == "trade":
            ev = handle_trade(data)
            if ev:
                events.append(ev)
        elif msg_type in ("orderbook_snapshot", "orderbook_delta"):
            events.extend(self.orderbook.handle(data))
            for ev in events:
                if ev.kind == EventKind.LIFECYCLE and ev.payload.get("event_type") == "book_seq_gap":
                    self._spawn(self._resync_orderbook(ev.ticker), name="book_resync")
        elif msg_type in ("market_lifecycle_v2", "market_lifecycle"):
            ev = handle_lifecycle(data)
            if ev:
                events.append(ev)
                if ev.payload.get("event_type") == "close":
                    self._spawn(self._archive_and_purge_market(ev.ticker), name="archive")
                elif ev.payload.get("event_type") in ("settled", "determined"):
                    raw = ev.payload.get("raw")
                    body = raw if isinstance(raw, dict) else {}
                    self._spawn(self._finalize_market(ev.ticker, body), name="finalize")
                    series = self.discovery.series_for_ticker(ev.ticker)
                    if series:
                        self.discovery.request_scan(series)
        elif msg_type == "pyth_value":
            ev = handle_pyth(data)
            if ev:
                events.append(ev)
        elif msg_type == "cfbenchmarks_value":
            ev = handle_cfbenchmarks(data)
            if ev:
                events.append(ev)
        elif msg_type == "error":
            log.warning("ws_error", payload=data)
        elif msg_type:
            debug_data(f"ws:{msg_type}", data)

        if events:
            debug_data("normalized", [{"kind": e.kind.value, "ticker": e.ticker} for e in events])
            if self.fanout:
                await self.fanout.publish(events)
            await self.sink.enqueue(events)

    async def run(self) -> None:
        self._running = True
        await self.sink.connect()

        await self.ws_pool.start()
        head = self.ws_pool.shards[0]
        await head.subscribe(["pyth_value"], underlying_tickers=["all"])
        await head.subscribe(["cfbenchmarks_value"], index_ids=["all"])

        log.critical(
            "fetcher_started",
            debug=self.settings.debug,
            series_allowlist=self.settings.filters.series_allowlist,
            live_event_only=self.settings.filters.live_event_only,
            ws_shards=self.settings.ws_shards,
        )

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.discovery.run())
            tg.create_task(self.sink.run())
            tg.create_task(self._metrics_server())

        await self.ws_pool.stop()
        await self.rest.close()
        await self.sink.close()
        if self._runner:
            await self._runner.cleanup()

    async def stop(self) -> None:
        """Signal every loop to wind down so run()'s TaskGroup can exit."""
        self._running = False
        self.sink.stop()
        await self.discovery.stop()
        await self.ws_pool.stop()

    async def _metrics_server(self) -> None:
        app = web.Application()

        async def healthz(_: web.Request) -> web.Response:
            return web.json_response({"status": "ok", "universe": len(self.discovery.universe)})

        async def metrics(_: web.Request) -> web.Response:
            lag_ms = None
            if self.last_message_at:
                lag_ms = (datetime.now(timezone.utc) - self.last_message_at).total_seconds() * 1000
            return web.json_response(
                {
                    "messages_received": self.messages_received,
                    "universe_size": len(self.discovery.universe),
                    "ws_reconnects": self.ws_pool.reconnects,
                    "ws_queue_depth": self.ws_pool.queue_depth,
                    "sink_queue_depth": self.sink.queue_depth,
                    "sink_events_written": self.sink.events_written,
                    "sink_last_flush_ms": self.sink.last_flush_ms,
                    "sink_dropped": self.sink.dropped,
                    "orderbook_seq_gaps": self.orderbook.seq_gaps,
                    "orderbook_awaiting_resync": len(self.orderbook.awaiting_resync),
                    "fanout_published": self.fanout.published if self.fanout else None,
                    "fanout_drops": self.fanout.drops if self.fanout else None,
                    "last_message_lag_ms": lag_ms,
                }
            )

        app.router.add_get("/healthz", healthz)
        app.router.add_get("/metrics", metrics)
        runner = web.AppRunner(app)
        self._runner = runner
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.settings.metrics_port)
        await site.start()
        log.debug("metrics_started", port=self.settings.metrics_port)
        while self._running:
            await asyncio.sleep(1)


def main() -> None:
    settings = FetcherSettings.load()
    setup_logging(debug=settings.debug, level=settings.log_level)
    app = FetcherApp(settings)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown() -> None:
        loop.create_task(app.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    try:
        loop.run_until_complete(app.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
