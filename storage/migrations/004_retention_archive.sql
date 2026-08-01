-- Archive indexes + raw-data retention (keeps markets dimension + aggregates longer).

CREATE INDEX IF NOT EXISTS idx_markets_close_time
    ON markets (close_time DESC)
    WHERE close_time IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_markets_series_close
    ON markets (series_ticker, close_time DESC)
    WHERE close_time IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_markets_event_ticker
    ON markets (event_ticker);

-- Drop heavy raw book deltas after 7 days; charts use ticks/market_1s.
SELECT add_retention_policy('book_deltas', INTERVAL '7 days', if_not_exists => TRUE);

-- Keep tick/trade prints for 30 days (enough for archive chart replay).
SELECT add_retention_policy('ticks', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('trades', INTERVAL '30 days', if_not_exists => TRUE);

-- Underlying index stream — 14 days.
SELECT add_retention_policy('underlying_prices', INTERVAL '14 days', if_not_exists => TRUE);

-- Lifecycle audit trail — 90 days.
SELECT add_retention_policy('lifecycle_events', INTERVAL '90 days', if_not_exists => TRUE);
