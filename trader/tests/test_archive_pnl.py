"""Archive event P/L helpers — ticker scoping via markets.event_ticker."""

from __future__ import annotations

import re


def event_ticker_from_market_ticker(ticker: str) -> str:
    """Mirror ui/web/src/lib/archivePnl.ts eventTickerFromMarketTicker."""
    m = re.match(r"^(.*)-T-?\d+(?:\.\d+)?$", ticker, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.match(r"^(.*)-(\d{1,4})$", ticker)
    if m:
        return m.group(1)
    return ticker


def test_event_ticker_daily_t_strike():
    assert (
        event_ticker_from_market_ticker("KXBTCD-26AUG0211-T62999.99")
        == "KXBTCD-26AUG0211"
    )
    assert (
        event_ticker_from_market_ticker("KXBTCD-26AUG0200-T63399.99")
        == "KXBTCD-26AUG0200"
    )


def test_event_ticker_15m_numeric_suffix():
    assert (
        event_ticker_from_market_ticker("KXBTC15M-26AUG021145-45")
        == "KXBTC15M-26AUG021145"
    )
    assert (
        event_ticker_from_market_ticker("KXBNB15M-26AUG011900-00")
        == "KXBNB15M-26AUG011900"
    )
    assert (
        event_ticker_from_market_ticker("KXDOGE15M-26AUG011930-30")
        == "KXDOGE15M-26AUG011930"
    )


def test_event_ticker_passthrough():
    assert event_ticker_from_market_ticker("KXBTCD-26AUG0211") == "KXBTCD-26AUG0211"


def test_legacy_dash_t_only_heuristic_fails_15m():
    """Document the bug we fixed: lastIndexOf('-T') misses 15M markets."""
    ticker = "KXBTC15M-26AUG021145-45"
    idx = ticker.rfind("-T")
    legacy = ticker[:idx] if idx > 0 else ticker
    assert legacy == ticker  # broken legacy behavior
    assert event_ticker_from_market_ticker(ticker) == "KXBTC15M-26AUG021145"
