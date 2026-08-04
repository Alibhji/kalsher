from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from common.kalshi.rest import KalshiRest

# Deposits change rarely; avoid re-paginating Kalshi on every /state poll.
_DEPOSITS_TTL_S = 600.0
_deposits_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _dep_ts(raw: dict[str, Any]) -> datetime:
    ts = raw.get("finalized_ts") or raw.get("created_ts")
    if ts is not None:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return datetime.now(timezone.utc)


def normalize_kalshi_deposit(raw: dict[str, Any]) -> dict[str, Any]:
    amount = Decimal(str(raw.get("amount_cents") or 0)) / Decimal("100")
    fee = Decimal(str(raw.get("fee_cents") or 0)) / Decimal("100")
    return {
        "id": str(raw.get("id") or ""),
        "ts": _dep_ts(raw),
        "amount": amount,
        "fee": fee,
        "net_amount": amount,
        "status": str(raw.get("status") or ""),
        "type": str(raw.get("type") or ""),
    }


async def _paginate_deposits(client: KalshiRest) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": 100}
    out: list[dict[str, Any]] = []
    while True:
        data = await client.get("/portfolio/deposits", params)
        out.extend(data.get("deposits") or [])
        cursor = data.get("cursor")
        if not cursor:
            break
        params["cursor"] = cursor
    return out


async def fetch_all_kalshi_deposits(
    client: KalshiRest,
    *,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    cache_key = str(id(client))
    now = time.monotonic()
    if use_cache:
        hit = _deposits_cache.get(cache_key)
        if hit and now - hit[0] < _DEPOSITS_TTL_S:
            return [dict(r) for r in hit[1]]

    rows = await _paginate_deposits(client)
    applied = [
        normalize_kalshi_deposit(r)
        for r in rows
        if str(r.get("status") or "").lower() == "applied"
    ]
    if use_cache:
        _deposits_cache[cache_key] = (now, applied)
    return [dict(r) for r in applied]


def clear_deposits_cache() -> None:
    _deposits_cache.clear()


def cumulative_capital(deposits: list[dict[str, Any]], until: datetime | None = None) -> Decimal:
    total = Decimal("0")
    for d in deposits:
        ts = d["ts"]
        if until is not None and ts > until:
            continue
        total += Decimal(str(d["net_amount"]))
    return total


def deposits_in_period(
    deposits: list[dict[str, Any]],
    start: datetime | None,
    end: datetime | None,
) -> Decimal:
    total = Decimal("0")
    for d in deposits:
        ts = d["ts"]
        if start is not None and ts < start:
            continue
        if end is not None and ts > end:
            continue
        total += Decimal(str(d["net_amount"]))
    return total


def account_pnl(equity: Decimal, deposits: list[dict[str, Any]], at: datetime | None = None) -> Decimal:
    invested = cumulative_capital(deposits, until=at)
    return equity - invested
