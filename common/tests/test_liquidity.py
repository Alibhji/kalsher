from decimal import Decimal

from common.liquidity import market_has_liquidity, market_has_liquidity_dollars
from common.prices import quote_cents_display


def test_no_quotes() -> None:
    assert not market_has_liquidity(None, None)


def test_tight_book() -> None:
    assert market_has_liquidity(59, 60)


def test_empty_book_1_99() -> None:
    assert not market_has_liquidity(1, 99)


def test_empty_book_2_100() -> None:
    assert not market_has_liquidity(2, 100)


def test_one_sided_yes_ask() -> None:
    assert market_has_liquidity(None, 54)


def test_one_sided_yes_bid() -> None:
    assert market_has_liquidity(46, None)


def test_near_certain_yes_98_99() -> None:
    assert market_has_liquidity(98, 99)


def test_near_certain_no_via_bid_99() -> None:
    assert market_has_liquidity(99, 100)


def test_one_sided_yes_ask_99() -> None:
    assert market_has_liquidity(None, 99)


def test_sub_cent_book_is_liquid() -> None:
    # 0.0¢ / 0.1¢ — old int truncation showed 0/0 and blocked the chart.
    assert market_has_liquidity_dollars(
        Decimal("0.0000"),
        Decimal("0.0010"),
        volume_usd=1000,
    )


def test_sub_cent_display() -> None:
    assert quote_cents_display(Decimal("0.0010")) == 0.1
    assert quote_cents_display(Decimal("0.9920")) == 99.2


def test_zero_volume_is_not_liquid() -> None:
    assert not market_has_liquidity(59, 60, volume_usd=0)
