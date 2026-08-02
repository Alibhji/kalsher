from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis

from common.settings import TraderSettings
from trader.app.book import (
    get_ask_levels_for_buy,
    get_bid_levels_for_sell,
    get_quotes,
    is_book_stale,
    mid_price,
)
from trader.app.ledger import apply_fill_tx, fee_for_fill
from trader.app.store import TradingStore


class PaperEngine:
    def __init__(
        self,
        pool: asyncpg.Pool,
        redis: aioredis.Redis,
        settings: TraderSettings,
    ) -> None:
        self.pool = pool
        self.redis = redis
        self.settings = settings
        self.store = TradingStore(pool)

    async def submit_order(self, order: dict[str, Any], experiment: dict[str, Any]) -> dict[str, Any]:
        ticker = order["ticker"]
        if self.settings.guards.reject_if_book_stale and await is_book_stale(self.redis, ticker):
            return await self.store.update_order(
                order["id"],
                status="rejected",
                reason="book_stale",
            ) or order

        side = order["side"]
        action = order["action"]
        order_type = order["type"]
        qty = Decimal(str(order["qty"]))
        filled = Decimal(str(order.get("filled_qty") or 0))
        remaining = qty - filled

        if order_type == "limit":
            limit_price = Decimal(str(order["limit_price"]))
            if await self._try_limit_fill(order, experiment, limit_price, remaining):
                return await self.store.get_order(order["id"]) or order
            return await self.store.update_order(order["id"], status="open") or order

        fills = await self._walk_book(order, action, side, ticker, remaining)
        if not fills:
            quotes = await get_quotes(self.redis, ticker)
            ref = mid_price(quotes, side)
            return await self.store.update_order(
                order["id"],
                status="rejected",
                reason=f"no liquidity at {ref}",
            ) or order

        return await self.store.get_order(order["id"]) or order

    async def _walk_book(
        self,
        order: dict[str, Any],
        action: str,
        side: str,
        ticker: str,
        remaining: Decimal,
    ) -> list[tuple[Decimal, Decimal]]:
        if action == "buy":
            levels = await get_ask_levels_for_buy(self.redis, ticker, side)
        else:
            levels = await get_bid_levels_for_sell(self.redis, ticker, side)

        if not levels:
            return []

        first_price = levels[0][0]
        max_slip = Decimal(self.settings.fill.max_slippage_e4) / Decimal("10000")
        fills: list[tuple[Decimal, Decimal]] = []

        for price, avail in levels:
            if action == "buy" and price > first_price + max_slip:
                break
            if action == "sell" and price < first_price - max_slip:
                break
            take = min(remaining, avail)
            if take <= 0:
                continue
            fee = fee_for_fill(take, price, "taker", self.settings.fees.maker_bps)
            if action == "buy":
                exp = await self.store.get_experiment(order["experiment_id"])
                cash = Decimal(str(exp["cash"]))
                if take * price + fee > cash:
                    take = (cash - fee) / price if price > 0 else Decimal("0")
                    take = take.quantize(Decimal("0.01"))
                    if take <= 0:
                        break
            else:
                pos = await self.store.get_position(order["experiment_id"], ticker, side)
                avail_pos = Decimal(str(pos["qty"])) if pos else Decimal("0")
                take = min(take, avail_pos)
                if take <= 0:
                    break

            await apply_fill_tx(
                self.pool,
                order_id=order["id"],
                experiment_id=order["experiment_id"],
                ticker=ticker,
                side=side,
                action=action,
                price=price,
                qty=take,
                fee=fee,
            )
            fills.append((price, take))
            remaining -= take
            if remaining <= 0:
                break

        return fills

    async def _try_limit_fill(
        self,
        order: dict[str, Any],
        experiment: dict[str, Any],
        limit_price: Decimal,
        remaining: Decimal,
    ) -> bool:
        side = order["side"]
        action = order["action"]
        ticker = order["ticker"]
        quotes = await get_quotes(self.redis, ticker)

        if action == "buy":
            ask_side = "yes" if side == "yes" else "no"
            if side == "yes":
                no_bids = await get_ask_levels_for_buy(self.redis, ticker, "yes")
                best_ask = no_bids[0][0] if no_bids else None
            else:
                levels = await get_ask_levels_for_buy(self.redis, ticker, "no")
                best_ask = levels[0][0] if levels else None
            if best_ask is None or best_ask > limit_price:
                return False
            fill_price = min(best_ask, limit_price)
        else:
            bid = mid_price(quotes, side)
            levels = await get_bid_levels_for_sell(self.redis, ticker, side)
            best_bid = levels[0][0] if levels else None
            if best_bid is None or best_bid < limit_price:
                return False
            fill_price = max(best_bid, limit_price)

        fee = fee_for_fill(remaining, fill_price, "maker", self.settings.fees.maker_bps)
        await apply_fill_tx(
            self.pool,
            order_id=order["id"],
            experiment_id=order["experiment_id"],
            ticker=ticker,
            side=side,
            action=action,
            price=fill_price,
            qty=remaining,
            fee=fee,
            liquidity="maker",
        )
        return True

    async def cancel_order(self, order: dict[str, Any], *, reason: str | None = None) -> dict[str, Any]:
        fields: dict[str, Any] = {"status": "cancelled"}
        if reason:
            fields["reason"] = reason
        return await self.store.update_order(order["id"], **fields) or order

    async def check_open_limits(self) -> None:
        orders = await self.store.list_open_orders()
        for order in orders:
            if order["mode"] != "paper" or order["type"] != "limit":
                continue
            exp = await self.store.get_experiment(order["experiment_id"])
            if not exp:
                continue
            await self._try_limit_fill(
                order,
                exp,
                Decimal(str(order["limit_price"])),
                Decimal(str(order["qty"])) - Decimal(str(order["filled_qty"])),
            )
