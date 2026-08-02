from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

import httpx

from common.kalshi.auth import KalshiAuth
from common.logging import debug_data


class TokenBucket:
    def __init__(self, rate: float) -> None:
        self.rate = max(rate, 0.1)
        self._tokens = rate
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(self.rate, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) / self.rate
            # Sleep outside the lock so waiters share refills instead of serializing.
            await asyncio.sleep(wait)


class KalshiRest:
    def __init__(self, base_url: str, auth: KalshiAuth, rps: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self._limiter = TokenBucket(rps)
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    def _sign_path(self, rel: str) -> str:
        return f"/trade-api/v2{rel if rel.startswith('/') else '/' + rel}"

    async def _request(self, method: str, path: str, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> dict[str, Any]:
        await self._limiter.acquire()
        rel = path if path.startswith("/") else f"/{path}"
        headers = self.auth.sign(method, self._sign_path(rel))
        resp = await self._client.request(method, rel, params=params, json=json, headers=headers)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        debug_data(f"rest {method} {rel}", {"params": params, "keys": list(data.keys()) if isinstance(data, dict) else type(data).__name__})
        return data

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("POST", path, json=body or {})

    async def delete(self, path: str) -> dict[str, Any]:
        return await self._request("DELETE", path)

    async def paginate(self, path: str, params: dict[str, Any] | None = None) -> AsyncIterator[dict[str, Any]]:
        params = dict(params or {})
        params.setdefault("limit", 1000)
        while True:
            data = await self.get(path, params)
            for item in data.get("markets", data.get("events", data.get("milestones", data.get("orders", [])))):
                yield item
            cursor = data.get("cursor")
            if not cursor:
                break
            params["cursor"] = cursor

    async def get_market(self, ticker: str) -> dict[str, Any]:
        return await self.get(f"/markets/{ticker}")

    async def get_event(self, event_ticker: str) -> dict[str, Any]:
        return await self.get(f"/events/{event_ticker}")

    async def get_series(self, series_ticker: str) -> dict[str, Any]:
        return await self.get(f"/series/{series_ticker}")

    async def get_orderbook(self, ticker: str) -> dict[str, Any]:
        return await self.get(f"/markets/{ticker}/orderbook")

    async def get_balance(self) -> dict[str, Any]:
        return await self.get("/portfolio/balance")

    async def get_orders(self, **params: Any) -> dict[str, Any]:
        return await self.get("/portfolio/orders", params)

    async def get_positions(self, **params: Any) -> dict[str, Any]:
        return await self.get("/portfolio/positions", params)

    async def get_fills(self, **params: Any) -> dict[str, Any]:
        return await self.get("/portfolio/fills", params)

    async def create_order(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self.post("/portfolio/events/orders", body)

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        return await self.delete(f"/portfolio/events/orders/{order_id}")
