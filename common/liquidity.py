from __future__ import annotations

from decimal import Decimal

from common.prices import MAX_PRICE, MIN_TICK


def market_has_liquidity_dollars(
    yes_bid: Decimal | None,
    yes_ask: Decimal | None,
    *,
    volume_usd: Decimal | float | None = None,
) -> bool:
    """True when the strike has dollar volume and a tradeable book (dollar-space)."""
    if volume_usd is not None and Decimal(str(volume_usd)) <= 0:
        return False

    if yes_bid is None and yes_ask is None:
        return False

    if yes_bid is not None and yes_ask is not None:
        if yes_ask <= yes_bid:
            return False
        if yes_ask - yes_bid >= Decimal("0.98"):
            return False

    can_buy_yes = yes_ask is not None and MIN_TICK <= yes_ask <= MAX_PRICE
    no_ask = (Decimal("1") - yes_bid) if yes_bid is not None else None
    can_buy_no = no_ask is not None and MIN_TICK <= no_ask <= MAX_PRICE
    return can_buy_yes or can_buy_no


def market_has_liquidity(
    yes_bid_cents: int | float | None,
    yes_ask_cents: int | float | None,
    *,
    volume_usd: Decimal | float | None = None,
) -> bool:
    """Legacy int-cent entry point — prefer market_has_liquidity_dollars when possible."""
    yes_bid = Decimal(str(yes_bid_cents)) / 100 if yes_bid_cents is not None else None
    yes_ask = Decimal(str(yes_ask_cents)) / 100 if yes_ask_cents is not None else None
    return market_has_liquidity_dollars(yes_bid, yes_ask, volume_usd=volume_usd)
