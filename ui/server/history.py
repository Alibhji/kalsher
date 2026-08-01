from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import asyncpg

BOUNDS_QUERY = """
SELECT open_time, close_time, expected_expiration_time, latest_expiration_time, status
FROM markets
WHERE ticker = $1
"""

MARKET_1S_QUERY = """
SELECT bucket AS ts, close, yes_bid, yes_ask
FROM market_1s
WHERE ticker = $1 AND bucket >= $2 AND bucket <= $3
ORDER BY bucket
"""

TICKS_BUCKET_QUERY = """
SELECT
    time_bucket($4::interval, ts) AS ts,
    last(last_price, ts) AS close,
    last(yes_bid, ts) AS yes_bid,
    last(yes_ask, ts) AS yes_ask
FROM ticks
WHERE ticker = $1 AND ts >= $2 AND ts <= $3
GROUP BY 1
ORDER BY 1
"""


def _to_cents(value: Decimal | float | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)) * 100)


def _point_cents(close: Any, yes_bid: Any, yes_ask: Any) -> float | None:
    if close is not None:
        return _to_cents(close)
    bid = _to_cents(yes_bid)
    ask = _to_cents(yes_ask)
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    if bid is not None:
        return bid
    if ask is not None:
        return ask
    return None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _resolve_close_time(
    close_time: datetime | None,
    expected_expiration_time: datetime | None,
    latest_expiration_time: datetime | None,
    open_time: datetime | None,
) -> datetime | None:
    """Kalshi active markets often have NULL close_time; use expiration fields."""
    if close_time is not None:
        return close_time
    if expected_expiration_time is not None:
        return expected_expiration_time
    if latest_expiration_time is not None:
        return latest_expiration_time
    if open_time is not None:
        return open_time + timedelta(hours=3)
    return None


def _bucket_interval(seconds: float) -> timedelta:
    if seconds <= 900:
        return timedelta(seconds=1)
    if seconds <= 3600:
        return timedelta(seconds=5)
    if seconds <= 10800:
        return timedelta(seconds=15)
    return timedelta(minutes=1)


async def fetch_market_history(
    pool: asyncpg.Pool,
    ticker: str,
    *,
    since: datetime | None = None,
) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        bounds = await conn.fetchrow(BOUNDS_QUERY, ticker)
        if not bounds:
            return None

        open_time = _as_utc(bounds["open_time"])
        close_time = _resolve_close_time(
            _as_utc(bounds["close_time"]),
            _as_utc(bounds["expected_expiration_time"]),
            _as_utc(bounds["latest_expiration_time"]),
            open_time,
        )

        if close_time is None:
            return {
                "ticker": ticker,
                "open_time": open_time.isoformat() if open_time else None,
                "close_time": None,
                "window_start": None,
                "window_end": None,
                "points": [],
            }

        window_end = min(close_time, now)
        window_start = open_time or (window_end - timedelta(hours=3))

        if window_start >= window_end:
            return {
                "ticker": ticker,
                "open_time": open_time.isoformat() if open_time else None,
                "close_time": close_time.isoformat(),
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "points": [],
                "incremental": since is not None,
            }

        query_start = window_start
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            query_start = max(window_start, since)

        rows = await conn.fetch(
            TICKS_BUCKET_QUERY,
            ticker,
            query_start,
            window_end,
            _bucket_interval((window_end - window_start).total_seconds()),
        )
        if not rows:
            rows = await conn.fetch(MARKET_1S_QUERY, ticker, query_start, window_end)

    points: list[dict[str, Any]] = []
    for row in rows:
        cents = _point_cents(row["close"], row["yes_bid"], row["yes_ask"])
        if cents is None:
            continue
        ts: datetime = row["ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        points.append({"ts": ts.isoformat(), "yes_cents": round(cents, 2)})

    return {
        "ticker": ticker,
        "open_time": open_time.isoformat() if open_time else None,
        "close_time": close_time.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "points": points,
        "incremental": since is not None,
        "closed": close_time <= now,
    }
