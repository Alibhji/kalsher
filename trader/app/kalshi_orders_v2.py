from __future__ import annotations

from decimal import Decimal
from typing import Any

import redis.asyncio as aioredis

from trader.app.book import get_ask_levels_for_buy, get_bid_levels_for_sell, get_quotes, mid_price


def fp_count(qty: Decimal | int | float | str) -> str:
    return f"{Decimal(str(qty)):.2f}"


def fp_price(price: Decimal) -> str:
    clamped = max(Decimal("0.0001"), min(Decimal("0.9999"), price))
    return f"{clamped:.4f}"


def limit_to_v2(side: str, action: str, limit_price: Decimal | str) -> tuple[str, str]:
    lp = Decimal(str(limit_price))
    if side == "yes":
        book_side = "bid" if action == "buy" else "ask"
        yes_price = lp
    else:
        book_side = "ask" if action == "buy" else "bid"
        yes_price = Decimal("1") - lp
    return book_side, fp_price(yes_price)


async def market_to_v2(
    redis: aioredis.Redis,
    ticker: str,
    side: str,
    action: str,
) -> tuple[str, str]:
    if action == "buy":
        levels = await get_ask_levels_for_buy(redis, ticker, side)
        if not levels:
            quotes = await get_quotes(redis, ticker)
            leg_price = mid_price(quotes, side)
            if leg_price is None:
                raise ValueError("no liquidity for market order")
        else:
            leg_price = levels[0][0]
    else:
        levels = await get_bid_levels_for_sell(redis, ticker, side)
        if not levels:
            quotes = await get_quotes(redis, ticker)
            leg_price = mid_price(quotes, side)
            if leg_price is None:
                raise ValueError("no liquidity for market order")
        else:
            leg_price = levels[0][0]

    if side == "yes":
        yes_price = leg_price
        book_side = "bid" if action == "buy" else "ask"
    else:
        yes_price = Decimal("1") - leg_price
        book_side = "ask" if action == "buy" else "bid"
    return book_side, fp_price(yes_price)


async def build_kalshi_v2_order(
    redis: aioredis.Redis,
    *,
    ticker: str,
    side: str,
    action: str,
    qty: Decimal,
    order_type: str,
    limit_price: Decimal | None = None,
    client_order_id: str | None = None,
) -> dict[str, Any]:
    if order_type == "limit":
        if limit_price is None:
            raise ValueError("limit_price required for limit orders")
        book_side, price = limit_to_v2(side, action, limit_price)
        time_in_force = "good_till_canceled"
    else:
        book_side, price = await market_to_v2(redis, ticker, side, action)
        time_in_force = "immediate_or_cancel"

    body: dict[str, Any] = {
        "ticker": ticker,
        "side": book_side,
        "count": fp_count(qty),
        "price": price,
        "time_in_force": time_in_force,
        "self_trade_prevention_type": "taker_at_cross",
    }
    if client_order_id:
        body["client_order_id"] = client_order_id
    return body
