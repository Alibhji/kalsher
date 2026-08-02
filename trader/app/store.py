from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _str(d: Decimal | float | int | None) -> str | None:
    if d is None:
        return None
    return str(d)


class TradingStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def create_experiment(
        self,
        name: str,
        mode: str,
        initial_capital: Decimal,
        strategy: str | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        row = await self.pool.fetchrow(
            """
            INSERT INTO trading.experiments (name, mode, initial_capital, cash, strategy, params)
            VALUES ($1, $2, $3, $3, $4, $5::jsonb)
            RETURNING *
            """,
            name,
            mode,
            initial_capital,
            strategy,
            json.dumps(params or {}),
        )
        return dict(row)

    async def list_experiments(
        self, include_archived: bool = False, tag: str | None = None
    ) -> list[dict[str, Any]]:
        if include_archived:
            rows = await self.pool.fetch("SELECT * FROM trading.experiments ORDER BY created_at DESC")
        else:
            rows = await self.pool.fetch(
                "SELECT * FROM trading.experiments WHERE archived_at IS NULL ORDER BY created_at DESC"
            )
        out = [dict(r) for r in rows]
        if tag:
            from trader.app.tags import tags_from_params

            needle = tag.strip().lower()
            filtered: list[dict[str, Any]] = []
            for row in out:
                params = row.get("params")
                if isinstance(params, str):
                    try:
                        params = json.loads(params)
                    except json.JSONDecodeError:
                        params = {}
                if needle in tags_from_params(params if isinstance(params, dict) else {}):
                    filtered.append(row)
            out = filtered
        return out

    async def delete_experiment(self, exp_id: UUID) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM trading.equity_curve WHERE experiment_id = $1",
                    exp_id,
                )
                result = await conn.execute(
                    "DELETE FROM trading.experiments WHERE id = $1",
                    exp_id,
                )
        return result.endswith("1")

    async def get_experiment(self, exp_id: UUID) -> dict[str, Any] | None:
        row = await self.pool.fetchrow("SELECT * FROM trading.experiments WHERE id = $1", exp_id)
        return dict(row) if row else None

    async def patch_experiment(self, exp_id: UUID, **fields: Any) -> dict[str, Any] | None:
        sets: list[str] = []
        vals: list[Any] = []
        idx = 1
        for k, v in fields.items():
            if v is None:
                continue
            if k == "params":
                sets.append(f"params = ${idx}::jsonb")
                vals.append(json.dumps(v))
            else:
                sets.append(f"{k} = ${idx}")
                vals.append(v)
            idx += 1
        if not sets:
            return await self.get_experiment(exp_id)
        vals.append(exp_id)
        row = await self.pool.fetchrow(
            f"UPDATE trading.experiments SET {', '.join(sets)} WHERE id = ${idx} RETURNING *",
            *vals,
        )
        return dict(row) if row else None

    async def archive_experiment(self, exp_id: UUID) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            "UPDATE trading.experiments SET archived_at = NOW(), status = 'archived' WHERE id = $1 RETURNING *",
            exp_id,
        )
        return dict(row) if row else None

    async def reset_experiment(self, exp_id: UUID) -> None:
        await self.pool.execute("SELECT trading.reset_experiment($1)", exp_id)

    async def adjust_capital(self, exp_id: UUID, new_cash: Decimal) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            "UPDATE trading.experiments SET cash = $1 WHERE id = $2 RETURNING *",
            new_cash,
            exp_id,
        )
        return dict(row) if row else None

    async def set_live_baseline(
        self, exp_id: UUID, cash: Decimal, initial_capital: Decimal | None = None
    ) -> dict[str, Any] | None:
        if initial_capital is not None:
            row = await self.pool.fetchrow(
                """
                UPDATE trading.experiments
                SET cash = $1, initial_capital = $2
                WHERE id = $3
                RETURNING *
                """,
                cash,
                initial_capital,
                exp_id,
            )
        else:
            row = await self.pool.fetchrow(
                "UPDATE trading.experiments SET cash = $1 WHERE id = $2 RETURNING *",
                cash,
                exp_id,
            )
        return dict(row) if row else None

    async def get_order_by_client_id(
        self, client_order_id: str, experiment_id: UUID | None = None
    ) -> dict[str, Any] | None:
        if experiment_id is not None:
            row = await self.pool.fetchrow(
                "SELECT * FROM trading.orders WHERE experiment_id = $1 AND client_order_id = $2",
                experiment_id,
                client_order_id,
            )
        else:
            row = await self.pool.fetchrow(
                "SELECT * FROM trading.orders WHERE client_order_id = $1",
                client_order_id,
            )
        return dict(row) if row else None

    async def get_order(self, order_id: UUID) -> dict[str, Any] | None:
        row = await self.pool.fetchrow("SELECT * FROM trading.orders WHERE id = $1", order_id)
        return dict(row) if row else None

    async def create_order(
        self,
        experiment_id: UUID,
        ticker: str,
        side: str,
        action: str,
        order_type: str,
        qty: Decimal,
        mode: str,
        limit_price: Decimal | None = None,
        client_order_id: str | None = None,
        status: str = "pending",
    ) -> dict[str, Any]:
        row = await self.pool.fetchrow(
            """
            INSERT INTO trading.orders
                (experiment_id, ticker, side, action, type, limit_price, qty, mode, client_order_id, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
            """,
            experiment_id,
            ticker,
            side,
            action,
            order_type,
            limit_price,
            qty,
            mode,
            client_order_id,
            status,
        )
        return dict(row)

    async def update_order(self, order_id: UUID, **fields: Any) -> dict[str, Any] | None:
        sets = ["updated_at = NOW()"]
        vals: list[Any] = []
        idx = 1
        for k, v in fields.items():
            sets.append(f"{k} = ${idx}")
            vals.append(v)
            idx += 1
        vals.append(order_id)
        row = await self.pool.fetchrow(
            f"UPDATE trading.orders SET {', '.join(sets)} WHERE id = ${idx} RETURNING *",
            *vals,
        )
        return dict(row) if row else None

    async def list_orders(
        self,
        experiment_id: UUID,
        status: str | None = None,
        ticker: str | None = None,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["experiment_id = $1"]
        vals: list[Any] = [experiment_id]
        idx = 2
        if status:
            clauses.append(f"status = ${idx}")
            vals.append(status)
            idx += 1
        if ticker:
            clauses.append(f"ticker = ${idx}")
            vals.append(ticker)
            idx += 1
        if since:
            clauses.append(f"created_at >= ${idx}")
            vals.append(since)
        rows = await self.pool.fetch(
            f"SELECT * FROM trading.orders WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
            *vals,
        )
        return [dict(r) for r in rows]

    async def list_open_orders(self, experiment_id: UUID | None = None) -> list[dict[str, Any]]:
        if experiment_id:
            rows = await self.pool.fetch(
                "SELECT * FROM trading.orders WHERE experiment_id = $1 AND status IN ('open', 'pending', 'partial') ORDER BY created_at",
                experiment_id,
            )
        else:
            rows = await self.pool.fetch(
                "SELECT * FROM trading.orders WHERE status IN ('open', 'pending', 'partial') ORDER BY created_at"
            )
        return [dict(r) for r in rows]

    async def get_position(
        self, experiment_id: UUID, ticker: str, side: str
    ) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM trading.positions WHERE experiment_id = $1 AND ticker = $2 AND side = $3",
            experiment_id,
            ticker,
            side,
        )
        return dict(row) if row else None

    async def list_positions(self, experiment_id: UUID) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            "SELECT * FROM trading.positions WHERE experiment_id = $1 AND qty > 0 ORDER BY ticker, side",
            experiment_id,
        )
        return [dict(r) for r in rows]

    async def list_fills(
        self,
        experiment_id: UUID,
        ticker: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses = ["experiment_id = $1"]
        vals: list[Any] = [experiment_id]
        idx = 2
        if ticker:
            clauses.append(f"ticker = ${idx}")
            vals.append(ticker)
            idx += 1
        if since:
            clauses.append(f"ts >= ${idx}")
            vals.append(since)
            idx += 1
        if until:
            clauses.append(f"ts <= ${idx}")
            vals.append(until)
            idx += 1
        vals.append(limit)
        rows = await self.pool.fetch(
            f"""
            SELECT * FROM trading.fills
            WHERE {' AND '.join(clauses)}
            ORDER BY ts DESC LIMIT ${idx}
            """,
            *vals,
        )
        return [dict(r) for r in rows]

    async def list_round_trips(
        self,
        experiment_id: UUID,
        ticker: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        event_ticker: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["experiment_id = $1"]
        vals: list[Any] = [experiment_id]
        idx = 2
        if ticker:
            clauses.append(f"ticker = ${idx}")
            vals.append(ticker)
            idx += 1
        if event_ticker:
            clauses.append(
                f"ticker IN (SELECT m.ticker FROM markets m WHERE m.event_ticker = ${idx})"
            )
            vals.append(event_ticker)
            idx += 1
        if since:
            clauses.append(f"COALESCE(exit_ts, entry_ts) >= ${idx}")
            vals.append(since)
            idx += 1
        if until:
            clauses.append(f"COALESCE(exit_ts, entry_ts) <= ${idx}")
            vals.append(until)
            idx += 1
        rows = await self.pool.fetch(
            f"SELECT * FROM trading.round_trips WHERE {' AND '.join(clauses)} ORDER BY entry_ts DESC",
            *vals,
        )
        return [dict(r) for r in rows]

    async def list_tickers_for_event(self, event_ticker: str) -> list[str]:
        rows = await self.pool.fetch(
            "SELECT ticker FROM markets WHERE event_ticker = $1",
            event_ticker,
        )
        return [str(r["ticker"]) for r in rows]

    async def event_ticker_map(self, tickers: list[str]) -> dict[str, str]:
        """Map market ticker → event_ticker for the given tickers."""
        if not tickers:
            return {}
        rows = await self.pool.fetch(
            "SELECT ticker, event_ticker FROM markets WHERE ticker = ANY($1::text[])",
            tickers,
        )
        return {str(r["ticker"]): str(r["event_ticker"]) for r in rows if r.get("event_ticker")}

    async def list_archive_pnl_for_experiment(self, experiment_id: UUID) -> list[dict[str, Any]]:
        """Per-event closed P/L for archive list (markets.event_ticker join)."""
        rows = await self.pool.fetch(
            """
            SELECT
                m.event_ticker,
                COUNT(*)::INT AS trip_count,
                COUNT(*) FILTER (WHERE rt.exit_ts IS NOT NULL)::INT AS trade_count,
                COALESCE(SUM(rt.net_pnl) FILTER (WHERE rt.exit_ts IS NOT NULL), 0) AS net_pnl
            FROM trading.round_trips rt
            JOIN markets m ON m.ticker = rt.ticker
            WHERE rt.experiment_id = $1
            GROUP BY m.event_ticker
            ORDER BY MAX(COALESCE(rt.exit_ts, rt.entry_ts)) DESC NULLS LAST
            """,
            experiment_id,
        )
        return [dict(r) for r in rows]

    async def list_experiments_for_event(self, event_ticker: str) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            WITH event_tickers AS (
                SELECT ticker FROM markets WHERE event_ticker = $1
            ),
            exp_ids AS (
                SELECT DISTINCT f.experiment_id
                FROM trading.fills f
                WHERE f.ticker IN (SELECT ticker FROM event_tickers)
            )
            SELECT
                e.id,
                e.name,
                e.mode,
                e.status,
                e.created_at,
                e.archived_at,
                (
                    SELECT COUNT(*)::INT FROM trading.fills f
                    WHERE f.experiment_id = e.id
                      AND f.ticker IN (SELECT ticker FROM event_tickers)
                ) AS fill_count,
                (
                    SELECT COUNT(*)::INT FROM trading.round_trips rt
                    WHERE rt.experiment_id = e.id
                      AND rt.ticker IN (SELECT ticker FROM event_tickers)
                      AND rt.exit_ts IS NOT NULL
                ) AS trade_count,
                (
                    SELECT COALESCE(SUM(rt.net_pnl), 0)
                    FROM trading.round_trips rt
                    WHERE rt.experiment_id = e.id
                      AND rt.ticker IN (SELECT ticker FROM event_tickers)
                      AND rt.exit_ts IS NOT NULL
                ) AS net_pnl,
                (
                    SELECT MAX(f.ts) FROM trading.fills f
                    WHERE f.experiment_id = e.id
                      AND f.ticker IN (SELECT ticker FROM event_tickers)
                ) AS last_activity
            FROM trading.experiments e
            WHERE e.id IN (SELECT experiment_id FROM exp_ids)
            ORDER BY last_activity DESC NULLS LAST
            """,
            event_ticker,
        )
        return [dict(r) for r in rows]

    async def list_open_round_trips(
        self, experiment_id: UUID, ticker: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["experiment_id = $1", "exit_ts IS NULL"]
        vals: list[Any] = [experiment_id]
        if ticker:
            clauses.append("ticker = $2")
            vals.append(ticker)
        rows = await self.pool.fetch(
            f"SELECT * FROM trading.round_trips WHERE {' AND '.join(clauses)} ORDER BY entry_ts",
            *vals,
        )
        return [dict(r) for r in rows]

    async def get_equity_curve(
        self,
        experiment_id: UUID,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        clauses = ["experiment_id = $1"]
        vals: list[Any] = [experiment_id]
        idx = 2
        if since:
            clauses.append(f"ts >= ${idx}")
            vals.append(since)
            idx += 1
        if until:
            clauses.append(f"ts <= ${idx}")
            vals.append(until)
            idx += 1
        vals.append(limit)
        rows = await self.pool.fetch(
            f"""
            SELECT * FROM trading.equity_curve
            WHERE {' AND '.join(clauses)}
            ORDER BY ts ASC LIMIT ${idx}
            """,
            *vals,
        )
        return [dict(r) for r in rows]

    async def equity_at_or_before(
        self, experiment_id: UUID, at: datetime
    ) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            """
            SELECT * FROM trading.equity_curve
            WHERE experiment_id = $1 AND ts <= $2
            ORDER BY ts DESC LIMIT 1
            """,
            experiment_id,
            at,
        )
        return dict(row) if row else None

    async def get_stats(self, experiment_id: UUID) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM trading.experiment_stats WHERE experiment_id = $1",
            experiment_id,
        )
        return dict(row) if row else None

    async def append_equity_point(
        self,
        experiment_id: UUID,
        cash: Decimal,
        position_value: Decimal,
        equity: Decimal,
        drawdown: Decimal,
    ) -> None:
        await self.pool.execute(
            """
            INSERT INTO trading.equity_curve (ts, experiment_id, cash, position_value, equity, drawdown)
            VALUES (NOW(), $1, $2, $3, $4, $5)
            """,
            experiment_id,
            cash,
            position_value,
            equity,
            drawdown,
        )

    async def sum_fees_paid(self, experiment_id: UUID) -> Decimal:
        val = await self.pool.fetchval(
            "SELECT COALESCE(SUM(fee), 0) FROM trading.fills WHERE experiment_id = $1",
            experiment_id,
        )
        return Decimal(str(val))

    async def sum_realized_from_positions(self, experiment_id: UUID) -> Decimal:
        val = await self.pool.fetchval(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM trading.positions WHERE experiment_id = $1",
            experiment_id,
        )
        return Decimal(str(val))
