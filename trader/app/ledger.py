from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import asyncpg

from trader.app.fees import compute_fee
from trader.app.store import TradingStore


async def apply_fill(
    conn: asyncpg.Connection,
    *,
    order_id: UUID,
    experiment_id: UUID,
    ticker: str,
    side: str,
    action: str,
    price: Decimal,
    qty: Decimal,
    fee: Decimal,
    liquidity: str = "taker",
    exit_kind: str = "close",
) -> UUID:
    """Apply a fill inside an existing transaction. Returns fill id."""
    fill_id = await conn.fetchval(
        """
        INSERT INTO trading.fills
            (order_id, experiment_id, ticker, side, action, price, qty, fee, liquidity)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        order_id,
        experiment_id,
        ticker,
        side,
        action,
        price,
        qty,
        fee,
        liquidity,
    )

    notional = qty * price
    exp = await conn.fetchrow("SELECT cash FROM trading.experiments WHERE id = $1 FOR UPDATE", experiment_id)
    cash = Decimal(str(exp["cash"]))

    pos = await conn.fetchrow(
        """
        SELECT * FROM trading.positions
        WHERE experiment_id = $1 AND ticker = $2 AND side = $3
        FOR UPDATE
        """,
        experiment_id,
        ticker,
        side,
    )

    pos_qty = Decimal(str(pos["qty"])) if pos else Decimal("0")
    pos_avg = Decimal(str(pos["avg_price"])) if pos else Decimal("0")
    pos_realized = Decimal(str(pos["realized_pnl"])) if pos else Decimal("0")
    pos_fees = Decimal(str(pos["fees_paid"])) if pos else Decimal("0")

    if action == "buy":
        new_qty = pos_qty + qty
        if pos_qty > 0:
            new_avg = (pos_qty * pos_avg + qty * price) / new_qty
        else:
            new_avg = price
        cash -= notional + fee
        await _open_round_trip(conn, experiment_id, ticker, side, qty, price)
    else:
        if qty > pos_qty:
            raise ValueError(f"insufficient position: have {pos_qty}, sell {qty}")
        new_qty = pos_qty - qty
        new_avg = pos_avg if new_qty > 0 else Decimal("0")
        realized = (price - pos_avg) * qty
        pos_realized += realized
        cash += notional - fee
        await _close_round_trip(conn, experiment_id, ticker, side, qty, price, fee, exit_kind)

    pos_fees += fee

    if pos:
        await conn.execute(
            """
            UPDATE trading.positions
            SET qty = $1, avg_price = $2, realized_pnl = $3, fees_paid = $4, updated_at = NOW()
            WHERE experiment_id = $5 AND ticker = $6 AND side = $7
            """,
            new_qty,
            new_avg,
            pos_realized,
            pos_fees,
            experiment_id,
            ticker,
            side,
        )
    else:
        await conn.execute(
            """
            INSERT INTO trading.positions
                (experiment_id, ticker, side, qty, avg_price, realized_pnl, fees_paid)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            experiment_id,
            ticker,
            side,
            new_qty,
            new_avg,
            pos_realized,
            pos_fees,
        )

    await conn.execute(
        "UPDATE trading.experiments SET cash = $1 WHERE id = $2",
        cash,
        experiment_id,
    )

    order = await conn.fetchrow("SELECT filled_qty, qty FROM trading.orders WHERE id = $1", order_id)
    filled = Decimal(str(order["filled_qty"])) + qty
    total = Decimal(str(order["qty"]))
    status = "filled" if filled >= total else "partial"
    await conn.execute(
        """
        UPDATE trading.orders
        SET filled_qty = $1, status = $2, updated_at = NOW()
        WHERE id = $3
        """,
        filled,
        status,
        order_id,
    )

    return fill_id


async def _open_round_trip(
    conn: asyncpg.Connection,
    experiment_id: UUID,
    ticker: str,
    side: str,
    qty: Decimal,
    price: Decimal,
) -> None:
    await conn.execute(
        """
        INSERT INTO trading.round_trips
            (experiment_id, ticker, side, qty, entry_ts, entry_price, fees)
        VALUES ($1, $2, $3, $4, NOW(), $5, 0)
        """,
        experiment_id,
        ticker,
        side,
        qty,
        price,
    )


async def _close_round_trip(
    conn: asyncpg.Connection,
    experiment_id: UUID,
    ticker: str,
    side: str,
    qty: Decimal,
    exit_price: Decimal,
    fee: Decimal,
    exit_kind: str,
) -> None:
    remaining = qty
    rows = await conn.fetch(
        """
        SELECT id, qty, entry_price, fees
        FROM trading.round_trips
        WHERE experiment_id = $1 AND ticker = $2 AND side = $3 AND exit_ts IS NULL
        ORDER BY entry_ts
        FOR UPDATE
        """,
        experiment_id,
        ticker,
        side,
    )
    for row in rows:
        if remaining <= 0:
            break
        rt_qty = Decimal(str(row["qty"]))
        close_qty = min(remaining, rt_qty)
        entry_price = Decimal(str(row["entry_price"]))
        gross = (exit_price - entry_price) * close_qty
        rt_fees = Decimal(str(row["fees"])) + fee * (close_qty / qty)
        net = gross - rt_fees
        entry_ts = await conn.fetchval("SELECT entry_ts FROM trading.round_trips WHERE id = $1", row["id"])
        hold_secs = int((datetime.now(timezone.utc) - entry_ts).total_seconds())

        if close_qty >= rt_qty:
            await conn.execute(
                """
                UPDATE trading.round_trips
                SET exit_ts = NOW(), exit_price = $1, exit_kind = $2,
                    gross_pnl = $3, fees = $4, net_pnl = $5, hold_secs = $6
                WHERE id = $7
                """,
                exit_price,
                exit_kind,
                gross,
                rt_fees,
                net,
                hold_secs,
                row["id"],
            )
        else:
            await conn.execute(
                """
                UPDATE trading.round_trips
                SET qty = $1
                WHERE id = $2
                """,
                rt_qty - close_qty,
                row["id"],
            )
            await conn.execute(
                """
                INSERT INTO trading.round_trips
                    (experiment_id, ticker, side, qty, entry_ts, entry_price, exit_ts, exit_price,
                     exit_kind, gross_pnl, fees, net_pnl, hold_secs)
                SELECT experiment_id, ticker, side, $1, entry_ts, entry_price, NOW(), $2,
                       $3, $4, $5, $6, $7
                FROM trading.round_trips WHERE id = $8
                """,
                close_qty,
                exit_price,
                exit_kind,
                gross,
                rt_fees,
                net,
                hold_secs,
                row["id"],
            )
        remaining -= close_qty


async def apply_fill_tx(
    pool: asyncpg.Pool,
    *,
    order_id: UUID,
    experiment_id: UUID,
    ticker: str,
    side: str,
    action: str,
    price: Decimal,
    qty: Decimal,
    fee: Decimal,
    liquidity: str = "taker",
) -> UUID:
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await apply_fill(
                conn,
                order_id=order_id,
                experiment_id=experiment_id,
                ticker=ticker,
                side=side,
                action=action,
                price=price,
                qty=qty,
                fee=fee,
                liquidity=liquidity,
            )


def fee_for_fill(qty: Decimal, price: Decimal, liquidity: str, maker_bps: int) -> Decimal:
    return compute_fee(qty, price, liquidity, maker_bps)


async def apply_settlement(
    conn: asyncpg.Connection,
    *,
    experiment_id: UUID,
    ticker: str,
    side: str,
    price: Decimal,
    qty: Decimal,
) -> None:
    """Close an expired/settled position at the market result price."""
    order_id = await conn.fetchval(
        """
        INSERT INTO trading.orders
            (experiment_id, ticker, side, action, type, limit_price, qty, filled_qty, mode, status, reason)
        VALUES ($1, $2, $3, 'sell', 'market', $4, $5, 0, 'live', 'filled', 'settlement')
        RETURNING id
        """,
        experiment_id,
        ticker,
        side,
        price,
        qty,
    )
    await apply_fill(
        conn,
        order_id=order_id,
        experiment_id=experiment_id,
        ticker=ticker,
        side=side,
        action="sell",
        price=price,
        qty=qty,
        fee=Decimal("0"),
        liquidity="settlement",
        exit_kind="settlement",
    )


async def apply_settlement_tx(
    pool: asyncpg.Pool,
    *,
    experiment_id: UUID,
    ticker: str,
    side: str,
    price: Decimal,
    qty: Decimal,
) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await apply_settlement(
                conn,
                experiment_id=experiment_id,
                ticker=ticker,
                side=side,
                price=price,
                qty=qty,
            )
