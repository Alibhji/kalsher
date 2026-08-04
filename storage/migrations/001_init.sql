-- Kalshi live data schema
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS markets (
    ticker TEXT PRIMARY KEY,
    event_ticker TEXT NOT NULL,
    series_ticker TEXT,
    title TEXT,
    yes_sub_title TEXT,
    no_sub_title TEXT,
    status TEXT,
    category TEXT,
    open_time TIMESTAMPTZ,
    close_time TIMESTAMPTZ,
    expected_expiration_time TIMESTAMPTZ,
    latest_expiration_time TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ticks (
    ts TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    yes_bid NUMERIC(18, 6),
    yes_ask NUMERIC(18, 6),
    no_bid NUMERIC(18, 6),
    no_ask NUMERIC(18, 6),
    last_price NUMERIC(18, 6),
    volume NUMERIC(24, 2),
    open_interest NUMERIC(24, 2),
    payload JSONB DEFAULT '{}'::jsonb
);

SELECT create_hypertable('ticks', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS trades (
    ts TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    price NUMERIC(18, 6),
    count NUMERIC(24, 2),
    taker_side TEXT,
    trade_id TEXT,
    payload JSONB DEFAULT '{}'::jsonb
);

SELECT create_hypertable('trades', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS book_deltas (
    ts TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    price NUMERIC(18, 6),
    delta NUMERIC(24, 2),
    seq BIGINT,
    payload JSONB DEFAULT '{}'::jsonb
);

SELECT create_hypertable('book_deltas', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS underlying_prices (
    ts TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price NUMERIC(24, 8),
    payload JSONB DEFAULT '{}'::jsonb
);

SELECT create_hypertable('underlying_prices', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS lifecycle_events (
    ts TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB DEFAULT '{}'::jsonb
);

SELECT create_hypertable('lifecycle_events', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ticks_ticker_ts ON ticks (ticker, ts DESC);
CREATE INDEX IF NOT EXISTS idx_trades_ticker_ts ON trades (ticker, ts DESC);
CREATE INDEX IF NOT EXISTS idx_book_deltas_ticker_ts ON book_deltas (ticker, ts DESC);

ALTER TABLE ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker',
    timescaledb.compress_orderby = 'ts DESC'
);
ALTER TABLE trades SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker',
    timescaledb.compress_orderby = 'ts DESC'
);
ALTER TABLE book_deltas SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker',
    timescaledb.compress_orderby = 'ts DESC'
);

SELECT add_compression_policy('ticks', INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_compression_policy('trades', INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_compression_policy('book_deltas', INTERVAL '1 day', if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_1s
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 second', ts) AS bucket,
    ticker,
    first(last_price, ts) FILTER (WHERE last_price IS NOT NULL) AS open,
    max(last_price) AS high,
    min(last_price) AS low,
    last(last_price, ts) FILTER (WHERE last_price IS NOT NULL) AS close,
    last(volume, ts) AS volume
FROM ticks
GROUP BY bucket, ticker
WITH NO DATA;

-- remove+add: if_not_exists does not skip when an existing policy uses different offsets
SELECT remove_continuous_aggregate_policy('ohlcv_1s', if_exists => TRUE);
SELECT add_continuous_aggregate_policy('ohlcv_1s',
    start_offset => INTERVAL '15 minutes',
    end_offset => INTERVAL '1 second',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE);
