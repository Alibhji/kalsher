from __future__ import annotations

from decimal import Decimal

from trader.app.settlement import parse_kalshi_positions, settlement_price


def test_settlement_price_yes_wins():
    assert settlement_price("yes", "yes") == Decimal("1")
    assert settlement_price("no", "yes") == Decimal("0")


def test_settlement_price_no_wins():
    assert settlement_price("yes", "no") == Decimal("0")
    assert settlement_price("no", "no") == Decimal("1")


def test_parse_kalshi_positions_signed_net():
    rows = [
        {"ticker": "ABC", "position_fp": "3.00"},
        {"ticker": "DEF", "position_fp": "-2.50"},
        {"ticker": "GHI", "position_fp": "0.00"},
    ]
    out = parse_kalshi_positions(rows)
    assert out["ABC"] == {"yes": Decimal("3"), "no": Decimal("0")}
    assert out["DEF"] == {"yes": Decimal("0"), "no": Decimal("2.5")}
    assert out["GHI"] == {"yes": Decimal("0"), "no": Decimal("0")}
