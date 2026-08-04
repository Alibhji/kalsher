from __future__ import annotations

import asyncio
import signal
from datetime import datetime
from pathlib import Path

import asyncpg
import redis.asyncio as aioredis
import uvloop
from aiohttp import ClientSession, web

from common.logging import get_logger, setup_logging
from common.settings import UiSettings
from ui.server.archive import fetch_archive_event_markets, fetch_archive_events, fetch_archive_tree
from ui.server.feed import LiveFeed
from ui.server.history import fetch_market_history
from ui.server.hub import MarketHub
from ui.server.maintenance import CONFIRM_PHRASE, reset_platform
from ui.server.markets import fetch_markets
from ui.server.rules import fetch_market_rules
from ui.server.trades import fetch_trades_for_ticker, parse_since_param
from ui.server.trading_proxy import proxy_trading
from ui.server.ws import WsManager

log = get_logger(__name__)
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"


def _int_param(request: web.Request, name: str, default: int, *, maximum: int) -> int:
    raw = request.query.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise web.HTTPBadRequest(text=f"Invalid {name}")
    return max(1, min(value, maximum))


class UiApp:
    def __init__(self, settings: UiSettings) -> None:
        self.settings = settings
        self._redis: aioredis.Redis | None = None
        self._pool: asyncpg.Pool | None = None
        self._hub = MarketHub(web_base=settings.kalshi_web_base)
        self._feed: LiveFeed | None = None
        self._ws_manager: WsManager | None = None
        self._http: ClientSession | None = None
        self._running = False

    async def start(self) -> None:
        self._redis = aioredis.from_url(self.settings.redis_url, decode_responses=True)
        self._pool = await asyncpg.create_pool(self.settings.timescale_dsn, min_size=1, max_size=5)
        self._http = ClientSession()
        self._running = True

        assert self._redis is not None and self._pool is not None
        self._feed = LiveFeed(
            self._redis,
            self._pool,
            self._hub,
            self.settings,
            redis_url=self.settings.redis_url,
        )
        self._ws_manager = WsManager(self._hub, self.settings)
        self._feed.set_on_tick(self._ws_manager.on_tick)
        self._feed.set_on_trade(self._ws_manager.on_trade)
        self._feed.set_on_structure_change(self._ws_manager.on_structure_change)

        app = web.Application()
        app["settings"] = self.settings
        app["http"] = self._http
        app.router.add_get("/healthz", self._healthz)
        app.router.add_get("/metrics", self._metrics)
        app.router.add_get("/ws", self._ws)
        app.router.add_get("/api/markets", self._api_markets)
        app.router.add_get("/api/markets/{ticker}/history", self._api_history)
        app.router.add_get("/api/markets/{ticker}/trades", self._api_trades)
        app.router.add_get("/api/markets/{ticker}/rules", self._api_rules)
        app.router.add_get("/api/archive/tree", self._api_archive_tree)
        app.router.add_get("/api/archive/events", self._api_archive_events)
        app.router.add_get("/api/archive/events/{event_ticker}/markets", self._api_archive_event_markets)
        app.router.add_post("/api/admin/reset-platform", self._api_reset_platform)
        app.router.add_route("*", "/api/trading/{tail:.*}", proxy_trading)

        if STATIC_DIR.is_dir():
            app.router.add_static("/assets", STATIC_DIR / "assets", show_index=False)
            app.router.add_get("/", self._index)
            app.router.add_get("/{tail:.*}", self._spa_fallback)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.settings.port)
        await site.start()
        log.critical("ui_started", port=self.settings.port, static=STATIC_DIR.is_dir())

        assert self._feed is not None and self._ws_manager is not None
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._feed.run())
            tg.create_task(self._ws_manager.run())
            tg.create_task(self._run_forever())

        await runner.cleanup()

    async def _run_forever(self) -> None:
        while self._running:
            await asyncio.sleep(3600)

    async def stop(self) -> None:
        self._running = False
        if self._feed:
            await self._feed.stop()
        if self._ws_manager:
            await self._ws_manager.stop()
        if self._http and not self._http.closed:
            await self._http.close()
            self._http = None
        if self._pool:
            await self._pool.close()
        if self._redis:
            await self._redis.aclose()

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        assert self._ws_manager is not None
        return await self._ws_manager.handle(request)

    async def _metrics(self, _: web.Request) -> web.Response:
        feed = self._feed
        ws = self._ws_manager
        return web.json_response(
            {
                "hub_markets": len(self._hub.all_rows()),
                "feed_messages_received": feed.messages_received if feed else 0,
                "feed_last_message_lag_ms": feed.last_message_lag_ms if feed else None,
                "ws_clients": ws.client_count if ws else 0,
                "ws_drops": ws.total_drops if ws else 0,
                "ws_resyncs": ws.total_resyncs if ws else 0,
            }
        )

    async def _healthz(self, _: web.Request) -> web.Response:
        assert self._redis is not None
        universe = await self._redis.scard("kalshi:universe")
        return web.json_response({"status": "ok", "universe": universe, "hub": len(self._hub.all_rows())})

    async def _api_markets(self, request: web.Request) -> web.Response:
        live_only = request.query.get("live", "1") != "0"
        if self._hub.all_rows() and request.query.get("source", "hub") != "redis":
            rows = self._hub.all_rows()
            if live_only and self.settings.live_only:
                rows = [r for r in rows if r.get("is_live")]
            if self.settings.drop_no_liquidity:
                rows = [r for r in rows if r.get("has_liquidity")]
            return web.json_response({"markets": rows})

        assert self._redis is not None and self._pool is not None
        payload = await fetch_markets(
            self._redis,
            self._pool,
            web_base=self.settings.kalshi_web_base,
            drop_no_liquidity=self.settings.drop_no_liquidity,
            live_only=live_only and self.settings.live_only,
        )
        return web.json_response(payload)

    async def _api_history(self, request: web.Request) -> web.Response:
        assert self._pool is not None
        ticker = request.match_info["ticker"]
        since_raw = request.query.get("since")
        since = None
        if since_raw:
            try:
                since = datetime.fromisoformat(since_raw.replace("Z", "+00:00"))
            except ValueError:
                raise web.HTTPBadRequest(text="Invalid since timestamp")
        history = await fetch_market_history(self._pool, ticker, since=since)
        if history is None:
            raise web.HTTPNotFound(text="Market not found")
        return web.json_response(history)

    async def _api_trades(self, request: web.Request) -> web.Response:
        assert self._pool is not None
        ticker = request.match_info["ticker"]
        limit = _int_param(request, "limit", 5000, maximum=50_000)
        since_raw = request.query.get("since")
        since = parse_since_param(since_raw) if since_raw else None
        if since_raw and since is None:
            raise web.HTTPBadRequest(text="Invalid since timestamp")
        trades = await fetch_trades_for_ticker(self._pool, ticker, since=since, limit=limit)
        return web.json_response({"ticker": ticker, "since": since_raw, "trades": trades})

    async def _api_rules(self, request: web.Request) -> web.Response:
        assert self._redis is not None and self._pool is not None
        ticker = request.match_info["ticker"]
        rules = await fetch_market_rules(self._redis, self._pool, ticker)
        if rules is None:
            raise web.HTTPNotFound(text="Market rules not found")
        return web.json_response(rules)

    async def _api_archive_tree(self, request: web.Request) -> web.Response:
        assert self._pool is not None
        series = request.query.get("series")
        limit = _int_param(request, "limit", self.settings.archive_default_limit, maximum=500)
        tree = await fetch_archive_tree(self._pool, series_ticker=series, period_limit=limit)
        return web.json_response({"series": tree})

    async def _api_archive_events(self, request: web.Request) -> web.Response:
        assert self._pool is not None
        series = request.query.get("series")
        limit = _int_param(request, "limit", self.settings.archive_default_limit, maximum=500)
        events = await fetch_archive_events(self._pool, series_ticker=series, limit=limit)
        return web.json_response({"events": events})

    async def _api_archive_event_markets(self, request: web.Request) -> web.Response:
        assert self._pool is not None
        event_ticker = request.match_info["event_ticker"]
        markets = await fetch_archive_event_markets(self._pool, event_ticker)
        if not markets:
            raise web.HTTPNotFound(text="Archived event not found")
        return web.json_response({"event_ticker": event_ticker, "markets": markets})

    async def _api_reset_platform(self, request: web.Request) -> web.Response:
        assert self._pool is not None and self._redis is not None
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Expected JSON body")
        if body.get("confirmPhrase") != CONFIRM_PHRASE:
            return web.json_response(
                {"ok": False, "error": f'confirmPhrase must be exactly "{CONFIRM_PHRASE}"'},
                status=400,
            )
        try:
            result = await reset_platform(self._pool, self._redis)
        except Exception as exc:
            log.error("reset_platform_failed", error=str(exc))
            return web.json_response(
                {"ok": False, "error": "Failed to reset platform", "detail": str(exc)},
                status=500,
            )
        # The hub still holds the pre-reset universe; rebuild it and push clients a resync
        # so the dashboard does not keep serving ghost markets until the next reconcile.
        self._hub.seed_rows([])
        if self._feed:
            await self._feed.reseed()
        if self._ws_manager:
            self._ws_manager.broadcast({"t": "resync"})
        return web.json_response({"ok": True, **result})

    async def _index(self, _: web.Request) -> web.Response:
        return await self._serve_index()

    async def _spa_fallback(self, request: web.Request) -> web.Response:
        if request.path.startswith("/api/") or request.path.startswith("/assets/"):
            raise web.HTTPNotFound()
        return await self._serve_index()

    async def _serve_index(self) -> web.Response:
        index = STATIC_DIR / "index.html"
        if not index.is_file():
            return web.Response(
                text="UI build not found. Run npm run build in ui/web.",
                status=503,
                content_type="text/plain",
            )
        return web.FileResponse(index)


def main() -> None:
    settings = UiSettings.load()
    setup_logging(debug=settings.debug)
    app = UiApp(settings)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown() -> None:
        loop.create_task(app.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    try:
        loop.run_until_complete(app.start())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
