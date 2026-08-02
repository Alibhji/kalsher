from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from trader.app.fill_analysis import summarize_period


def test_summarize_period_empty_window():
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)
    summary = summarize_period(
        round_trips=[],
        fills=[],
        start=start,
        end=end,
        baseline=Decimal("1000"),
    )
    assert summary["realized_pnl"] == "0.0000"
    assert summary["pnl_pct"] == "0.00"
    assert summary["closed_trades"] == 0
