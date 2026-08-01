from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import asyncpg

from common.liquidity import market_has_liquidity
from common.models import EventKind, NormalizedEvent, MarketMeta


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


class TimescaleStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=30)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    @property
    def pool(self) -> asyncpg.Pool:
        assert self._pool is not None
        return self._pool

    async def upsert_market(self, meta: MarketMeta) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO markets (
                    ticker, event_ticker, series_ticker, title, yes_sub_title, no_sub_title,
                    status, category, open_time, close_time, expected_expiration_time,
                    latest_expiration_time, metadata, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    status=EXCLUDED.status,
                    category=EXCLUDED.category,
                    close_time=EXCLUDED.close_time,
                    metadata=EXCLUDED.metadata,
                    updated_at=NOW()
                """,
                meta.ticker,
                meta.event_ticker,
                meta.series_ticker,
                meta.title,
                meta.yes_sub_title,
                meta.no_sub_title,
                meta.status,
                meta.category,
                meta.open_time,
                meta.close_time,
                meta.expected_expiration_time,
                meta.latest_expiration_time,
                json.dumps(meta.raw, default=str),
            )

    async def mark_market_closed(self, ticker: str, snapshot: dict[str, str] | None = None) -> None:
        had_liquidity, close_volume, bid_cents, ask_cents = await self._liquidity_at_close(
            ticker, snapshot
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE markets
                SET status = 'closed',
                    close_time = COALESCE(close_time, NOW()),
                    had_liquidity = $2,
                    close_volume = $3,
                    close_yes_bid_cents = $4,
                    close_yes_ask_cents = $5,
                    updated_at = NOW()
                WHERE ticker = $1
                """,
                ticker,
                had_liquidity,
                close_volume,
                bid_cents,
                ask_cents,
            )

    async def _liquidity_at_close(
        self,
        ticker: str,
        snapshot: dict[str, str] | None,
    ) -> tuple[bool, Decimal | None, int | None, int | None]:
        volume = _dec(snapshot.get("volume")) if snapshot else None
        yes_bid = _dec(snapshot.get("yes_bid")) if snapshot else None
        yes_ask = _dec(snapshot.get("yes_ask")) if snapshot else None

        if volume is None and yes_bid is None and yes_ask is None:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT yes_bid, yes_ask, volume
                    FROM ticks
                    WHERE ticker = $1
                    ORDER BY ts DESC
                    LIMIT 1
                    """,
                    ticker,
                )
            if row:
                volume = row["volume"]
                yes_bid = row["yes_bid"]
                yes_ask = row["yes_ask"]

        bid_cents = int((yes_bid * 100).quantize(Decimal("1"))) if yes_bid is not None else None
        ask_cents = int((yes_ask * 100).quantize(Decimal("1"))) if yes_ask is not None else None
        liquid = market_has_liquidity(bid_cents, ask_cents, volume_usd=volume)
        return liquid, volume, bid_cents, ask_cents

    async def write_events(self, events: list[NormalizedEvent]) -> None:
        ticks, trades, book, underlying, lifecycle = [], [], [], [], []
        for ev in events:
            if ev.kind == EventKind.MARKET_META:
                continue
            rows = self._rows_for(ev)
            if not rows:
                continue
            bucket = {
                EventKind.TICK: ticks,
                EventKind.TRADE: trades,
                EventKind.BOOK_DELTA: book,
                EventKind.BOOK_SNAPSHOT: book,
                EventKind.UNDERLYING: underlying,
                EventKind.LIFECYCLE: lifecycle,
            }[ev.kind]
            bucket.extend(rows)

        async with self.pool.acquire() as conn:
            if ticks:
                await conn.copy_records_to_table(
                    "ticks",
                    records=ticks,
                    columns=["ts", "ticker", "yes_bid", "yes_ask", "no_bid", "no_ask", "last_price", "volume", "open_interest", "payload"],
                )
            if trades:
                await conn.copy_records_to_table(
                    "trades",
                    records=trades,
                    columns=["ts", "ticker", "price", "count", "taker_side", "trade_id", "payload"],
                )
            if book:
                await conn.copy_records_to_table(
                    "book_deltas",
                    records=book,
                    columns=["ts", "ticker", "side", "price", "delta", "seq", "payload"],
                )
            if underlying:
                await conn.copy_records_to_table(
                    "underlying_prices",
                    records=underlying,
                    columns=["ts", "source", "symbol", "price", "payload"],
                )
            if lifecycle:
                await conn.copy_records_to_table(
                    "lifecycle_events",
                    records=lifecycle,
                    columns=["ts", "ticker", "event_type", "payload"],
                )

    def _rows_for(self, ev: NormalizedEvent) -> list[tuple]:
        p = ev.payload
        if ev.kind == EventKind.TICK:
            return [(
                ev.ts, ev.ticker,
                _dec(p.get("yes_bid")), _dec(p.get("yes_ask")),
                _dec(p.get("no_bid")), _dec(p.get("no_ask")),
                _dec(p.get("last_price")), _dec(p.get("volume")),
                _dec(p.get("open_interest")), json.dumps(p, default=str),
            )]
        if ev.kind == EventKind.TRADE:
            return [(
                ev.ts, ev.ticker, _dec(p.get("price")), _dec(p.get("count")),
                p.get("taker_side"), p.get("trade_id"), json.dumps(p, default=str),
            )]
        if ev.kind == EventKind.BOOK_SNAPSHOT:
            side = p.get("side", "yes")
            return [
                (ev.ts, ev.ticker, side, _dec(level.get("price")), _dec(level.get("size")), p.get("seq"), json.dumps(p, default=str))
                for level in p.get("levels", [])
            ]
        if ev.kind == EventKind.BOOK_DELTA:
            return [(ev.ts, ev.ticker, p.get("side"), _dec(p.get("price")), _dec(p.get("delta")), p.get("seq"), json.dumps(p, default=str))]
        if ev.kind == EventKind.UNDERLYING:
            return [(ev.ts, p.get("source", "unknown"), p.get("symbol", ev.ticker), _dec(p.get("price")), json.dumps(p, default=str))]
        if ev.kind == EventKind.LIFECYCLE:
            return [(ev.ts, ev.ticker, p.get("event_type", "unknown"), json.dumps(p, default=str))]
        return []
