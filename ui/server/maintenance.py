from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from common.logging import get_logger

log = get_logger(__name__)

CONFIRM_PHRASE = "RESET PLATFORM"

HISTORY_TABLES = (
    "ticks",
    "trades",
    "book_deltas",
    "underlying_prices",
    "lifecycle_events",
    "markets",
)

CONTINUOUS_AGGREGATES = (
    "market_1s",
    "underlying_1s",
)

TRADING_TABLES = (
    "trading.fills",
    "trading.orders",
    "trading.positions",
    "trading.round_trips",
    "trading.equity_curve",
    "trading.experiments",
)

ALL_TABLES = HISTORY_TABLES + TRADING_TABLES + CONTINUOUS_AGGREGATES


async def _truncate_tables(pool: asyncpg.Pool, tables: tuple[str, ...], *, optional: bool = False) -> None:
    if not tables:
        return
    sql = f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"
    async with pool.acquire() as conn:
        try:
            await conn.execute(sql)
        except asyncpg.UndefinedTableError:
            if not optional:
                raise


async def reset_database(pool: asyncpg.Pool) -> dict[str, int]:
    """Drop all rows immediately — no pre-count (COUNT on hypertables is very slow)."""
    await asyncio.gather(
        _truncate_tables(pool, HISTORY_TABLES),
        _truncate_tables(pool, CONTINUOUS_AGGREGATES, optional=True),
        _truncate_tables(pool, TRADING_TABLES, optional=True),
    )
    return dict.fromkeys(ALL_TABLES, 0)


async def reset_redis(redis: aioredis.Redis) -> int:
    """Instant wipe of the current Redis DB (dedicated kalshi cache)."""
    try:
        await redis.flushdb(asynchronous=True)
        return 0
    except TypeError:
        # Older redis-py without asynchronous= kwarg.
        await redis.flushdb()
        return 0
    except Exception as exc:
        log.warning("redis_flushdb_failed", error=str(exc))
        deleted = 0
        batch: list[str] = []
        async for key in redis.scan_iter(match="kalshi:*", count=1000):
            batch.append(key)
            if len(batch) >= 1000:
                deleted += await redis.unlink(*batch)
                batch.clear()
        if batch:
            deleted += await redis.unlink(*batch)
        return deleted


async def reset_platform(pool: asyncpg.Pool, redis: aioredis.Redis) -> dict[str, Any]:
    db_deleted, redis_keys = await asyncio.gather(
        reset_database(pool),
        reset_redis(redis),
    )
    log.critical("platform_reset", database=db_deleted, redis_keys=redis_keys)
    return {
        "database": db_deleted,
        "redis_keys_deleted": redis_keys,
        "tables": list(HISTORY_TABLES) + list(TRADING_TABLES) + list(CONTINUOUS_AGGREGATES),
        "cleared": True,
    }
