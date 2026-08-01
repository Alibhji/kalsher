from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

import msgspec


def parse_decimal(value: str | int | float | None) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def parse_ts(value: str | int | float | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1_000_000_000_000:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class EventKind(str, Enum):
    TICK = "tick"
    TRADE = "trade"
    BOOK_DELTA = "book_delta"
    BOOK_SNAPSHOT = "book_snapshot"
    LIFECYCLE = "lifecycle"
    UNDERLYING = "underlying"
    MARKET_META = "market_meta"


class NormalizedEvent(msgspec.Struct, kw_only=True):
    kind: EventKind
    ticker: str
    ts: datetime
    payload: dict[str, Any]
    source_ts: datetime | None = None


class MarketMeta(msgspec.Struct, kw_only=True):
    ticker: str
    event_ticker: str
    series_ticker: str | None = None
    title: str | None = None
    yes_sub_title: str | None = None
    no_sub_title: str | None = None
    status: str | None = None
    open_time: datetime | None = None
    close_time: datetime | None = None
    expected_expiration_time: datetime | None = None
    latest_expiration_time: datetime | None = None
    yes_bid_dollars: Decimal | None = None
    yes_ask_dollars: Decimal | None = None
    no_bid_dollars: Decimal | None = None
    no_ask_dollars: Decimal | None = None
    last_price_dollars: Decimal | None = None
    volume_fp: Decimal | None = None
    volume_24h_fp: Decimal | None = None
    open_interest_fp: Decimal | None = None
    category: str | None = None
    raw: dict[str, Any] = msgspec.field(default_factory=dict)
