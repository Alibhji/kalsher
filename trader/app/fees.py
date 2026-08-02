from __future__ import annotations

import math
from decimal import Decimal


def kalshi_taker_fee(qty: Decimal, price: Decimal) -> Decimal:
    """Kalshi fee: ceil(0.07 * qty * P * (1-P)) cents, returned in dollars."""
    if qty <= 0 or price <= 0 or price >= 1:
        return Decimal("0")
    raw_cents = Decimal("0.07") * qty * price * (Decimal("1") - price)
    cents = Decimal(str(math.ceil(float(raw_cents * 100)))) / Decimal("100")
    return cents


def maker_fee(qty: Decimal, price: Decimal, maker_bps: int = 0) -> Decimal:
    if maker_bps <= 0:
        return Decimal("0")
    return qty * price * Decimal(maker_bps) / Decimal("10000")


def compute_fee(qty: Decimal, price: Decimal, liquidity: str, maker_bps: int = 0) -> Decimal:
    if liquidity == "maker":
        return maker_fee(qty, price, maker_bps)
    return kalshi_taker_fee(qty, price)
