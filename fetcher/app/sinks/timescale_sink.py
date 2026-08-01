from __future__ import annotations

from common.models import EventKind, NormalizedEvent, MarketMeta
from storage.clients.timescale_store import TimescaleStore


class TimescaleSink:
    def __init__(self, store: TimescaleStore) -> None:
        self.store = store

    async def connect(self) -> None:
        await self.store.connect()

    async def close(self) -> None:
        await self.store.close()

    async def write(self, events: list[NormalizedEvent]) -> None:
        meta_events = [e for e in events if e.kind == EventKind.MARKET_META]
        for ev in meta_events:
            m = ev.payload.get("market", ev.payload)
            meta = MarketMeta(
                ticker=ev.ticker,
                event_ticker=m.get("event_ticker", ""),
                series_ticker=m.get("series_ticker"),
                title=m.get("title"),
                yes_sub_title=m.get("yes_sub_title"),
                no_sub_title=m.get("no_sub_title"),
                status=m.get("status"),
                open_time=None,
                close_time=None,
                expected_expiration_time=None,
                latest_expiration_time=None,
                category=ev.payload.get("event", {}).get("category") if isinstance(ev.payload.get("event"), dict) else None,
                raw=ev.payload,
            )
            await self.store.upsert_market(meta)
        await self.store.write_events(events)
