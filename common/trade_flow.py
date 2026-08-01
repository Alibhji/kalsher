from __future__ import annotations

from decimal import Decimal
from typing import Any


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value)))
    except Exception:
        return None


def trade_notional_usd(payload: dict[str, Any]) -> float | None:
    """Dollar notional for one fill (YES-price × contracts)."""
    direct = _to_float(payload.get("dollar_amount") or payload.get("dollar_volume"))
    if direct is not None:
        return direct
    price = _to_float(payload.get("price"))
    count = _to_float(payload.get("count"))
    if price is None or count is None:
        return None
    return price * count


def trade_signed_usd(payload: dict[str, Any]) -> float | None:
    """YES-buy flow is positive; NO-buy (bearish on YES) is negative — matches Kalshi tape."""
    notional = trade_notional_usd(payload)
    if notional is None:
        return None
    side = str(payload.get("taker_side") or "").lower()
    if side == "yes":
        return notional
    if side == "no":
        return -notional
    return None
