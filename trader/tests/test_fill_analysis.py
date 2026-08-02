from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from trader.app.fill_analysis import (
    annotate_fills_pnl,
    annotate_fills_pnl_with_settlements,
    clear_kalshi_fills_cache,
    normalize_kalshi_fill,
    resolve_kalshi_side_action,
    simulate_round_trips,
)
from trader.app.settlement import settlement_price


def _ts(hour: int = 12) -> datetime:
    return datetime(2026, 8, 1, hour, 0, 0, tzinfo=timezone.utc)


def test_normalize_kalshi_fill_uses_fee_cost_and_yes_price():
    raw = {
        "fill_id": "f1",
        "market_ticker": "KXTEST-T1",
        "side": "yes",
        "action": "buy",
        "count_fp": "10.00",
        "yes_price_dollars": "0.40",
        "no_price_dollars": "0.60",
        "fee_cost": "0.07",
        "created_time": "2026-08-01T12:00:00Z",
    }
    fill = normalize_kalshi_fill(raw, source="kalshi_live")
    assert fill["side"] == "yes"
    assert fill["action"] == "buy"
    assert fill["price"] == Decimal("0.40")
    assert fill["qty"] == Decimal("10.00")
    assert fill["fee"] == Decimal("0.07")
    assert fill["cash_delta"] == Decimal("-4.07")


def test_resolve_prefers_legacy_action_side():
    side, action = resolve_kalshi_side_action(
        {"side": "yes", "action": "sell", "outcome_side": "no", "book_side": "ask"}
    )
    assert (side, action) == ("yes", "sell")


def test_resolve_book_fallback_sell_yes():
    side, action = resolve_kalshi_side_action({"outcome_side": "no", "book_side": "ask"})
    assert (side, action) == ("yes", "sell")


def test_buy_sell_trade_pnl_only_on_sell_with_fees():
    fills = [
        {
            "id": "buy1",
            "ts": _ts(10),
            "ticker": "KXTEST-T1",
            "side": "yes",
            "action": "buy",
            "price": Decimal("0.40"),
            "qty": Decimal("10"),
            "fee": Decimal("0.07"),
            "cash_delta": Decimal("-4.07"),
        },
        {
            "id": "sell1",
            "ts": _ts(11),
            "ticker": "KXTEST-T1",
            "side": "yes",
            "action": "sell",
            "price": Decimal("0.55"),
            "qty": Decimal("10"),
            "fee": Decimal("0.08"),
            "cash_delta": Decimal("5.42"),
        },
    ]
    out = annotate_fills_pnl(fills)
    by_id = {r["id"]: r for r in out}
    assert by_id["buy1"]["trade_pnl"] is None
    # gross = (0.55-0.40)*10 = 1.50; fees = 0.07+0.08 = 0.15; net = 1.35
    assert by_id["sell1"]["trade_pnl"] == Decimal("1.35")

    trips = simulate_round_trips(fills)
    assert len(trips) == 1
    assert trips[0]["net_pnl"] == Decimal("1.35")
    assert trips[0]["fees"] == Decimal("0.15")


@pytest.mark.asyncio
async def test_settlement_pnl_only_on_entry_buy():
    fills = [
        {
            "id": "buy1",
            "ts": _ts(10),
            "ticker": "KXTEST-T1",
            "side": "yes",
            "action": "buy",
            "price": Decimal("0.40"),
            "qty": Decimal("10"),
            "fee": Decimal("0.07"),
            "cash_delta": Decimal("-4.07"),
        },
    ]

    class FakeClient:
        async def get_market(self, ticker: str) -> dict[str, Any]:
            return {
                "market": {
                    "status": "finalized",
                    "result": "yes",
                    "close_time": "2026-08-01T15:00:00Z",
                }
            }

    out = await annotate_fills_pnl_with_settlements(FakeClient(), fills, end=_ts(16))
    assert len(out) == 1
    # gross = (1.0-0.40)*10 = 6.0; fees = 0.07; net = 5.93
    assert out[0]["trade_pnl"] == Decimal("5.93")
    assert settlement_price("yes", "yes") == Decimal("1")


@pytest.mark.asyncio
async def test_annotate_with_settlements_no_double_pnl_on_closed_leg():
    fills = [
        {
            "id": "buy1",
            "ts": _ts(10),
            "ticker": "KXTEST-T1",
            "side": "yes",
            "action": "buy",
            "price": Decimal("0.40"),
            "qty": Decimal("10"),
            "fee": Decimal("0.07"),
            "cash_delta": Decimal("-4.07"),
        },
        {
            "id": "sell1",
            "ts": _ts(11),
            "ticker": "KXTEST-T1",
            "side": "yes",
            "action": "sell",
            "price": Decimal("0.55"),
            "qty": Decimal("10"),
            "fee": Decimal("0.08"),
            "cash_delta": Decimal("5.42"),
        },
    ]

    class FakeClient:
        async def get_market(self, ticker: str) -> dict[str, Any]:
            return {"market": {"status": "open"}}

    out = await annotate_fills_pnl_with_settlements(FakeClient(), fills, end=_ts(16))
    by_id = {r["id"]: r for r in out}
    assert by_id["buy1"]["trade_pnl"] is None
    assert by_id["sell1"]["trade_pnl"] == Decimal("1.35")
    # Exactly one fill carries realized P&L
    assert sum(1 for r in out if r["trade_pnl"] is not None) == 1


def test_clear_kalshi_fills_cache():
    clear_kalshi_fills_cache()
