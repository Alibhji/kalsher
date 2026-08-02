from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from common.kalshi.rest import KalshiRest

TERMINAL_STATUSES = frozenset({"finalized", "settled", "determined", "closed"})


def settlement_price(side: str, result: str) -> Decimal:
    side = side.lower()
    result = result.lower()
    if side == "yes":
        return Decimal("1") if result == "yes" else Decimal("0")
    return Decimal("1") if result == "no" else Decimal("0")


def parse_kalshi_positions(market_positions: list[dict[str, Any]]) -> dict[str, dict[str, Decimal]]:
    """Map ticker -> {yes: qty, no: qty} from Kalshi position_fp (signed net)."""
    out: dict[str, dict[str, Decimal]] = {}
    for row in market_positions:
        ticker = str(row.get("ticker") or row.get("market_ticker") or "")
        if not ticker:
            continue
        fp = Decimal(str(row.get("position_fp") or row.get("position") or "0"))
        if fp > 0:
            out[ticker] = {"yes": fp, "no": Decimal("0")}
        elif fp < 0:
            out[ticker] = {"yes": Decimal("0"), "no": abs(fp)}
        else:
            out[ticker] = {"yes": Decimal("0"), "no": Decimal("0")}
    return out


def _result_from_market_dict(market: dict[str, Any]) -> str | None:
    result = str(market.get("result") or "").lower().strip()
    if result in ("yes", "no"):
        return result
    return None


async def resolve_market_result(
    pool: asyncpg.Pool,
    client: KalshiRest,
    ticker: str,
) -> tuple[str | None, str | None]:
    """Return (result, status) when the market is terminal and has a result."""
    status: str | None = None
    try:
        data = await client.get_market(ticker)
        market = data.get("market") if isinstance(data.get("market"), dict) else data
        status = str(market.get("status") or "").lower()
        result = _result_from_market_dict(market)
        if status in TERMINAL_STATUSES and result:
            return result, status
    except Exception:
        pass

    row = await pool.fetchrow("SELECT status, metadata FROM markets WHERE ticker = $1", ticker)
    if not row:
        return None, status
    status = str(row["status"] or "").lower()
    meta = row["metadata"]
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    market_meta = (meta or {}).get("market") if isinstance(meta, dict) else {}
    result = _result_from_market_dict(market_meta or {})
    if status in TERMINAL_STATUSES and result:
        return result, status
    return None, status


async def fetch_kalshi_position_map(client: KalshiRest) -> dict[str, dict[str, Decimal]]:
    data = await client.get_positions()
    return parse_kalshi_positions(data.get("market_positions") or [])
