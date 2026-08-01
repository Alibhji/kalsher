from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from websockets.asyncio.client import connect

from common.kalshi.auth import KalshiAuth
from common.logging import get_logger

log = get_logger(__name__)

MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]
ReconnectHandler = Callable[[], Awaitable[None]]


class KalshiWebSocket:
    def __init__(
        self,
        ws_url: str,
        ws_path: str,
        auth: KalshiAuth,
        on_message: MessageHandler,
        queue_size: int = 10_000,
        on_reconnect: ReconnectHandler | None = None,
    ) -> None:
        self.ws_url = ws_url
        self.ws_path = ws_path
        self.auth = auth
        self.on_message = on_message
        self.on_reconnect = on_reconnect
        self._outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
        self._msg_id = 1
        self._running = False
        self.reconnects = 0
        self.messages_received = 0
        self.sids: dict[str, int] = {}

    async def run(self) -> None:
        self._running = True
        backoff = 1.0
        while self._running:
            try:
                headers = self.auth.ws_headers(self.ws_path)
                async with connect(
                    self.ws_url,
                    additional_headers=headers,
                    compression=None,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    had_disconnect = self.reconnects > 0
                    self.sids.clear()
                    backoff = 1.0
                    log.debug("ws_connected", url=self.ws_url, reconnect=had_disconnect)
                    if had_disconnect and self.on_reconnect:
                        await self.on_reconnect()
                    sender = asyncio.create_task(self._sender(ws))
                    try:
                        async for raw in ws:
                            data = json.loads(raw)
                            self.messages_received += 1
                            if data.get("type") == "subscribed":
                                msg = data.get("msg") or {}
                                channel = msg.get("channel")
                                sid = msg.get("sid")
                                if channel is not None and sid is not None:
                                    self.sids[channel] = sid
                            await self.on_message(data)
                    finally:
                        sender.cancel()
            except Exception as exc:
                self.reconnects += 1
                log.warning("ws_disconnected", error=str(exc), reconnects=self.reconnects)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def stop(self) -> None:
        self._running = False

    async def _sender(self, ws: Any) -> None:
        while self._running:
            payload = await self._outbound.get()
            await ws.send(json.dumps(payload))

    async def subscribe(
        self,
        channels: list[str],
        market_tickers: list[str] | None = None,
        **extra: Any,
    ) -> None:
        params: dict[str, Any] = {"channels": channels, **extra}
        if market_tickers:
            params["market_tickers"] = market_tickers
        await self._send({"id": self._next_id(), "cmd": "subscribe", "params": params})

    async def update_subscription(self, sid: int, action: str, market_tickers: list[str]) -> None:
        await self._send(
            {
                "id": self._next_id(),
                "cmd": "update_subscription",
                "params": {"sids": [sid], "action": action, "market_tickers": market_tickers},
            }
        )

    async def _send(self, payload: dict[str, Any]) -> None:
        await self._outbound.put(payload)

    def _next_id(self) -> int:
        mid = self._msg_id
        self._msg_id += 1
        return mid


class WebSocketPool:
    def __init__(
        self,
        ws_url: str,
        ws_path: str,
        auth: KalshiAuth,
        on_message: MessageHandler,
        shards: int,
        on_reconnect: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        count = max(1, shards)

        def make_reconnect(idx: int) -> ReconnectHandler:
            async def _cb() -> None:
                if on_reconnect:
                    await on_reconnect(idx)

            return _cb

        self.shards = [
            KalshiWebSocket(
                ws_url,
                ws_path,
                auth,
                on_message,
                on_reconnect=make_reconnect(i) if on_reconnect else None,
            )
            for i in range(count)
        ]
        self._tasks: list[asyncio.Task] = []

    def shard_for(self, ticker: str) -> KalshiWebSocket:
        return self.shards[hash(ticker) % len(self.shards)]

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(s.run()) for s in self.shards]

    async def stop(self) -> None:
        for s in self.shards:
            await s.stop()
        for t in self._tasks:
            t.cancel()

    @property
    def reconnects(self) -> int:
        return sum(s.reconnects for s in self.shards)

    @property
    def queue_depth(self) -> int:
        return sum(s._outbound.qsize() for s in self.shards)
