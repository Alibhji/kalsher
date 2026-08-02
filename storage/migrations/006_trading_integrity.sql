-- Idempotency + query support for the trading ledger.

-- Exchange-assigned fill id, so re-syncing an order cannot double-count fills.
ALTER TABLE trading.fills ADD COLUMN IF NOT EXISTS external_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_trading_fills_external
    ON trading.fills (external_id)
    WHERE external_id IS NOT NULL;

-- client_order_id only needs to be unique within an experiment; a global unique
-- constraint made two experiments collide and resolve to the wrong order.
ALTER TABLE trading.orders DROP CONSTRAINT IF EXISTS orders_client_order_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_trading_orders_client_oid
    ON trading.orders (experiment_id, client_order_id)
    WHERE client_order_id IS NOT NULL;

-- equity_at_or_before filters by experiment then ts; the hypertable only indexed ts.
CREATE INDEX IF NOT EXISTS idx_trading_equity_exp_ts
    ON trading.equity_curve (experiment_id, ts DESC);
