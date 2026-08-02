from __future__ import annotations

from decimal import Decimal

from trader.app.settlement import _result_from_market_dict, _result_from_metadata, settlement_price


def test_settlement_price_no_side_wins_on_no_result():
    assert settlement_price("no", "no") == Decimal("1")
    assert settlement_price("yes", "no") == Decimal("0")


def test_result_from_metadata_nested_market():
    meta = {"market": {"result": "yes", "status": "finalized"}}
    assert _result_from_metadata(meta) == "yes"


def test_lifecycle_payload_parsing():
    payload = {
        "event_type": "determined",
        "raw": {"result": "no", "event_type": "determined", "market_ticker": "FOO"},
    }
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    assert _result_from_market_dict(raw) == "no"
