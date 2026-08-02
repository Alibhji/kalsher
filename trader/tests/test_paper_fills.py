from __future__ import annotations

from decimal import Decimal

from trader.app.book import yes_ask_from_no_book


def test_yes_ask_from_no_book():
    no_bids = [(Decimal("0.47"), Decimal("100"))]
    ask = yes_ask_from_no_book(no_bids)
    assert ask == Decimal("0.53")
