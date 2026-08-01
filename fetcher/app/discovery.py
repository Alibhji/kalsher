from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from common.kalshi.rest import KalshiRest
from common.logging import get_logger
from common.settings import FetcherSettings
from fetcher.app.filters import apply_filters, live_event_markets

log = get_logger(__name__)

OnUniverseChange = Callable[[set[str], set[str], set[str], list[dict[str, Any]]], asyncio.Future | None]


class Discovery:
    def __init__(
        self,
        rest: KalshiRest,
        settings: FetcherSettings,
        on_change: OnUniverseChange | None = None,
    ) -> None:
        self.rest = rest
        self.settings = settings
        self.on_change = on_change
        self.universe: set[str] = set()
        self._per_series: dict[str, set[str]] = {}
        self._markets_by_ticker: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._wake: dict[str, asyncio.Event] = {}
        self._running = False

    async def run(self) -> None:
        self._running = True
        allowlist = self.settings.filters.series_allowlist
        if not allowlist:
            await self._global_loop()
            return
        for series in allowlist:
            self._wake[series] = asyncio.Event()
        async with asyncio.TaskGroup() as tg:
            for series in allowlist:
                tg.create_task(self._series_loop(series))

    async def stop(self) -> None:
        self._running = False
        for event in self._wake.values():
            event.set()

    def request_scan(self, series: str) -> None:
        wake = self._wake.get(series)
        if wake is not None:
            wake.set()

    def series_for_ticker(self, ticker: str) -> str | None:
        prefix = ticker.split("-", 1)[0]
        if prefix in self._wake:
            return prefix
        return None

    async def _global_loop(self) -> None:
        while self._running:
            try:
                await self._scan_global()
            except Exception as exc:
                log.error("discovery_error", error=str(exc))
            await asyncio.sleep(self.settings.discovery_interval_sec)

    async def _series_loop(self, series: str) -> None:
        wake = self._wake[series]
        backoff = 1.0
        while self._running:
            try:
                await self._scan_series(series)
                backoff = 1.0
            except Exception as exc:
                log.error("discovery_series_error", series=series, error=str(exc))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                continue
            try:
                await asyncio.wait_for(
                    wake.wait(),
                    timeout=self.settings.discovery_interval_sec,
                )
            except asyncio.TimeoutError:
                pass
            wake.clear()

    async def _scan_global(self) -> set[str]:
        now = datetime.now(timezone.utc)
        max_ts = int(now.timestamp() + self.settings.filters.max_hours_to_close * 3600)
        min_ts = int(now.timestamp())
        params = {
            "min_close_ts": min_ts,
            "max_close_ts": max_ts,
            "limit": 1000,
            "mve_filter": "exclude",
        }
        markets: list[dict[str, Any]] = []
        async for market in self.rest.paginate("/markets", params):
            if apply_filters(market, self.settings.filters, now):
                markets.append(market)
        tickers = {m["ticker"] for m in markets}
        await self._apply_series_update("__global__", tickers, {m["ticker"]: m for m in markets})
        return tickers

    async def scan_series(self, series: str) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        markets = [
            market
            async for market in self.rest.paginate(
                "/markets",
                {"series_ticker": series, "status": "open"},
            )
            if apply_filters(market, self.settings.filters, now)
        ]
        if self.settings.filters.live_event_only:
            markets = live_event_markets(markets, now)
        return markets

    async def _scan_series(self, series: str) -> None:
        markets = await self.scan_series(series)
        tickers = {m["ticker"] for m in markets}
        by_ticker = {m["ticker"]: m for m in markets}
        await self._apply_series_update(series, tickers, by_ticker)

    async def _apply_series_update(
        self,
        series: str,
        tickers: set[str],
        by_ticker: dict[str, dict[str, Any]],
    ) -> None:
        async with self._lock:
            prev_series = self._per_series.get(series, set())
            added_series = tickers - prev_series
            removed_series = prev_series - tickers
            self._per_series[series] = tickers
            for ticker in removed_series:
                self._markets_by_ticker.pop(ticker, None)
            for ticker, market in by_ticker.items():
                self._markets_by_ticker[ticker] = market

            prev_universe = self.universe
            new_universe: set[str] = set()
            for s_tickers in self._per_series.values():
                new_universe |= s_tickers
            added = new_universe - prev_universe
            removed = prev_universe - new_universe
            self.universe = new_universe

            added_markets = [self._markets_by_ticker[t] for t in added if t in self._markets_by_ticker]

            log.debug(
                "discovery_scan",
                series=series,
                series_total=len(tickers),
                universe_total=len(new_universe),
                added=len(added),
                removed=len(removed),
            )

            if self.on_change and (added or removed):
                result = self.on_change(new_universe, added, removed, added_markets)
                if asyncio.iscoroutine(result):
                    await result

    async def scan(self) -> set[str]:
        """Legacy entry: scan all allowlisted series sequentially (tests)."""
        allowlist = self.settings.filters.series_allowlist
        if not allowlist:
            return await self._scan_global()
        for series in allowlist:
            await self._scan_series(series)
        return self.universe
