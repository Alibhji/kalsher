-- Read models for the ui/ terminal.
--
-- ohlcv_1s (001) aggregates last_price only, which on a 15-minute market is
-- sparse and jumpy. The odds line needs the mid, and the candlestick chart
-- needs the underlying, which had no aggregate at all.

CREATE MATERIALIZED VIEW IF NOT EXISTS market_1s
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 second', ts) AS bucket,
    ticker,
    first(last_price, ts) FILTER (WHERE last_price IS NOT NULL) AS open,
    max(last_price) AS high,
    min(last_price) AS low,
    last(last_price, ts) FILTER (WHERE last_price IS NOT NULL) AS close,
    last(yes_bid, ts) FILTER (WHERE yes_bid IS NOT NULL) AS yes_bid,
    last(yes_ask, ts) FILTER (WHERE yes_ask IS NOT NULL) AS yes_ask,
    last(volume, ts) AS volume,
    last(open_interest, ts) AS open_interest
FROM ticks
GROUP BY bucket, ticker
WITH NO DATA;

SELECT add_continuous_aggregate_policy('market_1s',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 second',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS underlying_1s
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 second', ts) AS bucket,
    source,
    symbol,
    first(price, ts) AS open,
    max(price) AS high,
    min(price) AS low,
    last(price, ts) AS close,
    count(*) AS samples
FROM underlying_prices
GROUP BY bucket, source, symbol
WITH NO DATA;

SELECT add_continuous_aggregate_policy('underlying_1s',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 second',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_underlying_symbol_ts
    ON underlying_prices (symbol, ts DESC);

-- Flattens the enriched metadata blob into the fields a market card renders.
-- Strikes are regex-guarded before casting: one malformed value from the
-- exchange would otherwise break every query against the view.
CREATE OR REPLACE VIEW v_market_card AS
SELECT
    m.ticker,
    m.event_ticker,
    m.series_ticker,
    m.title,
    m.yes_sub_title,
    m.no_sub_title,
    m.status,
    m.category,
    m.open_time,
    m.close_time,
    m.expected_expiration_time,
    CASE WHEN m.metadata #>> '{market,floor_strike}' ~ '^-?[0-9]+(\.[0-9]+)?$'
         THEN (m.metadata #>> '{market,floor_strike}')::NUMERIC END AS floor_strike,
    CASE WHEN m.metadata #>> '{market,cap_strike}' ~ '^-?[0-9]+(\.[0-9]+)?$'
         THEN (m.metadata #>> '{market,cap_strike}')::NUMERIC END AS cap_strike,
    m.metadata #>> '{market,strike_type}'   AS strike_type,
    m.metadata #>> '{market,rules_primary}' AS rules_primary,
    m.metadata #>> '{event,title}'          AS event_title,
    m.metadata #>> '{series,title}'         AS series_title
FROM markets m;
