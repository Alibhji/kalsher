from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from common.kalshi.rest import KalshiRest
from trader.app.ledger import apply_settlement_tx
from trader.app.store import TradingStore

TERMINAL_STATUSES = frozenset({"finalized", "settled", "determined", "closed"})
SETTLE_CHANNEL = "trading:settle"


def settlement_price(side: str, result: str) -> Decimal:
    side = side.lower()
    result = result.lower()
    if side == "yes":
        return Decimal("1") if result == "yes" else Decimal("0")
    return Decimal("1") if result == "no" else Decimal("0")


def parse_kalshi_positions(market_positions: list[dict[str, Any]]) -> dict[str, dict[str, Decimal]]:
    """Map ticker -> {yes: qty, no: qty} from Kalshi position_fp (signed net)."""
    out: dict[str, dict[str, Decimal]] = {}
    for row in market_positions:
        ticker = str(row.get("ticker") or row.get("market_ticker") or "")
        if not ticker:
            continue
        fp = Decimal(str(row.get("position_fp") or row.get("position") or "0"))
        if fp > 0:
            out[ticker] = {"yes": fp, "no": Decimal("0")}
        elif fp < 0:
            out[ticker] = {"yes": Decimal("0"), "no": abs(fp)}
        else:
            out[ticker] = {"yes": Decimal("0"), "no": Decimal("0")}
    return out


def _result_from_market_dict(market: dict[str, Any]) -> str | None:
    result = str(market.get("result") or "").lower().strip()
    if result in ("yes", "no"):
        return result
    return None


async def _persist_market_result(
    pool: asyncpg.Pool,
    ticker: str,
    *,
    result: str,
    status: str,
) -> None:
    """Cache a Kalshi result locally so paper settlement does not re-hit the API."""
    await pool.execute(
        """
        UPDATE markets
        SET status = $2,
            metadata = jsonb_set(
                COALESCE(metadata, '{}'::jsonb),
                '{market,result}',
                to_jsonb($3::text),
                true
            ),
            updated_at = NOW()
        WHERE ticker = $1
        """,
        ticker,
        status,
        result,
    )


def _result_from_metadata(meta: Any) -> str | None:
    if not isinstance(meta, dict):
        return None
    direct = _result_from_market_dict(meta)
    if direct:
        return direct
    nested = meta.get("market")
    if isinstance(nested, dict):
        return _result_from_market_dict(nested)
    return None


async def _result_from_lifecycle(pool: asyncpg.Pool, ticker: str) -> tuple[str | None, str | None]:
    """Read the official result from WS lifecycle events (available before REST catches up)."""
    row = await pool.fetchrow(
        """
        SELECT payload FROM lifecycle_events
        WHERE ticker = $1
          AND payload->>'event_type' IN ('determined', 'settled')
        ORDER BY ts DESC
        LIMIT 1
        """,
        ticker,
    )
    if not row:
        return None, None
    payload = row["payload"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        return None, None
    raw = payload.get("raw")
    raw_dict = raw if isinstance(raw, dict) else {}
    result = _result_from_market_dict(raw_dict) or _result_from_market_dict(payload)
    event_type = str(payload.get("event_type") or raw_dict.get("event_type") or "").lower()
    status = event_type if event_type in TERMINAL_STATUSES else "determined"
    if result:
        return result, status
    return None, None


async def resolve_market_result(
    pool: asyncpg.Pool,
    client: KalshiRest | None,
    ticker: str,
) -> tuple[str | None, str | None]:
    """Return (result, status) when the market is terminal and has a result."""
    status: str | None = None
    if client is not None:
        try:
            data = await client.get_market(ticker)
            market = data.get("market") if isinstance(data.get("market"), dict) else data
            status = str(market.get("status") or "").lower()
            result = _result_from_market_dict(market)
            if status in TERMINAL_STATUSES and result:
                await _persist_market_result(pool, ticker, result=result, status=status)
                return result, status
        except Exception:
            pass

    result, status = await _result_from_lifecycle(pool, ticker)
    if result and status:
        await _persist_market_result(pool, ticker, result=result, status=status)
        return result, status

    row = await pool.fetchrow("SELECT status, metadata FROM markets WHERE ticker = $1", ticker)
    if not row:
        return None, status
    status = str(row["status"] or "").lower()
    meta = row["metadata"]
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    result = _result_from_metadata(meta)
    if status in TERMINAL_STATUSES and result:
        return result, status
    return None, status


async def settle_position_at_market_result(
    pool: asyncpg.Pool,
    *,
    experiment_id: UUID,
    ticker: str,
    side: str,
    qty: Decimal,
    client: KalshiRest | None,
    mode: str = "paper",
) -> UUID | None:
    """Close qty contracts at the official market result. Returns order id if settled."""
    if qty <= 0:
        return None
    result, _status = await resolve_market_result(pool, client, ticker)
    if not result:
        return None
    price = settlement_price(side, result)
    return await apply_settlement_tx(
        pool,
        experiment_id=experiment_id,
        ticker=ticker,
        side=side,
        price=price,
        qty=qty,
        mode=mode,
    )


async def _market_may_be_settled(pool: asyncpg.Pool, ticker: str) -> bool:
    """Skip Kalshi lookups while a market is clearly still open."""
    row = await pool.fetchrow(
        "SELECT status, close_time FROM markets WHERE ticker = $1",
        ticker,
    )
    if not row:
        return True
    status = str(row["status"] or "").lower()
    if status in TERMINAL_STATUSES:
        return True
    close_time = row["close_time"]
    if close_time is not None:
        now = datetime.now(timezone.utc)
        ct = close_time if close_time.tzinfo else close_time.replace(tzinfo=timezone.utc)
        return ct <= now
    return False


async def settle_experiment_positions(
    pool: asyncpg.Pool,
    store: TradingStore,
    experiment_id: UUID,
    *,
    mode: str,
    client: KalshiRest | None = None,
    kalshi_map: dict[str, dict[str, Decimal]] | None = None,
) -> int:
    """Auto-close positions on expired/finalized markets. Returns settlements applied."""
    settled = 0
    positions = await store.list_positions(experiment_id)
    for pos in positions:
        qty = Decimal(str(pos["qty"]))
        if qty <= 0:
            continue
        ticker = str(pos["ticker"])
        side = str(pos["side"])

        if not await _market_may_be_settled(pool, ticker):
            continue

        if mode == "live" and kalshi_map is not None:
            kalshi_qty = kalshi_map.get(ticker, {}).get(side, Decimal("0"))
            settle_qty = qty - kalshi_qty
            if settle_qty <= 0:
                continue
        else:
            settle_qty = qty

        if await settle_position_at_market_result(
            pool,
            experiment_id=experiment_id,
            ticker=ticker,
            side=side,
            qty=settle_qty,
            client=client,
            mode=mode,
        ):
            settled += 1
    return settled


async def settle_all_active_experiments(
    pool: asyncpg.Pool,
    store: TradingStore,
    client: KalshiRest | None,
) -> int:
    """Background sweep: settle expired positions for every active experiment."""
    kalshi_map: dict[str, dict[str, Decimal]] | None = None
    if client is not None:
        try:
            kalshi_map = await fetch_kalshi_position_map(client)
        except Exception:
            kalshi_map = {}

    total = 0
    for exp in await store.list_experiments():
        if exp["status"] != "active":
            continue
        n = await settle_experiment_positions(
            pool,
            store,
            exp["id"],
            mode=str(exp["mode"]),
            client=client,
            kalshi_map=kalshi_map if exp["mode"] == "live" else None,
        )
        total += n
    return total


async def settle_ticker_all_experiments(
    pool: asyncpg.Pool,
    store: TradingStore,
    ticker: str,
    client: KalshiRest | None,
    kalshi_map: dict[str, dict[str, Decimal]] | None = None,
) -> int:
    """Settle every open position on one ticker across all active experiments."""
    settled = 0
    for exp in await store.list_experiments():
        if exp["status"] != "active":
            continue
        mode = str(exp["mode"])
        positions = await store.list_positions(exp["id"])
        for pos in positions:
            if str(pos["ticker"]) != ticker:
                continue
            qty = Decimal(str(pos["qty"]))
            if qty <= 0:
                continue
            side = str(pos["side"])
            if mode == "live" and kalshi_map is not None:
                settle_qty = qty - kalshi_map.get(ticker, {}).get(side, Decimal("0"))
            else:
                settle_qty = qty
            if settle_qty <= 0:
                continue
            if await settle_position_at_market_result(
                pool,
                experiment_id=exp["id"],
                ticker=ticker,
                side=side,
                qty=settle_qty,
                client=client,
                mode=mode,
            ):
                settled += 1
    return settled


async def fetch_kalshi_position_map(client: KalshiRest) -> dict[str, dict[str, Decimal]]:
    data = await client.get_positions()
    return parse_kalshi_positions(data.get("market_positions") or [])
