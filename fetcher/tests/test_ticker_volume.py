from decimal import Decimal

from fetcher.app.handlers.ticker import handle_ticker


def test_ticker_ws_volume_fp_is_twice_dollar_volume() -> None:
    ev = handle_ticker(
        {
            "msg": {
                "market_ticker": "KXETH15M-26AUG011245-45",
                "volume_fp": "73895.22",
                "dollar_volume": 36947,
                "open_interest_fp": "34718.02",
                "dollar_open_interest": 17359,
            }
        }
    )
    assert ev is not None
    assert str(ev.payload["volume"]) == "36947"
    assert str(ev.payload["volume_contracts_fp"]) == "73895.22"
    assert Decimal(str(ev.payload["volume_contracts_fp"])) == Decimal(str(ev.payload["volume"])) * 2


def test_ticker_uses_dollar_volume_to_match_kalshi_ui() -> None:
    ev = handle_ticker(
        {
            "msg": {
                "market_ticker": "KXETHD-26AUG0113-T1874.99",
                "volume_fp": "970.98",
                "dollar_volume": 485,
                "open_interest_fp": "930.92",
                "dollar_open_interest": 465,
                "yes_bid_dollars": "0.0400",
                "yes_ask_dollars": "0.0700",
            }
        }
    )
    assert ev is not None
    assert str(ev.payload["volume"]) == "485"
    assert str(ev.payload["open_interest"]) == "465"
    assert str(ev.payload["volume_contracts_fp"]) == "970.98"


if __name__ == "__main__":
    test_ticker_uses_dollar_volume_to_match_kalshi_ui()
    print("ok")
