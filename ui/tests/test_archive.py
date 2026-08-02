from ui.server.archive import (
    ARCHIVE_EVENT_MARKETS_QUERY,
    ARCHIVE_MARKETS_QUERY,
    _EVENT_LIQUID_SETTLED_SQL,
    _SETTLED_MARKET_SQL,
)


def test_archive_queries_require_settled_result() -> None:
    assert "settled" in _SETTLED_MARKET_SQL
    assert "'yes', 'no'" in _SETTLED_MARKET_SQL
    assert "market,result" in _SETTLED_MARKET_SQL
    assert _EVENT_LIQUID_SETTLED_SQL.strip().startswith("AND NOT EXISTS")
    assert "close_time < NOW()" not in ARCHIVE_MARKETS_QUERY
    assert _SETTLED_MARKET_SQL.strip() in ARCHIVE_MARKETS_QUERY
    assert _SETTLED_MARKET_SQL.strip() in ARCHIVE_EVENT_MARKETS_QUERY


if __name__ == "__main__":
    test_archive_queries_require_settled_result()
    print("ok")
