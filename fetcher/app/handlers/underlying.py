from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from common.models import EventKind, NormalizedEvent, parse_decimal, parse_ts


def handle_pyth(msg: dict[str, Any]) -> NormalizedEvent | None:
    body = msg.get("msg") or {}
    symbol = body.get("underlying_ticker") or body.get("symbol") or body.get("ticker")
    price = parse_decimal(
        body.get("price")
        or body.get("price_dollars")
        or (body.get("avg_60s_data") or {}).get("value")
    )
    if not symbol or price is None:
        return None
    return NormalizedEvent(
        kind=EventKind.UNDERLYING,
        ticker=symbol,
        ts=datetime.now(timezone.utc),
        source_ts=parse_ts(body.get("ts") or body.get("publish_time") or body.get("received_at")),
        payload={"source": "pyth", "symbol": symbol, "price": price, "raw": body},
    )


def handle_cfbenchmarks(msg: dict[str, Any]) -> NormalizedEvent | None:
    body = msg.get("msg") or {}
    symbol = body.get("index_id") or body.get("symbol") or body.get("index")
    avg = body.get("avg_60s_data") or {}
    price = parse_decimal(avg.get("value") or body.get("value") or body.get("price"))
    if not symbol or price is None:
        return None
    return NormalizedEvent(
        kind=EventKind.UNDERLYING,
        ticker=symbol,
        ts=datetime.now(timezone.utc),
        source_ts=parse_ts(body.get("received_at") or body.get("ts") or body.get("timestamp")),
        payload={"source": "cfbenchmarks", "symbol": symbol, "price": price, "raw": body},
    )
