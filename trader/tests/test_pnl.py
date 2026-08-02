from __future__ import annotations

from decimal import Decimal

from trader.app.fees import kalshi_taker_fee
from trader.app.pnl import cost_basis, pnl_pct


def test_kalshi_fee_positive():
    fee = kalshi_taker_fee(Decimal("10"), Decimal("0.50"))
    assert fee > 0


def test_pnl_pct():
    basis = cost_basis(Decimal("10"), Decimal("0.50"))
    assert basis == Decimal("5.0")
    pct = pnl_pct(Decimal("0.76"), basis)
    assert pct is not None
    assert abs(float(pct) - 15.2) < 0.1
