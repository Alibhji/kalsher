from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from common.models import EventKind, NormalizedEvent, parse_decimal


def handle_lifecycle(msg: dict[str, Any]) -> NormalizedEvent | None:
    body = msg.get("msg") or {}
    ticker = body.get("market_ticker") or body.get("ticker")
    if not ticker:
        return None
    event_type = body.get("event_type") or body.get("type") or msg.get("type", "lifecycle")
    return NormalizedEvent(
        kind=EventKind.LIFECYCLE,
        ticker=ticker,
        ts=datetime.now(timezone.utc),
        payload={"event_type": event_type, "raw": body},
    )
