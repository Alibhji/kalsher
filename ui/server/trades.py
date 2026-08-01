from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import asyncpg

from common.trade_flow import trade_signed_usd

TRADES_SINCE_QUERY = """
SELECT ts, ticker, price, count, taker_side, trade_id
FROM trades
WHERE ticker = $1 AND ts >= $2
ORDER BY ts ASC
LIMIT $3
"""

RECENT_TRADES_QUERY = """
SELECT ts, ticker, price, count, taker_side, trade_id
FROM trades
WHERE ticker = $1
ORDER BY ts DESC
LIMIT $2
"""

GROUP_TRADES_QUERY = """
SELECT ts, ticker, price, count, taker_side, trade_id
FROM trades
WHERE ticker = ANY($1::text[])
  AND ts >= $2
ORDER BY ts ASC
LIMIT $3
"""


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _trade_payload(row: asyncpg.Record) -> dict[str, Any] | None:
    payload = {
        "price": row["price"],
        "count": row["count"],
        "taker_side": row["taker_side"],
        "trade_id": row["trade_id"],
    }
    signed = trade_signed_usd(payload)
    if signed is None:
        return None
    price = row["price"]
    price_cents = int(float(price) * 100) if price is not None else None
    return {
        "ticker": row["ticker"],
        "trade_id": row["trade_id"],
        "taker_side": row["taker_side"],
        "signed_usd": round(signed, 2),
        "price_cents": price_cents,
        "count": float(row["count"]) if row["count"] is not None else None,
        "ts": _iso(row["ts"]),
    }


async def fetch_trades_for_ticker(
    pool: asyncpg.Pool,
    ticker: str,
    *,
    since: datetime | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 20_000))
    async with pool.acquire() as conn:
        if since is not None:
            rows = await conn.fetch(TRADES_SINCE_QUERY, ticker, since, limit)
        else:
            rows = await conn.fetch(RECENT_TRADES_QUERY, ticker, min(limit, 200))
            rows = list(reversed(rows))
    out: list[dict[str, Any]] = []
    for row in rows:
        trade = _trade_payload(row)
        if trade:
            out.append(trade)
    return out


async def fetch_recent_trades(pool: asyncpg.Pool, ticker: str, *, limit: int = 50) -> list[dict[str, Any]]:
    return await fetch_trades_for_ticker(pool, ticker, limit=limit)


async def fetch_group_trades(
    pool: asyncpg.Pool,
    tickers: list[str],
    *,
    since: datetime,
    limit: int = 20_000,
) -> list[dict[str, Any]]:
    if not tickers:
        return []
    limit = max(1, min(limit, 50_000))
    async with pool.acquire() as conn:
        rows = await conn.fetch(GROUP_TRADES_QUERY, tickers, since, limit)
    out: list[dict[str, Any]] = []
    for row in rows:
        trade = _trade_payload(row)
        if trade:
            out.append(trade)
    return out


def parse_since_param(value: str | None) -> datetime | None:
    return _parse_since(value)
