from decimal import Decimal

from ui.server.markets import _merge_open_interest, _merge_volume


def test_merge_volume_prefers_live_over_stale_rest_seed() -> None:
    raw = {"volume": "452114"}
    market_json = {"volume_fp": "44459.48"}
    assert _merge_volume(raw, market_json) == Decimal("452114")


def test_merge_volume_falls_back_to_rest_when_no_live_tick() -> None:
    raw: dict[str, str] = {}
    market_json = {"volume_fp": "44459.48"}
    assert _merge_volume(raw, market_json) == Decimal("44459.48")


def test_merge_open_interest_prefers_live_over_stale_rest_seed() -> None:
    raw = {"open_interest": "228564"}
    market_json = {"open_interest_fp": "30546.72"}
    assert _merge_open_interest(raw, market_json) == Decimal("228564")


if __name__ == "__main__":
    test_merge_volume_prefers_live_over_stale_rest_seed()
    test_merge_volume_falls_back_to_rest_when_no_live_tick()
    test_merge_open_interest_prefers_live_over_stale_rest_seed()
    print("ok")
