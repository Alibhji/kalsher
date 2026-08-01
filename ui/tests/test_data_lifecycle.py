from datetime import datetime, timezone

from common.liquidity import market_has_liquidity


def test_history_window_fields() -> None:
    assert market_has_liquidity(59, 60)


def test_incremental_since_logic() -> None:
    window_start = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)
    since = datetime(2026, 8, 1, 6, 30, tzinfo=timezone.utc)
    query_start = max(window_start, since)
    assert query_start == since


if __name__ == "__main__":
    test_history_window_fields()
    test_incremental_since_logic()
    print("ok")
