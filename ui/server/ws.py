from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import WSCloseCode, web
from aiohttp.client_exceptions import ClientConnectionResetError

from common.logging import get_logger
from common.settings import UiSettings
from ui.server.hub import MarketHub

log = get_logger(__name__)

QUEUE_MAX = 256
RESYNC_FRAME = json.dumps({"t": "resync"})


def _encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str)


class WsClient:
    def __init__(self, ws: web.WebSocketResponse, hub: MarketHub, settings: UiSettings) -> None:
        self.ws = ws
        self.hub = hub
        self.settings = settings
        self.focus_ticker: str | None = None
        self.queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=QUEUE_MAX)
        self.drops = 0
        self.resyncs = 0
        self.closed = False

    def send(self, wire: str) -> None:
        """Enqueue an already-serialized frame."""
        if self.closed:
            return
        try:
            self.queue.put_nowait(wire)
        except asyncio.QueueFull:
            self.drops += 1
            self._request_resync()

    def _request_resync(self) -> None:
        """The client fell behind: discard the stale backlog and have it refetch."""
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.resyncs += 1
        self.queue.put_nowait(RESYNC_FRAME)

    def send_ready(self) -> None:
        self.send(_encode({"t": "ready", "count": self.hub.market_count}))

    async def writer_loop(self) -> None:
        while True:
            wire = await self.queue.get()
            if wire is None or self.ws.closed:
                break
            try:
                await self.ws.send_str(wire)
            except (ClientConnectionResetError, ConnectionResetError):
                break
            except Exception as exc:
                log.warning("ws_send_failed", error=str(exc))
                break
        self.closed = True


class WsManager:
    def __init__(self, hub: MarketHub, settings: UiSettings) -> None:
        self.hub = hub
        self.settings = settings
        self.clients: set[WsClient] = set()
        self._trades: list[dict[str, Any]] = []
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            await asyncio.sleep(self.settings.list_flush_ms / 1000.0)
            try:
                self._flush()
            except Exception as exc:
                log.warning("ws_flush_failed", error=str(exc))

    async def stop(self) -> None:
        self._running = False
        for client in list(self.clients):
            client.closed = True
            client.queue.put_nowait(None)

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)
        client = WsClient(ws, self.hub, self.settings)
        self.clients.add(client)
        writer = asyncio.create_task(client.writer_loop())
        try:
            client.send_ready()
            async for msg in ws:
                if msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
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
                    client.send(_encode({"t": "pong", "client_t": data.get("t")}))
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

    def broadcast(self, payload: dict[str, Any]) -> None:
        if not self.clients:
            return
        wire = _encode(payload)
        for client in list(self.clients):
            client.send(wire)

    async def on_structure_change(
        self,
        *,
        added: list[dict[str, Any]] | None = None,
        removed: list[str] | None = None,
        archived: list[str] | None = None,
    ) -> None:
        if removed:
            self.broadcast({"t": "rm", "tickers": removed})
        if added:
            self.broadcast({"t": "add", "markets": added})
        if archived:
            self.broadcast({"t": "archived", "tickers": archived})

    async def on_trade(self, trade: dict[str, Any]) -> None:
        """Buffered; trades ship with the next list flush so bursts cost one frame."""
        if trade:
            self._trades.append(trade)

    async def on_tick(self, ticker: str) -> None:
        """Low-latency path for the market a client has expanded."""
        if self.settings.market_flush_ms != 0:
            return
        watchers = [c for c in self.clients if c.focus_ticker == ticker]
        if not watchers:
            return
        delta = self.hub.quote_delta(ticker)
        if not delta:
            return
        wire = _encode({"t": "q", "updates": [delta]})
        for client in watchers:
            client.send(wire)

    def _flush(self) -> None:
        clients = list(self.clients)
        self._flush_trades(clients)
        self._flush_quotes(clients)

    def _flush_trades(self, clients: list[WsClient]) -> None:
        if not self._trades:
            return
        trades, self._trades = self._trades, []
        if not clients:
            return
        wire = _encode({"t": "tr", "trades": trades})
        for client in clients:
            client.send(wire)

    def _flush_quotes(self, clients: list[WsClient]) -> None:
        dirty = self.hub.dirty_tickers()
        if not dirty:
            return
        updates = [d for d in (self.hub.quote_delta(t) for t in dirty) if d]
        self.hub.mark_clean(dirty)
        if not updates or not clients:
            return

        # Focused tickers already went out via on_tick, so skip them for those clients.
        # Everyone else shares a single serialization.
        skip_focus = self.settings.market_flush_ms == 0
        wire_by_focus: dict[str | None, str | None] = {}
        for client in clients:
            focus = client.focus_ticker if skip_focus else None
            if focus not in wire_by_focus:
                subset = [u for u in updates if u["ticker"] != focus] if focus else updates
                wire_by_focus[focus] = _encode({"t": "q", "updates": subset}) if subset else None
            wire = wire_by_focus[focus]
            if wire:
                client.send(wire)

    @property
    def client_count(self) -> int:
        return len(self.clients)

    @property
    def total_drops(self) -> int:
        return sum(c.drops for c in self.clients)

    @property
    def total_resyncs(self) -> int:
        return sum(c.resyncs for c in self.clients)
