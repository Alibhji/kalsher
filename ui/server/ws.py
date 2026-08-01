from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from aiohttp import WSCloseCode, web
from aiohttp.client_exceptions import ClientConnectionResetError

from common.logging import get_logger
from common.settings import UiSettings
from ui.server.hub import MarketHub

log = get_logger(__name__)

QUEUE_MAX = 256


class WsClient:
    def __init__(self, ws: web.WebSocketResponse, hub: MarketHub, settings: UiSettings) -> None:
        self.ws = ws
        self.hub = hub
        self.settings = settings
        self.focus_ticker: str | None = None
        self.queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=QUEUE_MAX)
        self.drops = 0
        self.needs_resync = False
        self.closed = False

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self.closed:
            return
        payload = dict(payload)
        payload["t_send"] = time.time()
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            self.drops += 1
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.queue.put_nowait(payload)
            except asyncio.QueueFull:
                self.needs_resync = True

    async def writer_loop(self) -> None:
        while True:
            msg = await self.queue.get()
            if msg is None:
                break
            if self.needs_resync and msg.get("t") != "ready":
                continue
            if self.ws.closed:
                break
            try:
                await self.ws.send_str(json.dumps(msg, default=str))
            except (ClientConnectionResetError, ConnectionResetError):
                self.closed = True
                break
            if msg.get("t") == "ready":
                self.needs_resync = False

    async def send_ready(self) -> None:
        await self.send_json({"t": "ready", "count": len(self.hub.all_rows())})


class WsManager:
    def __init__(self, hub: MarketHub, settings: UiSettings) -> None:
        self.hub = hub
        self.settings = settings
        self.clients: set[WsClient] = set()
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            await asyncio.sleep(self.settings.list_flush_ms / 1000.0)
            await self._flush_list()

    async def stop(self) -> None:
        self._running = False

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)
        client = WsClient(ws, self.hub, self.settings)
        self.clients.add(client)
        writer = asyncio.create_task(client.writer_loop())
        await client.send_ready()
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.ERROR:
                    break
                if msg.type == web.WSMsgType.CLOSE:
                    break
                if msg.type != web.WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                op = data.get("op")
                if op == "focus":
                    client.focus_ticker = data.get("ticker")
                elif op == "ping":
                    await client.send_json({"t": "pong", "client_t": data.get("t")})
        finally:
            client.closed = True
            self.clients.discard(client)
            client.queue.put_nowait(None)
            try:
                await asyncio.wait_for(writer, timeout=2.0)
            except asyncio.TimeoutError:
                writer.cancel()
            if not ws.closed:
                await ws.close(code=WSCloseCode.GOING_AWAY, message=b"bye")

        return ws

    async def on_structure_change(
        self,
        *,
        added: list[dict[str, Any]] | None = None,
        removed: list[str] | None = None,
        archived: list[str] | None = None,
    ) -> None:
        added = added or []
        removed = removed or []
        archived = archived or []
        for client in self.clients:
            if removed:
                await client.send_json({"t": "rm", "tickers": removed})
            if added:
                await client.send_json({"t": "add", "markets": added})
            if archived:
                await client.send_json({"t": "archived", "tickers": archived})

    async def on_trade(self, trade: dict[str, Any]) -> None:
        if not trade:
            return
        for client in self.clients:
            await client.send_json({"t": "tr", "trades": [trade]})

    async def on_tick(self, ticker: str) -> None:
        if self.settings.market_flush_ms != 0:
            return
        delta = self.hub.quote_delta(ticker)
        if not delta:
            return
        for client in self.clients:
            if client.focus_ticker == ticker:
                await client.send_json({"t": "q", "updates": [delta]})

    async def _flush_list(self) -> None:
        dirty = self.hub.dirty_tickers()
        if not dirty:
            return
        updates = []
        for ticker in dirty:
            delta = self.hub.quote_delta(ticker)
            if delta:
                updates.append(delta)
        self.hub.mark_clean(dirty)
        if not updates:
            return
        for client in self.clients:
            list_updates = [
                u for u in updates if client.focus_ticker is None or u["ticker"] != client.focus_ticker
            ]
            if list_updates:
                await client.send_json({"t": "q", "updates": list_updates})

    @property
    def client_count(self) -> int:
        return len(self.clients)

    @property
    def total_drops(self) -> int:
        return sum(c.drops for c in self.clients)
