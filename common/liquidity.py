from __future__ import annotations

from decimal import Decimal


def market_has_liquidity(
    yes_bid_cents: int | None,
    yes_ask_cents: int | None,
    *,
    volume_usd: Decimal | float | None = None,
) -> bool:
    """True when the strike has dollar volume and a tradeable book."""
    if volume_usd is not None and Decimal(str(volume_usd)) <= 0:
        return False

    if yes_bid_cents is None and yes_ask_cents is None:
        return False

    if yes_bid_cents is not None and yes_ask_cents is not None:
        if yes_ask_cents <= yes_bid_cents:
            return False
        if yes_ask_cents - yes_bid_cents >= 98:
            return False

    can_buy_yes = yes_ask_cents is not None and 2 <= yes_ask_cents <= 98
    no_ask = (100 - yes_bid_cents) if yes_bid_cents is not None else None
    can_buy_no = no_ask is not None and 2 <= no_ask <= 98
    return can_buy_yes or can_buy_no
