from datetime import datetime, timedelta, timezone

from ui.server.history import _resolve_close_time


def test_resolve_close_time_prefers_actual_close() -> None:
    close = datetime(2026, 8, 1, 17, 15, tzinfo=timezone.utc)
    expected = datetime(2026, 8, 1, 17, 20, tzinfo=timezone.utc)
    assert _resolve_close_time(close, expected, None, None) == close


def test_resolve_close_time_uses_expected_when_close_null() -> None:
    expected = datetime(2026, 8, 1, 17, 20, tzinfo=timezone.utc)
    assert _resolve_close_time(None, expected, None, None) == expected


def test_resolve_close_time_falls_back_to_open_plus_three_hours() -> None:
    open_time = datetime(2026, 8, 1, 17, 0, tzinfo=timezone.utc)
    assert _resolve_close_time(None, None, None, open_time) == open_time + timedelta(hours=3)
