from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import asyncpg

from common.liquidity import market_has_liquidity

TERMINAL_ARCHIVE_STATUSES = ("finalized", "settled", "determined")

# Official yes/no result stored by fetcher/trader settlement pipeline.
_MARKET_RESULT_SQL = "COALESCE(m.metadata #>> '{market,result}', m.metadata #>> '{result}')"
_SETTLED_MARKET_SQL = f"""
    m.status IN ('finalized', 'settled', 'determined')
    AND {_MARKET_RESULT_SQL} IN ('yes', 'no')
"""
# Period appears only when every liquid strike in the event is settled.
_EVENT_LIQUID_SETTLED_SQL = """
    AND NOT EXISTS (
        SELECT 1 FROM markets m2
        WHERE m2.event_ticker = m.event_ticker
          AND m2.had_liquidity IS TRUE
          AND (
              m2.status NOT IN ('finalized', 'settled', 'determined')
              OR COALESCE(m2.metadata #>> '{market,result}', m2.metadata #>> '{result}')
                 NOT IN ('yes', 'no')
          )
    )
"""

ARCHIVE_MARKETS_QUERY = (
    r"""
SELECT
    m.ticker,
    m.event_ticker,
    m.series_ticker,
    m.title,
    m.status,
    m.open_time,
    m.close_time,
    m.had_liquidity,
    m.close_volume,
    m.close_yes_bid_cents,
    m.close_yes_ask_cents,
    m.metadata #>> '{event,title}' AS event_title,
    m.metadata #>> '{series,title}' AS series_title,
    CASE WHEN m.metadata #>> '{market,floor_strike}' ~ '^-?[0-9]+(\.[0-9]+)?$'
         THEN (m.metadata #>> '{market,floor_strike}')::NUMERIC END AS floor_strike,
    CASE WHEN m.metadata #>> '{market,cap_strike}' ~ '^-?[0-9]+(\.[0-9]+)?$'
         THEN (m.metadata #>> '{market,cap_strike}')::NUMERIC END AS cap_strike,
    m.metadata #>> '{market,strike_type}' AS strike_type,
    lt.yes_bid AS last_yes_bid,
    lt.yes_ask AS last_yes_ask,
    lt.volume AS last_volume
FROM markets m
LEFT JOIN LATERAL (
    SELECT yes_bid, yes_ask, volume
    FROM ticks t
    WHERE t.ticker = m.ticker
    ORDER BY t.ts DESC
    LIMIT 1
) lt ON TRUE
WHERE """
    + _SETTLED_MARKET_SQL
    + _EVENT_LIQUID_SETTLED_SQL
    + r"""
  AND ($1::text IS NULL OR m.series_ticker = $1)
ORDER BY m.close_time DESC NULLS LAST
LIMIT $2
"""
)

ARCHIVE_EVENT_MARKETS_QUERY = (
    r"""
SELECT
    m.ticker,
    m.event_ticker,
    m.series_ticker,
    m.title,
    m.status,
    m.open_time,
    m.close_time,
    m.had_liquidity,
    m.close_volume,
    m.close_yes_bid_cents,
    m.close_yes_ask_cents,
    m.metadata #>> '{event,title}' AS event_title,
    m.metadata #>> '{series,title}' AS series_title,
    CASE WHEN m.metadata #>> '{market,floor_strike}' ~ '^-?[0-9]+(\.[0-9]+)?$'
         THEN (m.metadata #>> '{market,floor_strike}')::NUMERIC END AS floor_strike,
    CASE WHEN m.metadata #>> '{market,cap_strike}' ~ '^-?[0-9]+(\.[0-9]+)?$'
         THEN (m.metadata #>> '{market,cap_strike}')::NUMERIC END AS cap_strike,
    m.metadata #>> '{market,strike_type}' AS strike_type,
    lt.yes_bid AS last_yes_bid,
    lt.yes_ask AS last_yes_ask,
    lt.volume AS last_volume
FROM markets m
LEFT JOIN LATERAL (
    SELECT yes_bid, yes_ask, volume
    FROM ticks t
    WHERE t.ticker = m.ticker
    ORDER BY t.ts DESC
    LIMIT 1
) lt ON TRUE
WHERE m.event_ticker = $1
  AND """
    + _SETTLED_MARKET_SQL
    + r"""
ORDER BY floor_strike NULLS LAST, m.ticker
"""
)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _price_cents(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return int((value * 100).quantize(Decimal("1")))


def _row_had_liquidity(row: asyncpg.Record) -> bool:
    if row["had_liquidity"] is not None:
        return bool(row["had_liquidity"])

    volume = _dec(row["close_volume"])
    if volume is None:
        volume = _dec(row["last_volume"])

    bid_cents = row["close_yes_bid_cents"]
    ask_cents = row["close_yes_ask_cents"]
    if bid_cents is None and ask_cents is None:
        bid_cents = _price_cents(_dec(row["last_yes_bid"]))
        ask_cents = _price_cents(_dec(row["last_yes_ask"]))

    return market_has_liquidity(bid_cents, ask_cents, volume_usd=volume)


def _row_volume(row: asyncpg.Record) -> float:
    volume = _dec(row["close_volume"])
    if volume is None:
        volume = _dec(row["last_volume"])
    return float(volume or 0)


def _market_payload(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "ticker": row["ticker"],
        "event_ticker": row["event_ticker"],
        "series_ticker": row["series_ticker"],
        "title": row["title"],
        "event_title": row["event_title"],
        "series_title": row["series_title"],
        "status": row["status"],
        "open_time": _iso(row["open_time"]),
        "close_time": _iso(row["close_time"]),
        "floor_strike": float(row["floor_strike"]) if row["floor_strike"] is not None else None,
        "cap_strike": float(row["cap_strike"]) if row["cap_strike"] is not None else None,
        "strike_type": row["strike_type"],
        "volume": str(_row_volume(row)),
        "had_liquidity": _row_had_liquidity(row),
    }


def build_archive_tree(rows: list[asyncpg.Record], *, period_limit: int) -> list[dict[str, Any]]:
    """Group settled liquid markets: series → bet name → time period."""
    periods: dict[str, dict[str, Any]] = {}

    for row in rows:
        if not _row_had_liquidity(row):
            continue

        event_ticker = row["event_ticker"]
        if event_ticker not in periods:
            series_title = row["series_title"] or row["series_ticker"] or "Unknown"
            event_title = row["event_title"] or event_ticker
            periods[event_ticker] = {
                "event_ticker": event_ticker,
                "event_title": event_title,
                "series_ticker": row["series_ticker"],
                "series_title": row["series_title"],
                "bet_name": series_title,
                "open_time": _iso(row["open_time"]),
                "close_time": _iso(row["close_time"]),
                "status": row["status"],
                "liquid_count": 0,
                "total_volume": 0.0,
            }

        period = periods[event_ticker]
        period["liquid_count"] += 1
        period["total_volume"] += _row_volume(row)

        open_time = _iso(row["open_time"])
        close_time = _iso(row["close_time"])
        if open_time and (period["open_time"] is None or open_time < period["open_time"]):
            period["open_time"] = open_time
        if close_time and (period["close_time"] is None or close_time > period["close_time"]):
            period["close_time"] = close_time

    sorted_periods = sorted(
        periods.values(),
        key=lambda p: p["close_time"] or "",
        reverse=True,
    )[:period_limit]

    series_map: dict[str, dict[str, Any]] = {}
    for period in sorted_periods:
        series_ticker = period["series_ticker"] or "UNKNOWN"
        if series_ticker not in series_map:
            series_map[series_ticker] = {
                "series_ticker": series_ticker,
                "series_title": period["series_title"] or series_ticker,
                "total_volume": 0.0,
                "period_count": 0,
                "bets": {},
            }

        series = series_map[series_ticker]
        bet_name = period["bet_name"]
        if bet_name not in series["bets"]:
            series["bets"][bet_name] = {
                "bet_name": bet_name,
                "total_volume": 0.0,
                "period_count": 0,
                "periods": [],
            }

        bet = series["bets"][bet_name]
        bet["periods"].append(period)
        bet["total_volume"] += period["total_volume"]
        bet["period_count"] += 1
        series["total_volume"] += period["total_volume"]
        series["period_count"] += 1

    tree: list[dict[str, Any]] = []
    for series_ticker in sorted(series_map.keys()):
        series = series_map[series_ticker]
        bets = []
        for bet_name in sorted(series["bets"].keys()):
            bet = series["bets"][bet_name]
            bet["periods"].sort(key=lambda p: p["close_time"] or "", reverse=True)
            bets.append(
                {
                    "bet_name": bet["bet_name"],
                    "total_volume": bet["total_volume"],
                    "period_count": bet["period_count"],
                    "periods": bet["periods"],
                }
            )
        bets.sort(key=lambda b: b["total_volume"], reverse=True)
        tree.append(
            {
                "series_ticker": series["series_ticker"],
                "series_title": series["series_title"],
                "total_volume": series["total_volume"],
                "period_count": series["period_count"],
                "bets": bets,
            }
        )

    tree.sort(key=lambda s: s["total_volume"], reverse=True)
    return tree


async def fetch_archive_tree(
    pool: asyncpg.Pool,
    *,
    series_ticker: str | None = None,
    period_limit: int = 40,
    scan_limit: int = 5000,
) -> list[dict[str, Any]]:
    period_limit = max(1, min(period_limit, 100))
    scan_limit = max(period_limit * 5, min(scan_limit, 20000))

    async with pool.acquire() as conn:
        rows = await conn.fetch(ARCHIVE_MARKETS_QUERY, series_ticker, scan_limit)

    return build_archive_tree(rows, period_limit=period_limit)


async def fetch_archive_events(
    pool: asyncpg.Pool,
    *,
    series_ticker: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    tree = await fetch_archive_tree(pool, series_ticker=series_ticker, period_limit=limit)
    events: list[dict[str, Any]] = []
    for series in tree:
        for bet in series["bets"]:
            for period in bet["periods"]:
                events.append(
                    {
                        "event_ticker": period["event_ticker"],
                        "series_ticker": period["series_ticker"],
                        "event_title": period["event_title"],
                        "series_title": period["series_title"],
                        "bet_name": bet["bet_name"],
                        "open_time": period["open_time"],
                        "close_time": period["close_time"],
                        "status": period["status"],
                        "market_count": period["liquid_count"],
                        "total_volume": period["total_volume"],
                    }
                )
    return events[:limit]


async def fetch_archive_event_markets(pool: asyncpg.Pool, event_ticker: str) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(ARCHIVE_EVENT_MARKETS_QUERY, event_ticker)

    return [_market_payload(row) for row in rows if _row_had_liquidity(row)]
