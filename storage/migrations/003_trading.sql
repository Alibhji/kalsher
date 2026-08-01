-- Trading schema (separate from market prints hypertable `trades`)
CREATE SCHEMA IF NOT EXISTS trading;

CREATE TABLE IF NOT EXISTS trading.experiments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT UNIQUE NOT NULL,
    mode            TEXT NOT NULL DEFAULT 'paper' CHECK (mode IN ('paper', 'live')),
    initial_capital NUMERIC(18, 4) NOT NULL,
    cash            NUMERIC(18, 4) NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    strategy        TEXT,
    params          JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS trading.orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id   UUID NOT NULL REFERENCES trading.experiments(id) ON DELETE CASCADE,
    client_order_id TEXT UNIQUE,
    ticker          TEXT NOT NULL,
    side            TEXT NOT NULL CHECK (side IN ('yes', 'no')),
    action          TEXT NOT NULL CHECK (action IN ('buy', 'sell')),
    type            TEXT NOT NULL CHECK (type IN ('market', 'limit')),
    limit_price     NUMERIC(18, 6),
    qty             NUMERIC(24, 2) NOT NULL,
    filled_qty      NUMERIC(24, 2) NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',
    mode            TEXT NOT NULL,
    kalshi_order_id TEXT,
    reason          TEXT,
    meta            JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trading.fills (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id      UUID NOT NULL REFERENCES trading.orders(id) ON DELETE CASCADE,
    experiment_id UUID NOT NULL REFERENCES trading.experiments(id) ON DELETE CASCADE,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ticker        TEXT NOT NULL,
    side          TEXT NOT NULL,
    action        TEXT NOT NULL,
    price         NUMERIC(18, 6) NOT NULL,
    qty           NUMERIC(24, 2) NOT NULL,
    fee           NUMERIC(18, 6) NOT NULL DEFAULT 0,
    liquidity     TEXT,
    meta          JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS trading.positions (
    experiment_id UUID NOT NULL REFERENCES trading.experiments(id) ON DELETE CASCADE,
    ticker        TEXT NOT NULL,
    side          TEXT NOT NULL,
    qty           NUMERIC(24, 2) NOT NULL DEFAULT 0,
    avg_price     NUMERIC(18, 6) NOT NULL DEFAULT 0,
    realized_pnl  NUMERIC(18, 6) NOT NULL DEFAULT 0,
    fees_paid     NUMERIC(18, 6) NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (experiment_id, ticker, side)
);

CREATE TABLE IF NOT EXISTS trading.round_trips (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES trading.experiments(id) ON DELETE CASCADE,
    ticker        TEXT NOT NULL,
    side          TEXT NOT NULL,
    qty           NUMERIC(24, 2) NOT NULL,
    entry_ts      TIMESTAMPTZ NOT NULL,
    entry_price   NUMERIC(18, 6) NOT NULL,
    exit_ts       TIMESTAMPTZ,
    exit_price    NUMERIC(18, 6),
    exit_kind     TEXT,
    gross_pnl     NUMERIC(18, 6),
    fees          NUMERIC(18, 6) NOT NULL DEFAULT 0,
    net_pnl       NUMERIC(18, 6),
    hold_secs     INTEGER,
    meta          JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS trading.equity_curve (
    ts             TIMESTAMPTZ NOT NULL,
    experiment_id  UUID NOT NULL,
    cash           NUMERIC(18, 4) NOT NULL,
    position_value NUMERIC(18, 4) NOT NULL,
    equity         NUMERIC(18, 4) NOT NULL,
    drawdown       NUMERIC(18, 6) NOT NULL DEFAULT 0
);

SELECT create_hypertable('trading.equity_curve', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_trading_orders_exp ON trading.orders (experiment_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trading_fills_exp ON trading.fills (experiment_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_trading_round_trips_exp ON trading.round_trips (experiment_id, entry_ts DESC);

CREATE OR REPLACE VIEW trading.experiment_stats AS
SELECT
    e.id AS experiment_id,
    e.name,
    e.mode,
    count(DISTINCT rt.id) FILTER (WHERE rt.exit_ts IS NOT NULL) AS closed_trades,
    count(DISTINCT rt.id) FILTER (WHERE rt.net_pnl > 0) AS wins,
    coalesce(sum(rt.net_pnl), 0) AS net_pnl,
    coalesce(max(ec.drawdown), 0) AS max_drawdown
FROM trading.experiments e
LEFT JOIN trading.round_trips rt ON rt.experiment_id = e.id
LEFT JOIN trading.equity_curve ec ON ec.experiment_id = e.id
GROUP BY e.id, e.name, e.mode;

CREATE OR REPLACE FUNCTION trading.reset_experiment(exp UUID) RETURNS void AS $$
BEGIN
    IF (SELECT mode FROM trading.experiments WHERE id = exp) = 'live' THEN
        RAISE EXCEPTION 'refusing to reset a live experiment';
    END IF;
    DELETE FROM trading.orders WHERE experiment_id = exp;
    DELETE FROM trading.positions WHERE experiment_id = exp;
    DELETE FROM trading.round_trips WHERE experiment_id = exp;
    DELETE FROM trading.equity_curve WHERE experiment_id = exp;
    UPDATE trading.experiments SET cash = initial_capital WHERE id = exp;
END;
$$ LANGUAGE plpgsql;
