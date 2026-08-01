from __future__ import annotations

from datetime import datetime, timezone

from common.settings import FilterSettings
from fetcher.app.filters import apply_filters, live_event_markets


def test_status_active():
    settings = FilterSettings()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    close = "2026-01-01T13:00:00Z"
    assert apply_filters({"status": "active", "open_time": "2026-01-01T11:00:00Z", "close_time": close}, settings, now)
    assert not apply_filters({"status": "closed", "open_time": "2026-01-01T11:00:00Z", "close_time": close}, settings, now)


def test_market_duration():
    settings = FilterSettings(max_duration_hours=3)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    market = {
        "status": "active",
        "open_time": "2026-01-01T10:00:00Z",
        "close_time": "2026-01-01T12:30:00Z",
    }
    assert apply_filters(market, settings, now)


def test_series_allowlist():
    settings = FilterSettings(
        series_allowlist=["KXBTC15M", "KXBTCD"],
        enabled_filters=["status_active", "series_allowlist"],
    )
    now = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)
    assert apply_filters(
        {"status": "active", "series_ticker": "KXBTC15M", "ticker": "KXBTC15M-26AUG010245"},
        settings,
        now,
    )
    assert not apply_filters(
        {"status": "active", "series_ticker": "KXMLBGAME", "ticker": "KXMLBGAME-FOO"},
        settings,
        now,
    )


def test_live_event_markets_picks_hourly_window():
    now = datetime(2026, 8, 1, 6, 30, tzinfo=timezone.utc)
    markets = [
        {"event_ticker": "KXBTCD-26AUG0103", "ticker": "KXBTCD-26AUG0103-T100000", "close_time": "2026-08-01T07:00:00Z"},
        {"event_ticker": "KXBTCD-26AUG0103", "ticker": "KXBTCD-26AUG0103-T110000", "close_time": "2026-08-01T07:00:00Z"},
        {"event_ticker": "KXBTCD-26AUG0117", "ticker": "KXBTCD-26AUG0117-T100000", "close_time": "2026-08-01T21:00:00Z"},
        {"event_ticker": "KXBTCD-26AUG0717", "ticker": "KXBTCD-26AUG0717-T100000", "close_time": "2026-08-07T21:00:00Z"},
    ]
    live = live_event_markets(markets, now)
    assert {m["ticker"] for m in live} == {
        "KXBTCD-26AUG0103-T100000",
        "KXBTCD-26AUG0103-T110000",
    }


def test_has_liquidity_filter_allows_missing_quotes():
    settings = FilterSettings(enabled_filters=["has_liquidity"])
    now = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)
    assert apply_filters({"status": "active", "ticker": "FOO"}, settings, now)


def test_has_liquidity_filter_drops_empty_book():
    settings = FilterSettings(enabled_filters=["has_liquidity"])
    now = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)
    assert not apply_filters(
        {"status": "active", "yes_bid_dollars": "0.01", "yes_ask_dollars": "0.99"},
        settings,
        now,
    )


if __name__ == "__main__":
    test_status_active()
    test_market_duration()
    test_series_allowlist()
    test_live_event_markets_picks_hourly_window()
    test_has_liquidity_filter_allows_missing_quotes()
    test_has_liquidity_filter_drops_empty_book()
    print("ok")
