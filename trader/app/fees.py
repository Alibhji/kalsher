from __future__ import annotations

from decimal import ROUND_CEILING, Decimal


def kalshi_taker_fee(qty: Decimal, price: Decimal) -> Decimal:
    """Kalshi fee: 0.07 * qty * P * (1-P) dollars, rounded up to the next cent."""
    if qty <= 0 or price <= 0 or price >= 1:
        return Decimal("0")
    raw = Decimal("0.07") * qty * price * (Decimal("1") - price)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def maker_fee(qty: Decimal, price: Decimal, maker_bps: int = 0) -> Decimal:
    if maker_bps <= 0:
        return Decimal("0")
    return qty * price * Decimal(maker_bps) / Decimal("10000")


def compute_fee(qty: Decimal, price: Decimal, liquidity: str, maker_bps: int = 0) -> Decimal:
    if liquidity == "maker":
        return maker_fee(qty, price, maker_bps)
    return kalshi_taker_fee(qty, price)
