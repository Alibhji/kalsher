"""Paper fill / book BBO parity with Kalshi semantics."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from trader.app.book import (
    asks_from_opposite_bids,
    normalize_bid_levels,
    yes_ask_from_no_book,
)
from trader.app.engine.paper import PaperEngine


def test_yes_ask_from_no_book():
    no_bids = [(Decimal("0.47"), Decimal("100"))]
    ask = yes_ask_from_no_book(no_bids)
    assert ask == Decimal("0.53")


def test_normalize_bid_levels_sorts_by_price_not_size():
    """Largest size must not win BBO — Redis ZSET score is size."""
    # size-desc order as ZREVRANGE would return
    raw = [
        (Decimal("0.001"), Decimal("14721")),
        (Decimal("0.33"), Decimal("3200")),
        (Decimal("0.52"), Decimal("84")),
        (Decimal("0.34"), Decimal("30")),
    ]
    bids = normalize_bid_levels(raw)
    assert bids[0][0] == Decimal("0.52")
    assert [p for p, _ in bids] == [
        Decimal("0.52"),
        Decimal("0.34"),
        Decimal("0.33"),
        Decimal("0.001"),
    ]


def test_normalize_bid_levels_drops_dust():
    raw = [
        (Decimal("0.50"), Decimal("10")),
        (Decimal("0.40"), Decimal("1e-9")),
        (Decimal("0.45"), Decimal("0")),
    ]
    bids = normalize_bid_levels(raw)
    assert bids == [(Decimal("0.50"), Decimal("10"))]


def test_asks_from_opposite_bids_best_ask_first():
    no_bids = [
        (Decimal("0.52"), Decimal("84")),
        (Decimal("0.34"), Decimal("30")),
        (Decimal("0.001"), Decimal("14721")),
    ]
    asks = asks_from_opposite_bids(no_bids)
    assert asks[0] == (Decimal("0.48"), Decimal("84"))
    assert asks[0][0] < asks[-1][0]
    assert yes_ask_from_no_book(no_bids) == Decimal("0.48")


def test_asks_yes_buy_matches_kalshi_complement():
    """YES buy ask = 1 - best NO bid after price sort."""
    # Intentionally unsorted / size-first
    no_raw = [
        (Decimal("0.001"), Decimal("10000")),
        (Decimal("0.53"), Decimal("5")),
        (Decimal("0.40"), Decimal("200")),
    ]
    bids = normalize_bid_levels(no_raw)
    asks = asks_from_opposite_bids(bids)
    assert asks[0][0] == Decimal("0.47")  # 1 - 0.53


def _settings():
    s = MagicMock()
    s.guards.reject_if_book_stale = False
    s.fees.maker_bps = 0
    s.fill.max_slippage_e4 = 200
    return s


def _engine():
    return PaperEngine(pool=MagicMock(), redis=MagicMock(), settings=_settings())


@pytest.mark.asyncio
async def test_market_ioc_fills_bbo_only_cancels_rest():
    """Market = IOC at top-of-book; remainder cancelled with reason ioc."""
    eng = _engine()
    order_id = uuid4()
    exp_id = uuid4()
    order = {
        "id": order_id,
        "experiment_id": exp_id,
        "ticker": "T-1",
        "side": "yes",
        "action": "buy",
        "type": "market",
        "qty": Decimal("100"),
        "filled_qty": Decimal("0"),
        "mode": "paper",
    }
    exp = {"id": exp_id, "cash": Decimal("10000")}

    # BBO ask 0.48 size 10; deeper level must not fill for market IOC
    levels = [
        (Decimal("0.48"), Decimal("10")),
        (Decimal("0.50"), Decimal("500")),
    ]

    filled_qty = Decimal("0")

    async def fake_apply(*_args, **kwargs):
        nonlocal filled_qty
        filled_qty += Decimal(str(kwargs["qty"]))
        return uuid4()

    eng.store.get_experiment = AsyncMock(return_value=exp)
    eng.store.update_order = AsyncMock(
        side_effect=lambda oid, **fields: {**order, **fields, "filled_qty": filled_qty}
    )
    eng.store.get_order = AsyncMock(
        side_effect=lambda oid: {**order, "filled_qty": filled_qty, "status": "partial"}
    )

    with (
        patch("trader.app.engine.paper.is_book_stale", AsyncMock(return_value=False)),
        patch(
            "trader.app.engine.paper.get_ask_levels_for_buy",
            AsyncMock(return_value=levels),
        ),
        patch("trader.app.engine.paper.apply_fill_tx", side_effect=fake_apply),
    ):
        result = await eng.submit_order(order, exp)

    assert filled_qty == Decimal("10")
    assert result["status"] == "cancelled"
    assert result.get("reason") == "ioc"
    eng.store.update_order.assert_any_call(order_id, status="cancelled", reason="ioc")


@pytest.mark.asyncio
async def test_limit_below_ask_rests_open():
    eng = _engine()
    order_id = uuid4()
    exp_id = uuid4()
    order = {
        "id": order_id,
        "experiment_id": exp_id,
        "ticker": "T-1",
        "side": "yes",
        "action": "buy",
        "type": "limit",
        "limit_price": Decimal("0.36"),
        "qty": Decimal("10"),
        "filled_qty": Decimal("0"),
        "mode": "paper",
    }
    exp = {"id": exp_id, "cash": Decimal("10000")}

    eng.store.update_order = AsyncMock(
        side_effect=lambda oid, **fields: {**order, **fields}
    )
    eng.store.get_order = AsyncMock(return_value={**order, "status": "open"})

    with (
        patch("trader.app.engine.paper.is_book_stale", AsyncMock(return_value=False)),
        patch(
            "trader.app.engine.paper.get_ask_levels_for_buy",
            AsyncMock(return_value=[(Decimal("0.48"), Decimal("100"))]),
        ),
        patch("trader.app.engine.paper.apply_fill_tx", AsyncMock()) as fill,
    ):
        result = await eng.submit_order(order, exp)

    assert result["status"] == "open"
    fill.assert_not_called()


@pytest.mark.asyncio
async def test_limit_cross_taker_partial_rests_remainder():
    """Marketable limit walks depth as taker; unfilled stays open."""
    eng = _engine()
    order_id = uuid4()
    exp_id = uuid4()
    order = {
        "id": order_id,
        "experiment_id": exp_id,
        "ticker": "T-1",
        "side": "yes",
        "action": "buy",
        "type": "limit",
        "limit_price": Decimal("0.50"),
        "qty": Decimal("100"),
        "filled_qty": Decimal("0"),
        "mode": "paper",
    }
    exp = {"id": exp_id, "cash": Decimal("10000")}

    levels = [
        (Decimal("0.48"), Decimal("10")),
        (Decimal("0.49"), Decimal("5")),
        (Decimal("0.55"), Decimal("1000")),  # above limit — must not fill
    ]
    filled_qty = Decimal("0")
    liquidities: list[str] = []

    async def fake_apply(*_args, **kwargs):
        nonlocal filled_qty
        filled_qty += Decimal(str(kwargs["qty"]))
        liquidities.append(kwargs.get("liquidity", "taker"))
        return uuid4()

    eng.store.get_experiment = AsyncMock(return_value=exp)
    eng.store.update_order = AsyncMock(
        side_effect=lambda oid, **fields: {
            **order,
            **fields,
            "filled_qty": filled_qty,
        }
    )
    eng.store.get_order = AsyncMock(
        side_effect=lambda oid: {
            **order,
            "filled_qty": filled_qty,
            "status": "partial" if filled_qty < order["qty"] else "filled",
        }
    )

    with (
        patch("trader.app.engine.paper.is_book_stale", AsyncMock(return_value=False)),
        patch(
            "trader.app.engine.paper.get_ask_levels_for_buy",
            AsyncMock(return_value=levels),
        ),
        patch("trader.app.engine.paper.apply_fill_tx", side_effect=fake_apply),
    ):
        result = await eng.submit_order(order, exp)

    assert filled_qty == Decimal("15")  # 10 + 5, not 0.55 level
    assert all(liq == "taker" for liq in liquidities)
    assert result["status"] == "open"
    assert Decimal(str(result["filled_qty"])) == Decimal("15")


@pytest.mark.asyncio
async def test_resting_maker_fills_at_limit_price():
    """When poll crosses, resting buy fills at limit (maker), size ≤ book."""
    eng = _engine()
    order_id = uuid4()
    exp_id = uuid4()
    order = {
        "id": order_id,
        "experiment_id": exp_id,
        "ticker": "T-1",
        "side": "yes",
        "action": "buy",
        "type": "limit",
        "limit_price": Decimal("0.40"),
        "qty": Decimal("20"),
        "filled_qty": Decimal("0"),
        "mode": "paper",
    }
    exp = {"id": exp_id, "cash": Decimal("10000")}

    # Ask has traded down through our limit
    levels = [(Decimal("0.39"), Decimal("7"))]
    applied: list[dict] = []

    async def fake_apply(*_args, **kwargs):
        applied.append(kwargs)
        return uuid4()

    eng.store.get_experiment = AsyncMock(return_value=exp)
    eng.store.get_order = AsyncMock(
        return_value={**order, "filled_qty": Decimal("7"), "status": "partial"}
    )

    with (
        patch(
            "trader.app.engine.paper.get_ask_levels_for_buy",
            AsyncMock(return_value=levels),
        ),
        patch("trader.app.engine.paper.apply_fill_tx", side_effect=fake_apply),
    ):
        ok = await eng._try_limit_fill(order, exp, Decimal("0.40"), Decimal("20"))

    assert ok is True
    assert len(applied) == 1
    assert applied[0]["price"] == Decimal("0.40")
    assert applied[0]["qty"] == Decimal("7")
    assert applied[0]["liquidity"] == "maker"
