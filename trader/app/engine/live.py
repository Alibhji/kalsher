from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis

from common.kalshi.auth import KalshiAuth
from common.kalshi.rest import KalshiRest
from common.settings import TraderSettings
from trader.app.kalshi_orders_v2 import build_kalshi_v2_order
from trader.app.ledger import apply_fill_tx, apply_settlement_tx, fee_for_fill
from trader.app.settlement import (
    fetch_kalshi_position_map,
    resolve_market_result,
    settlement_price,
)
from trader.app.store import TradingStore


class LiveEngine:
    def __init__(
        self,
        pool: asyncpg.Pool,
        settings: TraderSettings,
        redis: aioredis.Redis,
        kalshi: KalshiRest | None = None,
    ) -> None:
        self.pool = pool
        self.redis = redis
        self.settings = settings
        self.store = TradingStore(pool)
        self.kalshi = kalshi

    def _client(self) -> KalshiRest:
        if self.kalshi is None:
            auth = KalshiAuth(self.settings.kalshi_key_id, self.settings.kalshi_private_key_path)
            self.kalshi = KalshiRest(
                self.settings.kalshi_rest_base,
                auth,
                rps=self.settings.rest_rps,
            )
        return self.kalshi

    async def submit_order(self, order: dict[str, Any], experiment: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.trading_live_enabled:
            return await self.store.update_order(
                order["id"],
                status="rejected",
                reason="TRADING_LIVE_ENABLED is false",
            ) or order

        qty = Decimal(str(order["qty"]))
        limit_price = Decimal(str(order["limit_price"])) if order.get("limit_price") is not None else None

        try:
            body = await build_kalshi_v2_order(
                self.redis,
                ticker=order["ticker"],
                side=order["side"],
                action=order["action"],
                qty=qty,
                order_type=order["type"],
                limit_price=limit_price,
                client_order_id=order.get("client_order_id") or str(order["id"]),
            )
            resp = await self._client().create_order(body)
        except Exception as exc:
            return await self.store.update_order(
                order["id"],
                status="rejected",
                reason=str(exc)[:500],
            ) or order

        kalshi_id = resp.get("order_id")
        fill_count = Decimal(str(resp.get("fill_count") or "0"))
        remaining = Decimal(str(resp.get("remaining_count") or qty))
        avg_price_raw = resp.get("average_fill_price")

        if fill_count > 0:
            price = Decimal(str(avg_price_raw)) if avg_price_raw else (limit_price or Decimal("0"))
            if order["side"] == "no" and avg_price_raw:
                price = Decimal("1") - price
            fee = fee_for_fill(fill_count, price, "taker", self.settings.fees.maker_bps)
            await apply_fill_tx(
                self.pool,
                order_id=order["id"],
                experiment_id=order["experiment_id"],
                ticker=order["ticker"],
                side=order["side"],
                action=order["action"],
                price=price,
                qty=fill_count,
                fee=fee,
            )
            await self.store.update_order(
                order["id"],
                kalshi_order_id=str(kalshi_id) if kalshi_id else None,
                filled_qty=str(fill_count),
                status="filled" if remaining <= 0 else "open",
            )
        elif remaining <= 0 and fill_count <= 0:
            status = "rejected"
            reason = "order canceled with no fill"
            await self.store.update_order(
                order["id"],
                kalshi_order_id=str(kalshi_id) if kalshi_id else None,
                status=status,
                reason=reason,
            )
        else:
            await self.store.update_order(
                order["id"],
                kalshi_order_id=str(kalshi_id) if kalshi_id else None,
                status="open",
            )
            if fill_count <= 0:
                updated = await self.store.get_order(order["id"]) or order
                await self._sync_fills(updated)

        return await self.store.get_order(order["id"]) or order

    async def cancel_order(self, order: dict[str, Any]) -> dict[str, Any]:
        kid = order.get("kalshi_order_id")
        if kid:
            try:
                await self._client().cancel_order(str(kid))
            except Exception:
                pass
        return await self.store.update_order(order["id"], status="cancelled") or order

    async def _sync_fills(self, order: dict[str, Any]) -> None:
        kid = order.get("kalshi_order_id")
        if not kid:
            return
        try:
            data = await self._client().get_fills(order_id=str(kid))
        except Exception:
            return
        filled_so_far = Decimal(str(order.get("filled_qty") or 0))
        for fill in data.get("fills", []):
            qty = Decimal(str(fill.get("count_fp") or fill.get("count") or 0))
            if qty <= 0:
                continue
            price_raw = fill.get("yes_price_dollars") or fill.get("no_price_dollars") or fill.get("price")
            price = Decimal(str(price_raw)) if price_raw else Decimal("0")
            if order["side"] == "no" and fill.get("yes_price_dollars"):
                price = Decimal("1") - price
            fee = fee_for_fill(qty, price, "taker", self.settings.fees.maker_bps)
            await apply_fill_tx(
                self.pool,
                order_id=order["id"],
                experiment_id=order["experiment_id"],
                ticker=order["ticker"],
                side=order["side"],
                action=order["action"],
                price=price,
                qty=qty,
                fee=fee,
            )
            filled_so_far += qty
        if filled_so_far > Decimal(str(order.get("filled_qty") or 0)):
            status = "filled" if filled_so_far >= Decimal(str(order["qty"])) else "open"
            await self.store.update_order(order["id"], filled_qty=str(filled_so_far), status=status)

    async def reconcile_experiment(
        self,
        experiment_id: UUID,
        kalshi_map: dict[str, dict[str, Decimal]] | None = None,
    ) -> int:
        """Settle local positions that Kalshi has already closed. Returns settlements applied."""
        if not self.settings.trading_live_enabled:
            return 0
        client = self._client()
        if kalshi_map is None:
            kalshi_map = await fetch_kalshi_position_map(client)

        positions = await self.store.list_positions(experiment_id)
        settled = 0
        for pos in positions:
            qty = Decimal(str(pos["qty"]))
            if qty <= 0:
                continue
            ticker = str(pos["ticker"])
            side = str(pos["side"])
            kalshi_qty = kalshi_map.get(ticker, {}).get(side, Decimal("0"))
            if kalshi_qty >= qty:
                continue

            result, _status = await resolve_market_result(self.pool, client, ticker)
            if not result:
                continue

            price = settlement_price(side, result)
            await apply_settlement_tx(
                self.pool,
                experiment_id=experiment_id,
                ticker=ticker,
                side=side,
                price=price,
                qty=qty,
            )
            settled += 1
        return settled

    async def reconcile_positions(self) -> None:
        if not self.settings.trading_live_enabled:
            return
        try:
            client = self._client()
            kalshi_map = await fetch_kalshi_position_map(client)
            exps = await self.store.list_experiments()
            for exp in exps:
                if exp["mode"] != "live" or exp["status"] != "active":
                    continue
                await self.reconcile_experiment(exp["id"], kalshi_map)
        except Exception:
            pass
