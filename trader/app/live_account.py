from __future__ import annotations

from decimal import Decimal
from typing import Any

from common.kalshi.auth import KalshiAuth
from common.kalshi.rest import KalshiRest
from common.settings import TraderSettings


def _dollars_from_balance(data: dict[str, Any]) -> Decimal:
    if data.get("balance_dollars") is not None:
        return Decimal(str(data["balance_dollars"]))
    cents = data.get("balance")
    if cents is not None:
        return Decimal(str(cents)) / Decimal("100")
    return Decimal("0")


def _dollars_from_portfolio(data: dict[str, Any]) -> Decimal:
    pv = data.get("portfolio_value")
    if pv is not None:
        return Decimal(str(pv)) / Decimal("100")
    return Decimal("0")


async def fetch_kalshi_account(settings: TraderSettings, client: KalshiRest | None = None) -> dict[str, Any]:
    if client is None:
        auth = KalshiAuth(settings.kalshi_key_id, settings.kalshi_private_key_path)
        client = KalshiRest(settings.kalshi_rest_base, auth, rps=settings.rest_rps)
    data = await client.get_balance()
    available = _dollars_from_balance(data)
    position_value = _dollars_from_portfolio(data)
    equity = available + position_value
    return {
        "available_funds": available,
        "portfolio_value": position_value,
        "equity": equity,
        "updated_ts": data.get("updated_ts"),
    }
