from common.trade_flow import trade_notional_usd, trade_signed_usd


def test_trade_signed_usd_yes_buy() -> None:
    signed = trade_signed_usd({"price": "0.60", "count": "5", "taker_side": "yes"})
    assert signed == 3.0


def test_trade_signed_usd_no_buy() -> None:
    signed = trade_signed_usd({"price": "0.60", "count": "200", "taker_side": "no"})
    assert signed == -120.0


def test_trade_notional_prefers_dollar_amount() -> None:
    assert trade_notional_usd({"dollar_amount": "42.5", "price": "0.1", "count": "1"}) == 42.5
