-- Snapshot liquidity at market close for archive filtering.
ALTER TABLE markets ADD COLUMN IF NOT EXISTS had_liquidity BOOLEAN;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS close_volume NUMERIC(24, 2);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS close_yes_bid_cents INT;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS close_yes_ask_cents INT;

CREATE INDEX IF NOT EXISTS idx_markets_archive_liquid
    ON markets (close_time DESC)
    WHERE close_time IS NOT NULL AND had_liquidity = TRUE;
