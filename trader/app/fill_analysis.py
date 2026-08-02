from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from common.kalshi.rest import KalshiRest

from trader.app.capital import cumulative_capital, deposits_in_period
from trader.app.settlement import TERMINAL_STATUSES, settlement_price


def _parse_kalshi_ts(raw: dict[str, Any]) -> datetime:
    created = raw.get("created_time")
    if created:
        return datetime.fromisoformat(str(created).replace("Z", "+00:00"))
    ts = raw.get("ts")
    if ts is not None:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return datetime.now(timezone.utc)


def normalize_kalshi_fill(raw: dict[str, Any], *, source: str) -> dict[str, Any]:
    side = str(raw.get("side") or raw.get("outcome_side") or "yes").lower()
    action = str(raw.get("action") or "buy").lower()
    qty = Decimal(str(raw.get("count_fp") or raw.get("count") or 0))
    if side == "yes":
        price = Decimal(str(raw.get("yes_price_dollars") or raw.get("price") or 0))
    else:
        price = Decimal(str(raw.get("no_price_dollars") or raw.get("price") or 0))
    fee = Decimal(str(raw.get("fee_cost") or 0))
    ts = _parse_kalshi_ts(raw)
    ticker = str(raw.get("market_ticker") or raw.get("ticker") or "")
    cost = qty * price
    if action == "buy":
        cash_delta = -(cost + fee)
    else:
        cash_delta = cost - fee
    return {
        "id": str(raw.get("fill_id") or raw.get("trade_id") or ""),
        "ts": ts,
        "ticker": ticker,
        "side": side,
        "action": action,
        "price": price,
        "qty": qty,
        "fee": fee,
        "cost": str(cost.quantize(Decimal("0.0001"))),
        "cash_delta": cash_delta,
        "source": source,
        "order_id": raw.get("order_id"),
    }


async def _paginate_kalshi_fills(
    client: KalshiRest,
    path: str,
    *,
    min_ts: int | None = None,
    max_ts: int | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": 1000}
    if min_ts is not None:
        params["min_ts"] = min_ts
    if max_ts is not None:
        params["max_ts"] = max_ts
    out: list[dict[str, Any]] = []
    while True:
        data = await client.get(path, params)
        out.extend(data.get("fills") or [])
        cursor = data.get("cursor")
        if not cursor:
            break
        params["cursor"] = cursor
    return out


async def fetch_all_kalshi_fills(
    client: KalshiRest,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    min_ts = int(start.timestamp()) if start else None
    max_ts = int(end.timestamp()) if end else None
    live = await _paginate_kalshi_fills(client, "/portfolio/fills", min_ts=min_ts, max_ts=max_ts)
    historical: list[dict[str, Any]] = []
    try:
        historical = await _paginate_kalshi_fills(
            client, "/historical/fills", min_ts=min_ts, max_ts=max_ts
        )
    except Exception:
        pass
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for source, rows in (("kalshi_live", live), ("kalshi_historical", historical)):
        for raw in rows:
            fid = str(raw.get("fill_id") or raw.get("trade_id") or "")
            if fid and fid in seen:
                continue
            if fid:
                seen.add(fid)
            merged.append(normalize_kalshi_fill(raw, source=source))
    merged.sort(key=lambda r: r["ts"])
    if start or end:
        merged = [r for r in merged if _in_range(r["ts"], start, end)]
    return merged


def _in_range(ts: datetime, start: datetime | None, end: datetime | None) -> bool:
    if start and ts < start:
        return False
    if end and ts > end:
        return False
    return True


def normalize_local_fill(row: dict[str, Any]) -> dict[str, Any]:
    qty = Decimal(str(row["qty"]))
    price = Decimal(str(row["price"]))
    fee = Decimal(str(row["fee"]))
    action = str(row["action"]).lower()
    cost = qty * price
    cash_delta = -(cost + fee) if action == "buy" else cost - fee
    ts = row["ts"]
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return {
        "id": str(row["id"]),
        "ts": ts,
        "ticker": row["ticker"],
        "side": str(row["side"]).lower(),
        "action": action,
        "price": price,
        "qty": qty,
        "fee": fee,
        "cost": str(cost.quantize(Decimal("0.0001"))),
        "cash_delta": cash_delta,
        "source": "local",
        "order_id": row.get("order_id"),
    }


def _fifo_simulate(fills: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    """FIFO round-trip simulation. Returns closed trips and remaining open lots."""
    open_lots: dict[tuple[str, str], list[dict[str, Any]]] = {}
    closed: list[dict[str, Any]] = []

    for fill in sorted(fills, key=lambda f: f["ts"]):
        key = (fill["ticker"], fill["side"])
        if fill["action"] == "buy":
            open_lots.setdefault(key, []).append(
                {
                    "qty": fill["qty"],
                    "entry_price": fill["price"],
                    "entry_ts": fill["ts"],
                    "entry_fee": fill["fee"],
                    "fill_id": fill.get("id"),
                }
            )
            continue

        remaining = fill["qty"]
        lots = open_lots.get(key, [])
        exit_fee = fill["fee"]
        exit_qty_total = fill["qty"]
        while remaining > 0 and lots:
            lot = lots[0]
            lot_qty = lot["qty"]
            close_qty = min(remaining, lot_qty)
            entry_price = lot["entry_price"]
            exit_price = fill["price"]
            gross = (exit_price - entry_price) * close_qty
            fee_share = lot["entry_fee"] * (close_qty / lot_qty) + exit_fee * (
                close_qty / exit_qty_total if exit_qty_total > 0 else Decimal("0")
            )
            net = gross - fee_share
            basis = entry_price * close_qty
            pct = (net / basis * Decimal("100")) if basis > 0 else None
            closed.append(
                {
                    "ticker": fill["ticker"],
                    "side": fill["side"],
                    "qty": close_qty,
                    "entry_ts": lot["entry_ts"],
                    "entry_price": entry_price,
                    "exit_ts": fill["ts"],
                    "exit_price": exit_price,
                    "gross_pnl": gross,
                    "fees": fee_share,
                    "net_pnl": net,
                    "pnl_pct": pct,
                    "exit_kind": "close",
                    "entry_fill_id": lot.get("fill_id"),
                }
            )
            remaining -= close_qty
            if close_qty >= lot_qty:
                lots.pop(0)
            else:
                lot["qty"] = lot_qty - close_qty
                lot["entry_fee"] = lot["entry_fee"] * (Decimal("1") - close_qty / lot_qty)
        open_lots[key] = lots

    return closed, open_lots


def simulate_round_trips(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """FIFO round-trip simulation from chronological fills."""
    closed, _ = _fifo_simulate(fills)
    return closed


def _parse_market_ts(raw: Any) -> datetime | None:
    if raw in (None, ""):
        return None
    text = str(raw)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _synthetic_settlement_closes(
    client: KalshiRest,
    open_lots: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    """Close remaining open lots at $1/$0 when Kalshi market is finalized."""
    end_ts = end or datetime.now(timezone.utc)
    closed: list[dict[str, Any]] = []
    cache: dict[str, tuple[str | None, datetime | None]] = {}

    for (ticker, side), lots in open_lots.items():
        if not lots:
            continue
        if ticker not in cache:
            result: str | None = None
            exit_ts: datetime | None = None
            try:
                data = await client.get_market(ticker)
                market = data.get("market") if isinstance(data.get("market"), dict) else data
                status = str(market.get("status") or "").lower()
                if status in TERMINAL_STATUSES:
                    result = str(market.get("result") or "").lower()
                    if result not in ("yes", "no"):
                        result = None
                    exit_ts = (
                        _parse_market_ts(market.get("close_time"))
                        or _parse_market_ts(market.get("expected_expiration_time"))
                        or _parse_market_ts(market.get("latest_expiration_time"))
                    )
            except Exception:
                pass
            cache[ticker] = (result, exit_ts)

        result, market_exit_ts = cache[ticker]
        if not result:
            continue
        exit_ts = market_exit_ts or end_ts
        if exit_ts > end_ts:
            continue
        exit_price = settlement_price(side, result)

        for lot in lots:
            close_qty = Decimal(str(lot["qty"]))
            entry_price = Decimal(str(lot["entry_price"]))
            entry_fee = Decimal(str(lot["entry_fee"]))
            gross = (exit_price - entry_price) * close_qty
            net = gross - entry_fee
            basis = entry_price * close_qty
            pct = (net / basis * Decimal("100")) if basis > 0 else None
            closed.append(
                {
                    "ticker": ticker,
                    "side": side,
                    "qty": close_qty,
                    "entry_ts": lot["entry_ts"],
                    "entry_price": entry_price,
                    "exit_ts": exit_ts,
                    "exit_price": exit_price,
                    "gross_pnl": gross,
                    "fees": entry_fee,
                    "net_pnl": net,
                    "pnl_pct": pct,
                    "exit_kind": "settlement",
                    "entry_fill_id": lot.get("fill_id"),
                }
            )

    return closed


async def simulate_round_trips_with_settlements(
    client: KalshiRest,
    fills: list[dict[str, Any]],
    *,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    closed, open_lots = _fifo_simulate(fills)
    settled = await _synthetic_settlement_closes(client, open_lots, end=end)
    return closed + settled


async def annotate_fills_pnl_with_settlements(
    client: KalshiRest,
    fills: list[dict[str, Any]],
    *,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    """Attach realized P&L to fills, including synthetic settlement on expired markets."""
    closed, open_lots = _fifo_simulate(fills)
    settled = await _synthetic_settlement_closes(client, open_lots, end=end)
    pnl_by_entry: dict[str, tuple[Decimal, Decimal]] = {}
    for rt in closed + settled:
        fill_id = rt.get("entry_fill_id")
        if not fill_id:
            continue
        net = Decimal(str(rt["net_pnl"]))
        basis = Decimal(str(rt["entry_price"])) * Decimal(str(rt["qty"]))
        prev_net, prev_basis = pnl_by_entry.get(str(fill_id), (Decimal("0"), Decimal("0")))
        pnl_by_entry[str(fill_id)] = (prev_net + net, prev_basis + basis)

    out = annotate_fills_pnl(fills)
    for row in out:
        key = str(row.get("id") or "")
        if key in pnl_by_entry:
            net, basis = pnl_by_entry[key]
            row["trade_pnl"] = net
            row["trade_pnl_pct"] = (net / basis * Decimal("100")) if basis > 0 else None
    return out


def annotate_fills_pnl(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach signed cash flow and realized P&L (on closing sells) to each fill."""
    open_lots: dict[tuple[str, str], list[dict[str, Any]]] = {}
    out: list[dict[str, Any]] = []

    for fill in sorted(fills, key=lambda f: f["ts"]):
        row = dict(fill)
        qty = Decimal(str(row["qty"]))
        price = Decimal(str(row["price"]))
        fee = Decimal(str(row["fee"]))
        action = str(row["action"]).lower()

        cash = row.get("cash_delta")
        if cash is None:
            cash = -(qty * price + fee) if action == "buy" else qty * price - fee
        elif not isinstance(cash, Decimal):
            cash = Decimal(str(cash))
        row["cash_impact"] = cash

        key = (row["ticker"], row["side"])
        if action == "buy":
            row["trade_pnl"] = None
            row["trade_pnl_pct"] = None
            open_lots.setdefault(key, []).append(
                {
                    "qty": qty,
                    "entry_price": price,
                    "entry_fee": fee,
                }
            )
            out.append(row)
            continue

        remaining = qty
        lots = open_lots.get(key, [])
        fill_net = Decimal("0")
        fill_basis = Decimal("0")
        while remaining > 0 and lots:
            lot = lots[0]
            lot_qty = lot["qty"]
            close_qty = min(remaining, lot_qty)
            entry_price = lot["entry_price"]
            gross = (price - entry_price) * close_qty
            fee_share = lot["entry_fee"] * (close_qty / lot_qty) + fee * (
                close_qty / qty if qty > 0 else Decimal("0")
            )
            net = gross - fee_share
            basis = entry_price * close_qty
            fill_net += net
            fill_basis += basis
            remaining -= close_qty
            if close_qty >= lot_qty:
                lots.pop(0)
            else:
                lot["qty"] = lot_qty - close_qty
                lot["entry_fee"] = lot["entry_fee"] * (Decimal("1") - close_qty / lot_qty)
        open_lots[key] = lots

        if fill_basis > 0:
            pct = (fill_net / fill_basis) * Decimal("100")
            row["trade_pnl"] = fill_net
            row["trade_pnl_pct"] = pct
        else:
            row["trade_pnl"] = None
            row["trade_pnl_pct"] = None
        out.append(row)

    return out


def summarize_period(
    *,
    round_trips: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    start: datetime | None,
    end: datetime | None,
    baseline: Decimal,
    account_pnl_value: Decimal | None = None,
    period_deposits: Decimal | None = None,
) -> dict[str, Any]:
    closed = [
        rt
        for rt in round_trips
        if rt.get("exit_ts") and _in_range(rt["exit_ts"], start, end)
    ]
    realized = sum((Decimal(str(rt["net_pnl"])) for rt in closed), Decimal("0"))
    if account_pnl_value is not None:
        realized = account_pnl_value
    wins = sum(1 for rt in closed if Decimal(str(rt["net_pnl"])) > 0)
    if account_pnl_value is not None and not closed:
        wins = 1 if account_pnl_value > 0 else 0
    fill_count = len([f for f in fills if _in_range(f["ts"], start, end)])
    pct = (realized / baseline * Decimal("100")) if baseline > 0 else None
    return {
        "realized_pnl": str(realized.quantize(Decimal("0.0001"))),
        "pnl_pct": str(pct.quantize(Decimal("0.01"))) if pct is not None else None,
        "closed_trades": len(closed),
        "wins": wins,
        "fill_count": fill_count,
        "win_rate": f"{(wins / len(closed) * 100):.1f}" if closed else None,
        "net_deposits": str(period_deposits.quantize(Decimal("0.0001"))) if period_deposits is not None else None,
    }


def build_pnl_series(
    round_trips: list[dict[str, Any]],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    initial: Decimal = Decimal("0"),
) -> list[dict[str, Any]]:
    """Cumulative realized P&L at each closed trade exit."""
    closed = [
        rt
        for rt in round_trips
        if rt.get("exit_ts") and _in_range(rt["exit_ts"], start, end)
    ]
    closed.sort(key=lambda r: r["exit_ts"])
    points: list[dict[str, Any]] = []
    if start:
        points.append(
            {
                "ts": start,
                "cumulative_pnl": str(Decimal("0")),
                "equity": str(initial.quantize(Decimal("0.0001"))),
            }
        )
    cumulative = Decimal("0")
    for rt in closed:
        cumulative += Decimal(str(rt["net_pnl"]))
        equity = initial + cumulative
        points.append(
            {
                "ts": rt["exit_ts"],
                "cumulative_pnl": str(cumulative.quantize(Decimal("0.0001"))),
                "equity": str(equity.quantize(Decimal("0.0001"))),
            }
        )
    if not points and end:
        points.append(
            {
                "ts": end,
                "cumulative_pnl": "0",
                "equity": str(initial.quantize(Decimal("0.0001"))),
            }
        )
    return points


def build_equity_pnl_series(
    curve: list[dict[str, Any]],
    initial: Decimal,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    deposits: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows = sorted(curve, key=lambda r: r["ts"])
    points: list[dict[str, Any]] = []
    for row in rows:
        ts = row["ts"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if not _in_range(ts, start, end):
            continue
        equity = Decimal(str(row["equity"]))
        invested = cumulative_capital(deposits or [], until=ts) if deposits else initial
        pnl = equity - invested
        points.append(
            {
                "ts": ts,
                "cumulative_pnl": str(pnl.quantize(Decimal("0.0001"))),
                "equity": str(equity.quantize(Decimal("0.0001"))),
                "capital_invested": str(invested.quantize(Decimal("0.0001"))),
            }
        )
    return points


def build_account_pnl_series(
    *,
    deposits: list[dict[str, Any]],
    round_trips: list[dict[str, Any]],
    current_equity: Decimal,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fallback account P&L from closed trades, anchored to equity minus deposits."""
    end_ts = end or datetime.now(timezone.utc)
    total_invested = cumulative_capital(deposits, until=end_ts)
    account_now = current_equity - total_invested

    closed = [
        rt
        for rt in round_trips
        if rt.get("exit_ts") and _in_range(rt["exit_ts"], None, end_ts)
    ]
    closed.sort(key=lambda r: r["exit_ts"])

    points: list[dict[str, Any]] = []
    cumulative = Decimal("0")
    for rt in closed:
        if not _in_range(rt["exit_ts"], start, end_ts):
            continue
        cumulative += Decimal(str(rt["net_pnl"] or 0))
        points.append(
            {
                "ts": rt["exit_ts"],
                "cumulative_pnl": str(cumulative.quantize(Decimal("0.0001"))),
                "equity": str((total_invested + cumulative).quantize(Decimal("0.0001"))),
                "capital_invested": str(total_invested.quantize(Decimal("0.0001"))),
            }
        )

    if start and (not points or points[0]["ts"] != start):
        invested_start = cumulative_capital(deposits, until=start)
        points.insert(
            0,
            {
                "ts": start,
                "cumulative_pnl": "0",
                "equity": str(invested_start.quantize(Decimal("0.0001"))),
                "capital_invested": str(invested_start.quantize(Decimal("0.0001"))),
            },
        )

    if not points or points[-1]["ts"] != end_ts:
        if start:
            last_cumulative = Decimal(str(points[-1]["cumulative_pnl"])) if points else Decimal("0")
            invested_end = cumulative_capital(deposits, until=end_ts)
            points.append(
                {
                    "ts": end_ts,
                    "cumulative_pnl": str(last_cumulative.quantize(Decimal("0.0001"))),
                    "equity": str((invested_end + last_cumulative).quantize(Decimal("0.0001"))),
                    "capital_invested": str(invested_end.quantize(Decimal("0.0001"))),
                }
            )
        else:
            points.append(
                {
                    "ts": end_ts,
                    "cumulative_pnl": str(account_now.quantize(Decimal("0.0001"))),
                    "equity": str(current_equity.quantize(Decimal("0.0001"))),
                    "capital_invested": str(total_invested.quantize(Decimal("0.0001"))),
                }
            )

    if start:
        base = Decimal("0")
        if points:
            base = Decimal(str(points[0]["cumulative_pnl"]))
        return [
            {
                **p,
                "cumulative_pnl": str((Decimal(str(p["cumulative_pnl"])) - base).quantize(Decimal("0.0001"))),
            }
            for p in points
        ]
    return points
