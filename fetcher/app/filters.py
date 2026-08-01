from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from common.liquidity import market_has_liquidity
from common.settings import FilterSettings

FilterFn = Callable[[dict[str, Any], FilterSettings, datetime], bool]


def status_active(market: dict[str, Any], settings: FilterSettings, now: datetime) -> bool:
    return market.get("status") == "active"


def time_to_close(market: dict[str, Any], settings: FilterSettings, now: datetime) -> bool:
    close = _parse_dt(market.get("close_time"))
    if close is None:
        return False
    return (close - now).total_seconds() <= settings.max_hours_to_close * 3600


def market_duration(market: dict[str, Any], settings: FilterSettings, now: datetime) -> bool:
    open_t = _parse_dt(market.get("open_time"))
    close = _parse_dt(market.get("close_time"))
    if open_t is None or close is None:
        return True
    return (close - open_t).total_seconds() <= settings.max_duration_hours * 3600


def category_allowlist(market: dict[str, Any], settings: FilterSettings, now: datetime) -> bool:
    if not settings.category_allowlist:
        return True
    category = market.get("category") or market.get("event_category") or ""
    return category in settings.category_allowlist


def series_allowlist(market: dict[str, Any], settings: FilterSettings, now: datetime) -> bool:
    if not settings.series_allowlist:
        return True
    series = market.get("series_ticker") or market.get("event_ticker", "").split("-")[0]
    return series in settings.series_allowlist


def has_liquidity(market: dict[str, Any], settings: FilterSettings, now: datetime) -> bool:
    bid = _price_cents(market.get("yes_bid_dollars") or market.get("yes_bid"))
    ask = _price_cents(market.get("yes_ask_dollars") or market.get("yes_ask"))
    vol = market.get("volume_fp") or market.get("volume")
    volume_usd = None
    if vol is not None and vol != "":
        try:
            volume_usd = float(vol)
        except (TypeError, ValueError):
            volume_usd = None
    if bid is None and ask is None and volume_usd is None:
        return True
    return market_has_liquidity(bid, ask, volume_usd=volume_usd)


def _price_cents(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


FILTER_REGISTRY: dict[str, FilterFn] = {
    "status_active": status_active,
    "time_to_close": time_to_close,
    "market_duration": market_duration,
    "category_allowlist": category_allowlist,
    "series_allowlist": series_allowlist,
    "has_liquidity": has_liquidity,
}


def apply_filters(market: dict[str, Any], settings: FilterSettings, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    for name in settings.enabled_filters:
        fn = FILTER_REGISTRY.get(name)
        if fn and not fn(market, settings, now):
            return False
    return True


def live_event_markets(markets: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Kalshi's calendar shows one event per series: the next one to close."""
    by_event: dict[str, list[dict[str, Any]]] = {}
    for market in markets:
        by_event.setdefault(market.get("event_ticker") or "", []).append(market)

    closes: dict[str, datetime] = {}
    for event, event_markets in by_event.items():
        valid = [_parse_dt(m.get("close_time")) for m in event_markets]
        parsed = [close for close in valid if close is not None]
        if parsed:
            closes[event] = min(parsed)

    upcoming = {event: close for event, close in closes.items() if close > now}
    if not upcoming:
        return []

    live_event = min(upcoming, key=upcoming.__getitem__)
    return by_event[live_event]


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
