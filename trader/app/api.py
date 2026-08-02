from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request

from trader.app.capital import account_pnl, cumulative_capital, deposits_in_period, fetch_all_kalshi_deposits
from trader.app.experiments import ExperimentService
from trader.app.fill_analysis import (
    build_account_pnl_series,
    annotate_fills_pnl,
    build_equity_pnl_series,
    build_pnl_series,
    fetch_all_kalshi_fills,
    normalize_local_fill,
    simulate_round_trips,
    simulate_round_trips_with_settlements,
    annotate_fills_pnl_with_settlements,
    summarize_period,
)
from trader.app.ledger import apply_fill_tx
from trader.app.pnl import build_profile, enrich_round_trip, parse_datetime_param, parse_equity_range
from trader.app.schemas import (
    CapitalAdjust,
    CloseAllRequest,
    ExperimentCreate,
    ExperimentOut,
    ExperimentPatch,
    FillOut,
    OrderOut,
    OrderRequest,
    PeriodSummaryOut,
    PnlPointOut,
    PnlSeriesOut,
    ProfileOut,
    RoundTripOut,
    StatsOut,
    TradingConfigOut,
)
from trader.app.tags import tags_from_params
from trader.app.store import TradingStore


def _json_dict(val: Any) -> dict:
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _exp_out(row: dict) -> ExperimentOut:
    params = _json_dict(row.get("params"))
    return ExperimentOut(
        id=row["id"],
        name=row["name"],
        mode=row["mode"],
        initial_capital=str(row["initial_capital"]),
        cash=str(row["cash"]),
        status=row["status"],
        strategy=row.get("strategy"),
        params=params,
        tags=tags_from_params(params),
        created_at=row["created_at"].isoformat(),
        archived_at=row["archived_at"].isoformat() if row.get("archived_at") else None,
    )


def _order_out(row: dict) -> OrderOut:
    return OrderOut(
        id=row["id"],
        experiment_id=row["experiment_id"],
        client_order_id=row.get("client_order_id"),
        ticker=row["ticker"],
        side=row["side"],
        action=row["action"],
        type=row["type"],
        limit_price=str(row["limit_price"]) if row.get("limit_price") is not None else None,
        qty=str(row["qty"]),
        filled_qty=str(row["filled_qty"]),
        status=row["status"],
        mode=row["mode"],
        kalshi_order_id=row.get("kalshi_order_id"),
        reason=row.get("reason"),
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


def create_router(app_state: Any) -> APIRouter:
    router = APIRouter(prefix="/api")

    def store() -> TradingStore:
        return app_state.store

    def exp_svc() -> ExperimentService:
        return app_state.exp_svc

    def engine_for(mode: str):
        return app_state.live_engine if mode == "live" else app_state.paper_engine

    def profile_kwargs():
        return {
            "settings": app_state.settings,
            "kalshi_client": app_state.live_engine._client() if app_state.settings.kalshi_key_id else None,
            "live_trading_enabled": app_state.settings.trading_live_enabled,
        }

    def _range_params(start: str | None, end: str | None) -> tuple[datetime | None, datetime]:
        start_dt = parse_datetime_param(start)
        end_dt = parse_datetime_param(end) or datetime.now(timezone.utc)
        return start_dt, end_dt

    async def _live_deposits() -> list[dict[str, Any]]:
        if not app_state.settings.kalshi_key_id:
            return []
        try:
            return await fetch_all_kalshi_deposits(app_state.live_engine._client())
        except Exception:
            return []

    async def _baseline_equity(exp_id: UUID, at: datetime | None, initial: Decimal) -> Decimal:
        if at is None:
            return initial
        row = await store().equity_at_or_before(exp_id, at)
        if row:
            return Decimal(str(row["equity"]))
        return initial

    async def _account_period_pnl(
        exp: dict,
        *,
        start_dt: datetime | None,
        end_dt: datetime,
        deposits: list[dict[str, Any]],
    ) -> tuple[Decimal, Decimal, Decimal]:
        profile = await build_profile(store(), app_state.redis, exp["id"], **profile_kwargs())
        equity_end = Decimal(str(profile["equity"]))
        invested_end = cumulative_capital(deposits, until=end_dt) if deposits else Decimal(str(exp["initial_capital"]))
        pnl_end = equity_end - invested_end

        if start_dt is None:
            baseline = invested_end if invested_end > 0 else Decimal(str(exp["initial_capital"]))
            net_dep = deposits_in_period(deposits, None, end_dt) if deposits else Decimal("0")
            return pnl_end, baseline, net_dep

        invested_start = cumulative_capital(deposits, until=start_dt) if deposits else Decimal(str(exp["initial_capital"]))
        row = await store().equity_at_or_before(exp["id"], start_dt)
        equity_start = Decimal(str(row["equity"])) if row else invested_start
        pnl_start = equity_start - invested_start
        period_pnl = pnl_end - pnl_start
        baseline = equity_start if equity_start > 0 else invested_start
        net_dep = deposits_in_period(deposits, start_dt, end_dt) if deposits else Decimal("0")
        return period_pnl, baseline, net_dep

    async def _round_trips_for_analysis(
        exp: dict,
        fills: list[dict[str, Any]],
        src: str,
        end_dt: datetime,
    ) -> list[dict[str, Any]]:
        if src in ("kalshi", "all") and exp["mode"] == "live" and app_state.settings.kalshi_key_id:
            client = app_state.live_engine._client()
            return await simulate_round_trips_with_settlements(client, fills, end=end_dt)
        rows = await store().list_round_trips(exp["id"], since=None, until=end_dt)
        round_trips: list[dict[str, Any]] = []
        for r in rows:
            enriched = enrich_round_trip(dict(r))
            round_trips.append(
                {
                    **enriched,
                    "exit_ts": enriched.get("exit_ts"),
                    "net_pnl": Decimal(str(enriched["net_pnl"]))
                    if enriched.get("net_pnl") is not None
                    else Decimal("0"),
                }
            )
        return round_trips

    async def _annotate_fills_for_analysis(
        exp: dict,
        fills: list[dict[str, Any]],
        src: str,
        end_dt: datetime,
    ) -> list[dict[str, Any]]:
        if src in ("kalshi", "all") and exp["mode"] == "live" and app_state.settings.kalshi_key_id:
            client = app_state.live_engine._client()
            return await annotate_fills_pnl_with_settlements(client, fills, end=end_dt)
        return annotate_fills_pnl(fills)

    async def _analysis_fills(
        exp: dict,
        *,
        start_dt: datetime | None,
        end_dt: datetime | None,
        source: str,
    ) -> tuple[list[dict[str, Any]], str]:
        exp_id = exp["id"]
        use_kalshi = exp["mode"] == "live" and source in ("kalshi", "all") and app_state.settings.kalshi_key_id
        kalshi_fills: list[dict[str, Any]] = []
        if use_kalshi:
            kalshi_fills = await fetch_all_kalshi_fills(
                app_state.live_engine._client(),
                start=start_dt,
                end=end_dt,
            )

        local_rows = await store().list_fills(exp_id, since=start_dt, until=end_dt, limit=5000)
        local_fills = [normalize_local_fill(r) for r in local_rows]

        if source == "kalshi" and use_kalshi:
            return kalshi_fills, "kalshi"
        if source == "local" or not use_kalshi:
            return local_fills, "local"

        seen = {f["id"] for f in kalshi_fills if f.get("id")}
        merged = list(kalshi_fills)
        for f in local_fills:
            if f.get("id") and f["id"] in seen:
                continue
            merged.append(f)
        merged.sort(key=lambda r: r["ts"])
        return merged, "kalshi+local"

    def _as_uuid(val: str) -> UUID:
        try:
            return UUID(str(val))
        except ValueError:
            return uuid.uuid5(uuid.NAMESPACE_URL, str(val))

    def _fill_out_rows(fills: list[dict[str, Any]]) -> list[FillOut]:
        out: list[FillOut] = []
        for f in fills:
            cash = f.get("cash_impact", f.get("cash_delta"))
            trade_pnl = f.get("trade_pnl")
            trade_pct = f.get("trade_pnl_pct")
            out.append(
                FillOut(
                    id=_as_uuid(str(f["id"])),
                    ts=f["ts"].isoformat() if isinstance(f["ts"], datetime) else str(f["ts"]),
                    ticker=f["ticker"],
                    side=f["side"],
                    action=f["action"],
                    price=str(f["price"]),
                    qty=str(f["qty"]),
                    fee=str(f["fee"]),
                    cost=str(f["cost"]),
                    cash_impact=str(Decimal(str(cash)).quantize(Decimal("0.0001"))),
                    trade_pnl=str(Decimal(str(trade_pnl)).quantize(Decimal("0.0001"))) if trade_pnl is not None else None,
                    trade_pnl_pct=str(Decimal(str(trade_pct)).quantize(Decimal("0.01"))) if trade_pct is not None else None,
                )
            )
        return out

    def _sim_round_trip_out(rt: dict, idx: int) -> RoundTripOut:
        qty = Decimal(str(rt["qty"]))
        entry_price = Decimal(str(rt["entry_price"]))
        basis = qty * entry_price
        net = Decimal(str(rt["net_pnl"]))
        pct = (net / basis * Decimal("100")) if basis > 0 else None
        return RoundTripOut(
            id=uuid.uuid5(uuid.NAMESPACE_DNS, f"{rt['ticker']}-{rt['entry_ts']}-{idx}"),
            ticker=rt["ticker"],
            side=rt["side"],
            qty=str(qty),
            entry_ts=rt["entry_ts"].isoformat(),
            entry_price=str(entry_price),
            exit_ts=rt["exit_ts"].isoformat() if rt.get("exit_ts") else None,
            exit_price=str(rt["exit_price"]) if rt.get("exit_price") is not None else None,
            cost_basis=str(basis.quantize(Decimal("0.0001"))),
            gross_pnl=str(rt["gross_pnl"]),
            fees=str(rt["fees"]),
            net_pnl=str(net),
            pnl_pct=str(pct.quantize(Decimal("0.01"))) if pct is not None else None,
            exit_kind="close",
            action_at_entry=f"buy {rt['side']}",
        )

    @router.get("/config", response_model=TradingConfigOut)
    async def trading_config():
        s = app_state.settings
        return TradingConfigOut(
            live_trading_enabled=s.trading_live_enabled,
            kalshi_configured=bool(s.kalshi_key_id),
        )

    @router.post("/experiments", response_model=ExperimentOut)
    async def create_experiment(body: ExperimentCreate):
        if body.mode == "live":
            if not app_state.settings.trading_live_enabled:
                raise HTTPException(403, "TRADING_LIVE_ENABLED is false")
            if not app_state.settings.kalshi_key_id:
                raise HTTPException(400, "Kalshi API keys not configured")
            acct = await fetch_kalshi_account(
                app_state.settings,
                app_state.live_engine._client() if app_state.settings.kalshi_key_id else None,
            )
            row = await exp_svc().create(body.name, body.mode, acct["equity"], body.strategy, body.params, [])
            row = await store().set_live_baseline(row["id"], acct["available_funds"], acct["equity"]) or row
        else:
            row = await exp_svc().create(
                body.name, body.mode, body.initial_capital, body.strategy, body.params, body.tags
            )
        return _exp_out(row)

    @router.get("/experiments", response_model=list[ExperimentOut])
    async def list_experiments(
        include_archived: bool = Query(default=False),
        tag: str | None = Query(default=None),
    ):
        rows = await exp_svc().list_all(include_archived=include_archived, tag=tag)
        return [_exp_out(r) for r in rows]

    @router.get("/experiments/{exp_id}", response_model=ExperimentOut)
    async def get_experiment(exp_id: UUID):
        return _exp_out(await exp_svc().get(exp_id))

    @router.patch("/experiments/{exp_id}", response_model=ExperimentOut)
    async def patch_experiment(exp_id: UUID, body: ExperimentPatch):
        exp = await exp_svc().get(exp_id)
        if body.tags is not None and exp["mode"] != "paper":
            raise HTTPException(400, "tags are only supported for paper experiments")
        row = await exp_svc().patch(
            exp_id,
            name=body.name,
            status=body.status,
            strategy=body.strategy,
            params=body.params,
            tags=body.tags,
        )
        return _exp_out(row)

    @router.post("/experiments/{exp_id}/capital", response_model=ExperimentOut)
    async def adjust_capital(exp_id: UUID, body: CapitalAdjust):
        row = await exp_svc().adjust_capital(exp_id, body.set, body.delta)
        return _exp_out(row)

    @router.post("/experiments/{exp_id}/reset", response_model=ExperimentOut)
    async def reset_experiment(exp_id: UUID):
        return _exp_out(await exp_svc().reset(exp_id))

    @router.delete("/experiments/{exp_id}", response_model=ExperimentOut)
    async def delete_experiment(exp_id: UUID, permanent: bool = Query(default=False)):
        if permanent:
            return _exp_out(await exp_svc().delete_permanent(exp_id))
        return _exp_out(await exp_svc().archive(exp_id))

    @router.post("/experiments/{exp_id}/orders", response_model=OrderOut)
    async def place_order(
        exp_id: UUID,
        body: OrderRequest,
        request: Request,
        x_confirm_live: str | None = Header(default=None),
    ):
        exp = await exp_svc().get(exp_id)
        if exp["status"] != "active":
            raise HTTPException(409, "experiment not active")

        if body.qty > Decimal(str(app_state.settings.guards.max_order_qty)):
            raise HTTPException(400, "qty exceeds max_order_qty")

        if body.client_order_id:
            existing = await store().get_order_by_client_id(body.client_order_id)
            if existing:
                return _order_out(existing)

        if exp["mode"] == "live":
            if not app_state.settings.trading_live_enabled:
                raise HTTPException(403, "TRADING_LIVE_ENABLED is false")
            if x_confirm_live != "yes":
                raise HTTPException(403, "X-Confirm-Live: yes header required")

        pos = await store().get_position(exp_id, body.ticker, body.side)
        pos_qty = Decimal(str(pos["qty"])) if pos else Decimal("0")
        if body.action == "buy":
            new_qty = pos_qty + body.qty
        else:
            if body.qty > pos_qty:
                raise HTTPException(400, f"insufficient position: {pos_qty}")
            new_qty = pos_qty - body.qty
        if new_qty > Decimal(str(app_state.settings.guards.max_position_per_market)):
            raise HTTPException(400, "would exceed max_position_per_market")

        order = await store().create_order(
            exp_id,
            body.ticker,
            body.side,
            body.action,
            body.type,
            body.qty,
            exp["mode"],
            body.limit_price,
            body.client_order_id or str(uuid.uuid4()),
            status="pending",
        )

        eng = engine_for(exp["mode"])
        result = await eng.submit_order(order, exp)
        if result.get("status") == "rejected":
            raise HTTPException(422, result.get("reason") or "order rejected")
        return _order_out(result)

    @router.delete("/orders/{order_id}", response_model=OrderOut)
    async def cancel_order(order_id: UUID):
        order = await store().get_order(order_id)
        if not order:
            raise HTTPException(404, "order not found")
        exp = await exp_svc().get(order["experiment_id"])
        eng = engine_for(exp["mode"])
        result = await eng.cancel_order(order)
        return _order_out(result)

    @router.post("/experiments/{exp_id}/close_all")
    async def close_all(
        exp_id: UUID,
        body: CloseAllRequest,
        x_confirm_live: str | None = Header(default=None),
    ):
        exp = await exp_svc().get(exp_id)
        positions = await store().list_positions(exp_id)
        results = []
        for p in positions:
            if body.ticker and p["ticker"] != body.ticker:
                continue
            qty = Decimal(str(p["qty"]))
            if qty <= 0:
                continue
            req = OrderRequest(
                ticker=p["ticker"],
                side=p["side"],
                action="sell",
                type="market",
                qty=qty,
            )
            order = await store().create_order(
                exp_id,
                req.ticker,
                req.side,
                req.action,
                req.type,
                req.qty,
                exp["mode"],
                client_order_id=str(uuid.uuid4()),
            )
            eng = engine_for(exp["mode"])
            if exp["mode"] == "live":
                if not app_state.settings.trading_live_enabled or x_confirm_live != "yes":
                    raise HTTPException(403, "live close_all requires TRADING_LIVE_ENABLED and X-Confirm-Live")
            results.append(_order_out(await eng.submit_order(order, exp)))
        return {"closed": results}

    @router.get("/experiments/{exp_id}/orders", response_model=list[OrderOut])
    async def list_orders(
        exp_id: UUID,
        status: str | None = None,
        ticker: str | None = None,
        since: datetime | None = None,
    ):
        await exp_svc().get(exp_id)
        rows = await store().list_orders(exp_id, status, ticker, since)
        return [_order_out(r) for r in rows]

    @router.get("/experiments/{exp_id}/fills", response_model=list[FillOut])
    async def list_fills(
        exp_id: UUID,
        ticker: str | None = None,
        limit: int = Query(default=1000, le=5000),
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        source: str = Query(default="auto"),
    ):
        exp = await exp_svc().get(exp_id)
        start_dt, end_dt = _range_params(start, end)
        src = source
        if src == "auto":
            src = "kalshi" if exp["mode"] == "live" and app_state.settings.kalshi_key_id else "local"
        fills, _ = await _analysis_fills(exp, start_dt=None, end_dt=end_dt, source=src)
        fills = await _annotate_fills_for_analysis(exp, fills, src, end_dt)
        if start_dt:
            fills = [f for f in fills if f["ts"] >= start_dt]
        if ticker:
            fills = [f for f in fills if f["ticker"] == ticker]
        fills.sort(key=lambda f: f["ts"], reverse=True)
        return _fill_out_rows(fills[:limit])

    @router.get("/experiments/{exp_id}/round_trips", response_model=list[RoundTripOut])
    async def list_round_trips(
        exp_id: UUID,
        ticker: str | None = None,
        since: datetime | None = None,
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        source: str = Query(default="auto"),
    ):
        exp = await exp_svc().get(exp_id)
        start_dt, end_dt = _range_params(start, end)
        if start_dt is None and since is not None:
            start_dt = since
        src = source
        if src == "auto":
            src = "kalshi" if exp["mode"] == "live" and app_state.settings.kalshi_key_id else "local"

        if src in ("kalshi", "all") and exp["mode"] == "live" and app_state.settings.kalshi_key_id:
            fills, _ = await _analysis_fills(exp, start_dt=None, end_dt=end_dt, source=src)
            if ticker:
                fills = [f for f in fills if f["ticker"] == ticker]
            simulated = await _round_trips_for_analysis(exp, fills, src, end_dt)
            if start_dt or end_dt:
                simulated = [
                    rt
                    for rt in simulated
                    if rt.get("exit_ts")
                    and (not start_dt or rt["exit_ts"] >= start_dt)
                    and rt["exit_ts"] <= end_dt
                ]
            return [_sim_round_trip_out(rt, i) for i, rt in enumerate(reversed(simulated))]

        rows = await store().list_round_trips(exp_id, ticker, start_dt, end_dt)
        out = []
        for r in rows:
            enriched = enrich_round_trip(dict(r))
            out.append(
                RoundTripOut(
                    id=enriched["id"],
                    ticker=enriched["ticker"],
                    side=enriched["side"],
                    qty=str(enriched["qty"]),
                    entry_ts=enriched["entry_ts"].isoformat(),
                    entry_price=str(enriched["entry_price"]),
                    exit_ts=enriched["exit_ts"].isoformat() if enriched.get("exit_ts") else None,
                    exit_price=str(enriched["exit_price"]) if enriched.get("exit_price") is not None else None,
                    cost_basis=enriched["cost_basis"],
                    gross_pnl=str(enriched["gross_pnl"]) if enriched.get("gross_pnl") is not None else None,
                    fees=str(enriched["fees"]),
                    net_pnl=str(enriched["net_pnl"]) if enriched.get("net_pnl") is not None else None,
                    pnl_pct=enriched.get("pnl_pct"),
                    exit_kind=enriched.get("exit_kind"),
                    action_at_entry=enriched["action_at_entry"],
                )
            )
        return out

    @router.get("/experiments/{exp_id}/positions")
    async def list_positions(exp_id: UUID):
        profile = await build_profile(store(), app_state.redis, exp_id, **profile_kwargs())
        return {"positions": profile["positions"]}

    @router.get("/experiments/{exp_id}/profile", response_model=ProfileOut)
    async def get_profile(exp_id: UUID):
        await exp_svc().get(exp_id)
        p = await build_profile(store(), app_state.redis, exp_id, **profile_kwargs())
        return ProfileOut(**p)

    @router.post("/experiments/{exp_id}/sync_live", response_model=ProfileOut)
    async def sync_live_profile(exp_id: UUID):
        exp = await exp_svc().get(exp_id)
        if exp["mode"] != "live":
            raise HTTPException(400, "not a live experiment")
        if not app_state.settings.trading_live_enabled:
            raise HTTPException(403, "TRADING_LIVE_ENABLED is false")
        await app_state.live_engine.reconcile_experiment(exp_id)
        p = await build_profile(store(), app_state.redis, exp_id, **profile_kwargs())
        return ProfileOut(**p)

    @router.get("/experiments/{exp_id}/equity")
    async def get_equity(
        exp_id: UUID,
        range: str | None = Query(default=None),
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
    ):
        await exp_svc().get(exp_id)
        start_dt = parse_datetime_param(start) or parse_equity_range(range)
        end_dt = parse_datetime_param(end) or datetime.now(timezone.utc)
        rows = await store().get_equity_curve(exp_id, start_dt, end_dt)
        return {
            "points": [
                {
                    "ts": r["ts"].isoformat(),
                    "cash": str(r["cash"]),
                    "position_value": str(r["position_value"]),
                    "equity": str(r["equity"]),
                    "drawdown": str(r["drawdown"]),
                }
                for r in rows
            ]
        }

    @router.get("/experiments/{exp_id}/period_summary", response_model=PeriodSummaryOut)
    async def period_summary(
        exp_id: UUID,
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        source: str = Query(default="auto"),
    ):
        exp = await exp_svc().get(exp_id)
        start_dt, end_dt = _range_params(start, end)
        src = source
        if src == "auto":
            src = "kalshi" if exp["mode"] == "live" and app_state.settings.kalshi_key_id else "local"
        initial = Decimal(str(exp["initial_capital"]))
        deposits = await _live_deposits() if exp["mode"] == "live" else []
        # Account-level delta only for all-time (no start). With a start date, use closed trades in range.
        use_account_pnl = bool(deposits) and exp["mode"] == "live" and start_dt is None

        if use_account_pnl:
            period_pnl, baseline, net_dep = await _account_period_pnl(
                exp, start_dt=start_dt, end_dt=end_dt, deposits=deposits
            )
            invested = cumulative_capital(deposits, until=end_dt)
        elif deposits and exp["mode"] == "live" and start_dt is not None:
            baseline = cumulative_capital(deposits, until=start_dt)
            if baseline <= 0:
                baseline = await _baseline_equity(exp_id, start_dt, initial)
            period_pnl = None
            net_dep = deposits_in_period(deposits, start_dt, end_dt)
            invested = cumulative_capital(deposits, until=end_dt)
        else:
            baseline = await _baseline_equity(exp_id, start_dt, initial)
            period_pnl = None
            net_dep = Decimal("0")
            invested = baseline

        fills, resolved_source = await _analysis_fills(
            exp, start_dt=None, end_dt=end_dt, source=src
        )
        round_trips = await _round_trips_for_analysis(exp, fills, src, end_dt)

        summary = summarize_period(
            round_trips=round_trips,
            fills=fills,
            start=start_dt,
            end=end_dt,
            baseline=baseline,
            account_pnl_value=period_pnl if use_account_pnl else None,
            period_deposits=net_dep if use_account_pnl else None,
        )
        pnl_pct = summary["pnl_pct"]
        if use_account_pnl and baseline > 0 and period_pnl is not None:
            pct = (period_pnl / baseline) * Decimal("100")
            pnl_pct = str(pct.quantize(Decimal("0.01")))
        elif start_dt is None and exp["mode"] == "live" and resolved_source.startswith("kalshi") and not use_account_pnl:
            pnl_pct = None
        return PeriodSummaryOut(
            start=start_dt.isoformat() if start_dt else None,
            end=end_dt.isoformat(),
            realized_pnl=summary["realized_pnl"],
            pnl_pct=pnl_pct,
            closed_trades=summary["closed_trades"],
            wins=summary["wins"],
            fill_count=summary["fill_count"],
            win_rate=summary["win_rate"],
            source=resolved_source,
            baseline=str(baseline.quantize(Decimal("0.0001"))),
            capital_invested=str(invested.quantize(Decimal("0.0001"))) if use_account_pnl else None,
            net_deposits=str(net_dep.quantize(Decimal("0.0001"))) if use_account_pnl and net_dep > 0 else summary.get("net_deposits"),
        )

    @router.get("/experiments/{exp_id}/pnl_series", response_model=PnlSeriesOut)
    async def pnl_series(
        exp_id: UUID,
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        source: str = Query(default="auto"),
    ):
        exp = await exp_svc().get(exp_id)
        start_dt, end_dt = _range_params(start, end)
        src = source
        if src == "auto":
            src = "kalshi" if exp["mode"] == "live" and app_state.settings.kalshi_key_id else "local"
        initial = Decimal(str(exp["initial_capital"]))
        deposits = await _live_deposits() if exp["mode"] == "live" else []
        baseline = await _baseline_equity(exp_id, start_dt, initial)

        if deposits and exp["mode"] == "live":
            curve = await store().get_equity_curve(exp_id, start_dt, end_dt)
            if curve:
                points = build_equity_pnl_series(
                    curve, initial, start=start_dt, end=end_dt, deposits=deposits
                )
                if start_dt and points:
                    base = Decimal(str(points[0]["cumulative_pnl"]))
                    for p in points:
                        p["cumulative_pnl"] = str(
                            (Decimal(str(p["cumulative_pnl"])) - base).quantize(Decimal("0.0001"))
                        )
                source_label = "equity_curve+deposits"
            else:
                fills, resolved_source = await _analysis_fills(
                    exp, start_dt=None, end_dt=end_dt, source=src
                )
                round_trips = await _round_trips_for_analysis(exp, fills, src, end_dt)
                profile = await build_profile(store(), app_state.redis, exp_id, **profile_kwargs())
                points = build_account_pnl_series(
                    deposits=deposits,
                    round_trips=round_trips,
                    current_equity=Decimal(str(profile["equity"])),
                    start=start_dt,
                    end=end_dt,
                )
                source_label = f"{resolved_source}+deposits"
        elif src in ("kalshi", "all") and exp["mode"] == "live" and app_state.settings.kalshi_key_id:
            fills, resolved_source = await _analysis_fills(
                exp, start_dt=None, end_dt=end_dt, source=src
            )
            round_trips = await _round_trips_for_analysis(exp, fills, src, end_dt)
            points = build_pnl_series(round_trips, start=start_dt, end=end_dt, initial=baseline)
            source_label = resolved_source
        else:
            curve = await store().get_equity_curve(exp_id, start_dt, end_dt)
            if curve:
                points = build_equity_pnl_series(
                    curve, initial, start=start_dt, end=end_dt, deposits=deposits or None
                )
                source_label = "equity_curve"
            else:
                fills, resolved_source = await _analysis_fills(
                    exp, start_dt=None, end_dt=end_dt, source="local"
                )
                round_trips = simulate_round_trips(fills)
                points = build_pnl_series(round_trips, start=start_dt, end=end_dt, initial=baseline)
                source_label = "local_fills"

        if len(points) > 400:
            step = max(1, len(points) // 400)
            trimmed = points[::step]
            if trimmed[-1] != points[-1]:
                trimmed.append(points[-1])
            points = trimmed

        return PnlSeriesOut(
            points=[
                PnlPointOut(
                    ts=p["ts"].isoformat() if isinstance(p["ts"], datetime) else str(p["ts"]),
                    cumulative_pnl=p["cumulative_pnl"],
                    equity=p.get("equity"),
                )
                for p in points
            ],
            source=source_label,
        )

    @router.post("/experiments/{exp_id}/sync_kalshi_history")
    async def sync_kalshi_history(exp_id: UUID):
        exp = await exp_svc().get(exp_id)
        if exp["mode"] != "live":
            raise HTTPException(400, "not a live experiment")
        if not app_state.settings.kalshi_key_id:
            raise HTTPException(400, "Kalshi API keys not configured")
        client = app_state.live_engine._client()
        fills = await fetch_all_kalshi_fills(client)
        deposits = await fetch_all_kalshi_deposits(client)
        invested = cumulative_capital(deposits)
        return {
            "fill_count": len(fills),
            "deposit_count": len(deposits),
            "capital_invested": str(invested.quantize(Decimal("0.0001"))),
            "first_ts": fills[0]["ts"].isoformat() if fills else None,
            "last_ts": fills[-1]["ts"].isoformat() if fills else None,
            "source": "kalshi",
        }

    @router.get("/experiments/{exp_id}/stats", response_model=StatsOut)
    async def get_stats(exp_id: UUID):
        await exp_svc().get(exp_id)
        s = await store().get_stats(exp_id)
        if not s:
            exp = await exp_svc().get(exp_id)
            return StatsOut(
                experiment_id=exp_id,
                name=exp["name"],
                mode=exp["mode"],
                closed_trades=0,
                wins=0,
                net_pnl="0",
                max_drawdown="0",
            )
        closed = int(s.get("closed_trades") or 0)
        wins = int(s.get("wins") or 0)
        win_rate = f"{(wins / closed * 100):.1f}" if closed > 0 else None
        return StatsOut(
            experiment_id=s["experiment_id"],
            name=s["name"],
            mode=s["mode"],
            closed_trades=closed,
            wins=wins,
            net_pnl=str(s.get("net_pnl") or 0),
            max_drawdown=str(s.get("max_drawdown") or 0),
            win_rate=win_rate,
        )

    @router.get("/healthz")
    async def healthz():
        return {"ok": True}

    return router
