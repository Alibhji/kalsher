from __future__ import annotations

from decimal import Decimal

import redis.asyncio as aioredis


def _dec(val: str | None) -> Decimal | None:
    if val is None or val == "":
        return None
    try:
        return Decimal(val)
    except Exception:
        return None


async def is_book_stale(redis: aioredis.Redis, ticker: str) -> bool:
    val = await redis.hget(f"kalshi:market:{ticker}", "book_stale")
    return val in ("1", "true", "True")


async def get_quotes(redis: aioredis.Redis, ticker: str) -> dict[str, Decimal | None]:
    raw = await redis.hgetall(f"kalshi:market:{ticker}")
    return {
        "yes_bid": _dec(raw.get("yes_bid")),
        "yes_ask": _dec(raw.get("yes_ask")),
        "no_bid": _dec(raw.get("no_bid")),
        "no_ask": _dec(raw.get("no_ask")),
        "last_price": _dec(raw.get("last_price")),
    }


QUOTE_FIELDS = ("yes_bid", "yes_ask", "no_bid", "no_ask", "last_price")


async def get_quotes_many(
    redis: aioredis.Redis, tickers: list[str]
) -> dict[str, dict[str, Decimal | None]]:
    """One round trip for many tickers instead of one HGETALL each."""
    if not tickers:
        return {}
    pipe = redis.pipeline()
    for ticker in tickers:
        pipe.hmget(f"kalshi:market:{ticker}", *QUOTE_FIELDS)
    rows = await pipe.execute()
    return {
        ticker: {field: _dec(value) for field, value in zip(QUOTE_FIELDS, values or [])}
        for ticker, values in zip(tickers, rows)
    }


def mid_price(quotes: dict[str, Decimal | None], side: str) -> Decimal | None:
    if side == "yes":
        bid, ask = quotes.get("yes_bid"), quotes.get("yes_ask")
    else:
        bid, ask = quotes.get("no_bid"), quotes.get("no_ask")
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    if bid is not None:
        return bid
    if ask is not None:
        return ask
    last = quotes.get("last_price")
    if last is not None:
        return last
    return None


async def read_book_levels(redis: aioredis.Redis, ticker: str, side: str) -> list[tuple[Decimal, Decimal]]:
    """Return [(price, size), ...] sorted best bid first (highest price)."""
    key = f"kalshi:book:{ticker}:{side}"
    raw = await redis.zrevrange(key, 0, -1, withscores=True)
    levels: list[tuple[Decimal, Decimal]] = []
    for price_str, size in raw:
        size_d = Decimal(str(size))
        if size_d > 0:
            levels.append((Decimal(price_str), size_d))
    return levels


def yes_ask_from_no_book(no_bids: list[tuple[Decimal, Decimal]]) -> Decimal | None:
    if not no_bids:
        return None
    best_no_bid = no_bids[0][0]
    return Decimal("1") - best_no_bid


async def get_ask_levels_for_buy(
    redis: aioredis.Redis, ticker: str, side: str
) -> list[tuple[Decimal, Decimal]]:
    """Levels to walk when buying `side` (price, available_qty)."""
    if side == "yes":
        no_bids = await read_book_levels(redis, ticker, "no")
        return [(Decimal("1") - p, q) for p, q in no_bids]
    yes_bids = await read_book_levels(redis, ticker, "yes")
    return [(Decimal("1") - p, q) for p, q in yes_bids]


async def get_bid_levels_for_sell(
    redis: aioredis.Redis, ticker: str, side: str
) -> list[tuple[Decimal, Decimal]]:
    """Levels to walk when selling `side`."""
    return await read_book_levels(redis, ticker, side)
