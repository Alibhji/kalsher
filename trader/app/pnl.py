from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis

from trader.app.book import get_quotes_many, mid_price
from trader.app.live_account import fetch_kalshi_account
from trader.app.store import TradingStore


def cost_basis(qty: Decimal, entry_price: Decimal) -> Decimal:
    return qty * entry_price


def pnl_pct(net_pnl: Decimal | None, basis: Decimal) -> Decimal | None:
    if net_pnl is None or basis <= 0:
        return None
    return (net_pnl / basis) * Decimal("100")


def action_at_entry(side: str) -> str:
    return f"buy {side}"


def enrich_round_trip(rt: dict, unrealized: Decimal | None = None) -> dict:
    qty = Decimal(str(rt["qty"]))
    entry_price = Decimal(str(rt["entry_price"]))
    basis = cost_basis(qty, entry_price)
    net = rt.get("net_pnl")
    net_d = Decimal(str(net)) if net is not None else None
    pct = pnl_pct(net_d, basis)
    if net_d is None and unrealized is not None:
        pct = pnl_pct(unrealized, basis)
    return {
        **rt,
        "cost_basis": str(basis.quantize(Decimal("0.0001"))),
        "pnl_pct": str(pct.quantize(Decimal("0.01"))) if pct is not None else None,
        "action_at_entry": action_at_entry(rt["side"]),
    }


async def build_profile(
    store: TradingStore,
    redis: aioredis.Redis,
    exp_id: UUID,
    *,
    settings=None,
    kalshi_client=None,
    live_trading_enabled: bool = False,
) -> dict:
    exp = await store.get_experiment(exp_id)
    if not exp:
        raise KeyError("experiment not found")

    kalshi_acct = None
    if exp["mode"] == "live" and settings is not None:
        try:
            kalshi_acct = await fetch_kalshi_account(settings, kalshi_client)
            await store.set_live_baseline(exp_id, kalshi_acct["available_funds"])
            cash = kalshi_acct["available_funds"]
        except Exception:
            cash = Decimal(str(exp["cash"]))
    else:
        cash = Decimal(str(exp["cash"]))

    positions = await store.list_positions(exp_id)
    realized = await store.sum_realized_from_positions(exp_id)
    fees = await store.sum_fees_paid(exp_id)

    pos_out = []
    unrealized_total = Decimal("0")
    position_value = Decimal("0")

    quote_map = await get_quotes_many(redis, [p["ticker"] for p in positions])

    for p in positions:
        qty = Decimal(str(p["qty"]))
        avg = Decimal(str(p["avg_price"]))
        mark = mid_price(quote_map.get(p["ticker"], {}), p["side"])
        basis = cost_basis(qty, avg)
        unreal = Decimal("0")
        if mark is not None:
            unreal = (mark - avg) * qty
            position_value += mark * qty
        unrealized_total += unreal
        pos_out.append(
            {
                "ticker": p["ticker"],
                "side": p["side"],
                "qty": str(qty),
                "avg_price": str(avg),
                "realized_pnl": str(p["realized_pnl"]),
                "fees_paid": str(p["fees_paid"]),
                "cost_basis": str(basis.quantize(Decimal("0.0001"))),
                "mark_price": str(mark) if mark is not None else None,
                "unrealized_pnl": str(unreal.quantize(Decimal("0.0001"))),
            }
        )

    initial = Decimal(str(exp["initial_capital"]))
    capital_invested = initial
    if kalshi_acct is not None:
        position_value = kalshi_acct["portfolio_value"]
        equity = kalshi_acct["equity"]
        if kalshi_client is not None:
            try:
                from trader.app.capital import cumulative_capital, fetch_all_kalshi_deposits

                dep_rows = await fetch_all_kalshi_deposits(kalshi_client)
                if dep_rows:
                    capital_invested = cumulative_capital(dep_rows)
            except Exception:
                pass
        total_pnl = equity - capital_invested
        pct = pnl_pct(total_pnl, capital_invested)
        extra = {
            "available_funds": str(kalshi_acct["available_funds"].quantize(Decimal("0.0001"))),
            "portfolio_value": str(position_value.quantize(Decimal("0.0001"))),
            "total_pnl": str(total_pnl.quantize(Decimal("0.0001"))),
            "pnl_pct": str(pct.quantize(Decimal("0.01"))) if pct is not None else "0",
            "capital_invested": str(capital_invested.quantize(Decimal("0.0001"))),
        }
    else:
        equity = cash + position_value
        extra = {}

    curve = await store.get_equity_curve(exp_id, limit=1)
    drawdown = Decimal(str(curve[0]["drawdown"])) if curve else Decimal("0")

    return {
        "experiment_id": exp_id,
        "name": exp["name"],
        "mode": exp["mode"],
        "cash": str(cash.quantize(Decimal("0.0001"))),
        "initial_capital": str(initial),
        "realized_pnl": str(realized.quantize(Decimal("0.0001"))),
        "unrealized_pnl": str(unrealized_total.quantize(Decimal("0.0001"))),
        "fees_paid": str(fees.quantize(Decimal("0.0001"))),
        "equity": str(equity.quantize(Decimal("0.0001"))),
        "drawdown": str(drawdown.quantize(Decimal("0.0001"))),
        "positions": pos_out,
        "live_trading_enabled": live_trading_enabled,
        **extra,
    }


async def mark_equity_loop(
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    interval: float,
    running: callable,
) -> None:
    store = TradingStore(pool)
    peak_by_exp: dict[str, Decimal] = {}
    import asyncio

    while running():
        try:
            exps = await store.list_experiments()
            for exp in exps:
                if exp["status"] != "active":
                    continue
                profile = await build_profile(store, redis, exp["id"])
                exp_id = str(exp["id"])
                equity = Decimal(profile["equity"])
                peak = peak_by_exp.get(exp_id, equity)
                if equity > peak:
                    peak = equity
                peak_by_exp[exp_id] = peak
                dd = equity - peak
                await store.append_equity_point(
                    exp["id"],
                    Decimal(profile["cash"]),
                    Decimal(profile["equity"]) - Decimal(profile["cash"]),
                    equity,
                    dd,
                )
        except Exception:
            pass
        await asyncio.sleep(interval)


def parse_equity_range(range_str: str | None) -> datetime | None:
    if not range_str:
        return None
    now = datetime.now(timezone.utc)
    mapping = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
    delta = mapping.get(range_str)
    return now - delta if delta else None


def parse_datetime_param(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
