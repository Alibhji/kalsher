from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from common.liquidity import market_has_liquidity

UNIVERSE_KEY = "kalshi:universe"

HOT_HASH_FIELDS = (
    "yes_bid",
    "yes_ask",
    "last_price",
    "volume",
    "open_interest",
    "updated_at",
    "market",
    "event",
)

CARD_QUERY = """
SELECT
    ticker, title, event_ticker, series_ticker, category, status,
    open_time, close_time, expected_expiration_time,
    floor_strike, cap_strike, strike_type,
    event_title, series_title
FROM v_market_card
WHERE ticker = ANY($1::text[])
"""


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _json_field(raw: dict[str, str], key: str) -> dict[str, Any]:
    text = raw.get(key)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _price_cents(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return int((value * 100).quantize(Decimal("1")))


def _is_live(row: dict[str, Any], now: datetime) -> bool:
    status = row.get("status")
    if status and status != "active":
        return False
    open_time = row.get("open_time")
    close_time = row.get("close_time")
    if isinstance(open_time, datetime) and now < open_time:
        return False
    if isinstance(close_time, datetime) and now >= close_time:
        return False
    return status == "active"


def _slug(text: str | None) -> str:
    if not text:
        return "market"
    # Kalshi drops slashes without inserting a hyphen (e.g. "Above/below" → "abovebelow").
    lowered = text.lower()
    lowered = re.sub(r"/\s*", "", lowered)
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "market"


def _url_tail(ticker: str, event_ticker: str | None) -> str:
    return ticker.lower()


def _kalshi_url(
    web_base: str,
    ticker: str,
    *,
    event_ticker: str | None,
    series_ticker: str | None,
    series_title: str | None,
    event_title: str | None,
) -> str:
    base = web_base.rstrip("/")
    if series_ticker:
        series_slug = _slug(series_title or event_title or series_ticker)
        tail = _url_tail(ticker, event_ticker)
        return f"{base}/markets/{series_ticker.lower()}/{series_slug}/{tail}"
    if event_ticker:
        return f"{base}/markets/{event_ticker.lower()}"
    return f"{base}/markets/{ticker.lower()}"


def _event_kalshi_url(
    web_base: str,
    *,
    event_ticker: str | None,
    series_ticker: str | None,
    series_title: str | None,
    event_title: str | None,
) -> str | None:
    if not event_ticker or not series_ticker:
        return None
    base = web_base.rstrip("/")
    series_slug = _slug(series_title or event_title or series_ticker)
    return f"{base}/markets/{series_ticker.lower()}/{series_slug}/{event_ticker.lower()}"


def _derived_no_cents(yes_bid_cents: int | None, yes_ask_cents: int | None) -> tuple[int | None, int | None]:
    no_bid = (100 - yes_ask_cents) if yes_ask_cents is not None else None
    no_ask = (100 - yes_bid_cents) if yes_bid_cents is not None else None
    return no_bid, no_ask


def _merge_volume(raw: dict[str, str], market_json: dict[str, Any]) -> Decimal | None:
    # WS dollar_volume and REST volume_fp are the same quantity; WS volume_fp counts both
    # legs (~2x). The REST blob is written once at enrichment, so it is only a cold-start seed.
    live = _parse_decimal(raw.get("volume"))
    return live if live is not None else _parse_decimal(market_json.get("volume_fp"))


def _merge_open_interest(raw: dict[str, str], market_json: dict[str, Any]) -> Decimal | None:
    live = _parse_decimal(raw.get("open_interest"))
    return live if live is not None else _parse_decimal(market_json.get("open_interest_fp"))


def _serialize_row(row: dict[str, Any], web_base: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    close = row.get("close_time")
    open_time = row.get("open_time")
    seconds_to_close: int | None = None
    if isinstance(close, datetime):
        seconds_to_close = max(0, int((close - now).total_seconds()))

    yes_bid = row.get("yes_bid_cents")
    yes_ask = row.get("yes_ask_cents")
    no_bid, no_ask = _derived_no_cents(yes_bid, yes_ask)
    is_live = _is_live(row, now)
    volume = row.get("volume")
    has_liquidity = market_has_liquidity(yes_bid, yes_ask, volume_usd=volume)

    out: dict[str, Any] = {
        "ticker": row["ticker"],
        "event_ticker": row.get("event_ticker"),
        "title": row.get("title"),
        "event_title": row.get("event_title"),
        "series_ticker": row.get("series_ticker"),
        "series_title": row.get("series_title"),
        "category": row.get("category"),
        "status": row.get("status"),
        "open_time": open_time.isoformat() if isinstance(open_time, datetime) else open_time,
        "close_time": close.isoformat() if isinstance(close, datetime) else close,
        "floor_strike": float(row["floor_strike"]) if row.get("floor_strike") is not None else None,
        "cap_strike": float(row["cap_strike"]) if row.get("cap_strike") is not None else None,
        "strike_type": row.get("strike_type"),
        "yes_bid_cents": yes_bid,
        "yes_ask_cents": yes_ask,
        "no_bid_cents": no_bid,
        "no_ask_cents": no_ask,
        "volume": str(row["volume"]) if row.get("volume") is not None else None,
        "open_interest": str(row["open_interest"]) if row.get("open_interest") is not None else None,
        "seconds_to_close": seconds_to_close,
        "is_live": is_live,
        "has_quotes": yes_bid is not None or yes_ask is not None,
        "has_liquidity": has_liquidity,
        "kalshi_url": _kalshi_url(
            web_base,
            row["ticker"],
            event_ticker=row.get("event_ticker"),
            series_ticker=row.get("series_ticker"),
            series_title=row.get("series_title"),
            event_title=row.get("event_title"),
        ),
        "event_kalshi_url": _event_kalshi_url(
            web_base,
            event_ticker=row.get("event_ticker"),
            series_ticker=row.get("series_ticker"),
            series_title=row.get("series_title"),
            event_title=row.get("event_title"),
        ),
    }
    return out


async def fetch_markets(
    redis: aioredis.Redis,
    pool: asyncpg.Pool,
    *,
    web_base: str = "https://kalshi.com",
    drop_no_liquidity: bool = True,
    live_only: bool = True,
) -> dict[str, Any]:
    tickers = sorted(await redis.smembers(UNIVERSE_KEY))
    if not tickers:
        return {"markets": []}

    pipe = redis.pipeline()
    for ticker in tickers:
        pipe.hmget(f"kalshi:market:{ticker}", *HOT_HASH_FIELDS)
    redis_rows = await pipe.execute()

    cards: dict[str, asyncpg.Record] = {}
    async with pool.acquire() as conn:
        records = await conn.fetch(CARD_QUERY, tickers)
        cards = {r["ticker"]: r for r in records}

    merged: list[dict[str, Any]] = []
    for ticker, values in zip(tickers, redis_rows):
        raw = {
            field: value
            for field, value in zip(HOT_HASH_FIELDS, values or [])
            if value is not None
        }
        card = cards.get(ticker)
        market_json = _json_field(raw, "market")
        event_json = _json_field(raw, "event")

        close_time = _parse_dt(card["close_time"] if card else None) or _parse_dt(market_json.get("close_time"))
        open_time = _parse_dt(card["open_time"] if card else None) or _parse_dt(market_json.get("open_time"))
        floor = card["floor_strike"] if card and card["floor_strike"] is not None else _parse_decimal(market_json.get("floor_strike"))
        cap = card["cap_strike"] if card and card["cap_strike"] is not None else _parse_decimal(market_json.get("cap_strike"))

        yes_bid = _parse_decimal(raw.get("yes_bid")) or _parse_decimal(market_json.get("yes_bid_dollars"))
        yes_ask = _parse_decimal(raw.get("yes_ask")) or _parse_decimal(market_json.get("yes_ask_dollars"))
        volume = _merge_volume(raw, market_json)
        oi = _merge_open_interest(raw, market_json)

        row: dict[str, Any] = {
            "ticker": ticker,
            "event_ticker": (card["event_ticker"] if card else None) or market_json.get("event_ticker"),
            "title": (card["title"] if card else None) or market_json.get("title"),
            "event_title": (card["event_title"] if card else None) or event_json.get("title"),
            "series_ticker": (card["series_ticker"] if card else None) or market_json.get("series_ticker") or event_json.get("series_ticker"),
            "series_title": card["series_title"] if card else None,
            "category": (card["category"] if card else None) or event_json.get("category"),
            "status": (card["status"] if card else None) or market_json.get("status"),
            "open_time": open_time,
            "close_time": close_time,
            "floor_strike": floor,
            "cap_strike": cap,
            "strike_type": card["strike_type"] if card else market_json.get("strike_type"),
            "yes_bid_cents": _price_cents(yes_bid),
            "yes_ask_cents": _price_cents(yes_ask),
            "volume": volume,
            "open_interest": oi,
        }
        merged.append(row)

    merged.sort(key=lambda r: (r["close_time"] is None, r["close_time"] or datetime.max.replace(tzinfo=timezone.utc)))
    rows = [_serialize_row(r, web_base) for r in merged]
    if live_only:
        rows = [r for r in rows if r["is_live"]]
    if drop_no_liquidity:
        rows = [r for r in rows if r["has_liquidity"]]
    return {"markets": rows}
