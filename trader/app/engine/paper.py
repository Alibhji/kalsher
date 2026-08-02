from __future__ import annotations

from decimal import Decimal
from typing import Any

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
            await self._fill_marketable_limit(order, experiment, limit_price, remaining)
            current = await self.store.get_order(order["id"]) or order
            filled_now = Decimal(str(current.get("filled_qty") or 0))
            if filled_now >= qty:
                return current
            return await self.store.update_order(order["id"], status="open") or current

        # Market = Kalshi IOC: take only BBO, cancel any remainder.
        fills = await self._walk_book(
            order,
            action,
            side,
            ticker,
            remaining,
            bbo_only=True,
            liquidity="taker",
        )
        if not fills:
            quotes = await get_quotes(self.redis, ticker)
            ref = mid_price(quotes, side)
            return await self.store.update_order(
                order["id"],
                status="rejected",
                reason=f"no liquidity at {ref}",
            ) or order

        current = await self.store.get_order(order["id"]) or order
        filled_now = Decimal(str(current.get("filled_qty") or 0))
        if filled_now < qty:
            return await self.store.update_order(
                order["id"],
                status="cancelled",
                reason="ioc",
            ) or current
        return current

    async def _walk_book(
        self,
        order: dict[str, Any],
        action: str,
        side: str,
        ticker: str,
        remaining: Decimal,
        *,
        bbo_only: bool = False,
        limit_price: Decimal | None = None,
        liquidity: str = "taker",
        fill_price_override: Decimal | None = None,
    ) -> list[tuple[Decimal, Decimal]]:
        if action == "buy":
            levels = await get_ask_levels_for_buy(self.redis, ticker, side)
        else:
            levels = await get_bid_levels_for_sell(self.redis, ticker, side)

        if not levels:
            return []

        if bbo_only:
            levels = levels[:1]

        fills: list[tuple[Decimal, Decimal]] = []

        for price, avail in levels:
            if limit_price is not None:
                if action == "buy" and price > limit_price:
                    break
                if action == "sell" and price < limit_price:
                    break

            take = min(remaining, avail)
            if take <= 0:
                continue

            exec_price = fill_price_override if fill_price_override is not None else price
            fee = fee_for_fill(take, exec_price, liquidity, self.settings.fees.maker_bps)

            if action == "buy":
                exp = await self.store.get_experiment(order["experiment_id"])
                cash = Decimal(str(exp["cash"]))
                if take * exec_price + fee > cash:
                    take = (cash - fee) / exec_price if exec_price > 0 else Decimal("0")
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
                price=exec_price,
                qty=take,
                fee=fee,
                liquidity=liquidity,
            )
            fills.append((exec_price, take))
            remaining -= take
            if remaining <= 0:
                break

        return fills

    async def _fill_marketable_limit(
        self,
        order: dict[str, Any],
        experiment: dict[str, Any],
        limit_price: Decimal,
        remaining: Decimal,
    ) -> list[tuple[Decimal, Decimal]]:
        """On submit: if limit crosses BBO, walk depth as taker up to limit."""
        side = order["side"]
        action = order["action"]
        ticker = order["ticker"]

        if action == "buy":
            levels = await get_ask_levels_for_buy(self.redis, ticker, side)
            best = levels[0][0] if levels else None
            if best is None or best > limit_price:
                return []
        else:
            levels = await get_bid_levels_for_sell(self.redis, ticker, side)
            best = levels[0][0] if levels else None
            if best is None or best < limit_price:
                return []

        return await self._walk_book(
            order,
            action,
            side,
            ticker,
            remaining,
            limit_price=limit_price,
            liquidity="taker",
        )

    async def _try_limit_fill(
        self,
        order: dict[str, Any],
        experiment: dict[str, Any],
        limit_price: Decimal,
        remaining: Decimal,
    ) -> bool:
        """Resting GTC poll: when crossed, fill at limit_price as maker."""
        if remaining <= 0:
            return False

        side = order["side"]
        action = order["action"]
        ticker = order["ticker"]

        if action == "buy":
            levels = await get_ask_levels_for_buy(self.redis, ticker, side)
            best = levels[0][0] if levels else None
            if best is None or best > limit_price:
                return False
        else:
            levels = await get_bid_levels_for_sell(self.redis, ticker, side)
            best = levels[0][0] if levels else None
            if best is None or best < limit_price:
                return False

        fills = await self._walk_book(
            order,
            action,
            side,
            ticker,
            remaining,
            limit_price=limit_price,
            liquidity="maker",
            fill_price_override=limit_price,
        )
        return bool(fills)

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
