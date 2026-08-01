from ui.server.markets import (
    _event_kalshi_url,
    _kalshi_url,
    _slug,
)


def test_slug() -> None:
    assert _slug("Bitcoin price Above/below") == "bitcoin-price-abovebelow"
    assert _slug("Dogecoin 15 Minute") == "dogecoin-15-minute"


def test_kalshi_url_btc_15m_market() -> None:
    url = _kalshi_url(
        "https://kalshi.com",
        "KXBTC15M-25DEC222345-45",
        event_ticker="KXBTC15M-25DEC222345",
        series_ticker="KXBTC15M",
        series_title="Bitcoin price up down",
        event_title="BTC Up or Down - 15 minutes",
    )
    assert url == "https://kalshi.com/markets/kxbtc15m/bitcoin-price-up-down/kxbtc15m-25dec222345-45"


def test_event_kalshi_url_btcd() -> None:
    url = _event_kalshi_url(
        "https://kalshi.com",
        event_ticker="KXBTCD-26AUG0103",
        series_ticker="KXBTCD",
        series_title="Bitcoin price Above/below",
        event_title="BTC price today at 3am EDT",
    )
    assert url == "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-26aug0103"


def test_kalshi_url_btcd_strike() -> None:
    url = _kalshi_url(
        "https://kalshi.com",
        "KXBTCD-26AUG0103-T72799.99",
        event_ticker="KXBTCD-26AUG0103",
        series_ticker="KXBTCD",
        series_title="Bitcoin price Above/below",
        event_title="BTC price today at 3am EDT",
    )
    assert url == "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-26aug0103-t72799.99"


