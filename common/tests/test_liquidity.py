from common.liquidity import market_has_liquidity


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


def test_zero_volume_is_not_liquid() -> None:
    assert not market_has_liquidity(59, 60, volume_usd=0)


if __name__ == "__main__":
    test_no_quotes()
    test_tight_book()
    test_empty_book_1_99()
    test_empty_book_2_100()
    test_one_sided_yes_ask()
    test_one_sided_yes_bid()
    test_zero_volume_is_not_liquid()
    print("ok")
