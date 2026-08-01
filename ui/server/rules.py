from __future__ import annotations

import json
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from common.market_rules import build_market_rules_markdown

META_FIELDS = ("market", "event", "series")


def _json_blob(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


async def _load_from_redis(redis: aioredis.Redis, ticker: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    values = await redis.hmget(f"kalshi:market:{ticker}", *META_FIELDS)
    market = _json_blob(values[0] if values else None)
    event = _json_blob(values[1] if values and len(values) > 1 else None)
    series = _json_blob(values[2] if values and len(values) > 2 else None)
    return market, event, series


async def _load_from_db(pool: asyncpg.Pool, ticker: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT metadata FROM markets WHERE ticker = $1", ticker)
    if not row or not row["metadata"]:
        return {}, {}, {}

    meta = row["metadata"]
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            return {}, {}, {}
    if not isinstance(meta, dict):
        return {}, {}, {}

    return (
        meta.get("market") if isinstance(meta.get("market"), dict) else {},
        meta.get("event") if isinstance(meta.get("event"), dict) else {},
        meta.get("series") if isinstance(meta.get("series"), dict) else {},
    )


async def fetch_market_rules(
    redis: aioredis.Redis,
    pool: asyncpg.Pool,
    ticker: str,
) -> dict[str, Any] | None:
    market, _event, series = await _load_from_redis(redis, ticker)
    if not market.get("rules_primary") and not market.get("yes_sub_title"):
        db_market, _db_event, db_series = await _load_from_db(pool, ticker)
        if db_market:
            market = db_market
        if db_series:
            series = db_series

    if not market:
        return None

    markdown = build_market_rules_markdown(market, series=series)
    if not markdown:
        return None

    return {
        "ticker": ticker,
        "markdown": markdown,
        "yes_sub_title": market.get("yes_sub_title"),
        "rules_primary": market.get("rules_primary"),
        "rules_secondary": market.get("rules_secondary"),
        "expiration_value": market.get("expiration_value"),
        "settlement_sources": series.get("settlement_sources"),
    }
