from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from common.models import EventKind, NormalizedEvent, parse_decimal, parse_ts


def _now() -> datetime:
    return datetime.now(timezone.utc)


def handle_ticker(msg: dict[str, Any]) -> NormalizedEvent | None:
    body = msg.get("msg") or {}
    ticker = body.get("market_ticker")
    if not ticker:
        return None
    return NormalizedEvent(
        kind=EventKind.TICK,
        ticker=ticker,
        ts=_now(),
        source_ts=parse_ts(body.get("ts")),
        payload={
            "yes_bid": parse_decimal(body.get("yes_bid_dollars")),
            "yes_ask": parse_decimal(body.get("yes_ask_dollars")),
            "no_bid": parse_decimal(body.get("no_bid_dollars")),
            "no_ask": parse_decimal(body.get("no_ask_dollars")),
            "last_price": parse_decimal(body.get("price_dollars") or body.get("last_price_dollars")),
            # REST volume_fp == WS dollar_volume (matched notional); WS volume_fp counts both legs (~2x).
            "volume": parse_decimal(body.get("dollar_volume")) or parse_decimal(body.get("volume_fp")),
            "open_interest": parse_decimal(body.get("dollar_open_interest")) or parse_decimal(body.get("open_interest_fp")),
            "volume_contracts_fp": parse_decimal(body.get("volume_fp")),
            "open_interest_contracts_fp": parse_decimal(body.get("open_interest_fp")),
            "raw": body,
        },
    )


def handle_trade(msg: dict[str, Any]) -> NormalizedEvent | None:
    body = msg.get("msg") or {}
    ticker = body.get("market_ticker")
    if not ticker:
        return None
    return NormalizedEvent(
        kind=EventKind.TRADE,
        ticker=ticker,
        ts=_now(),
        source_ts=parse_ts(body.get("ts")),
        payload={
            "price": parse_decimal(body.get("yes_price_dollars") or body.get("price_dollars")),
            "count": parse_decimal(body.get("count_fp") or body.get("count")),
            "taker_side": body.get("taker_side"),
            "trade_id": body.get("trade_id"),
            "raw": body,
        },
    )
