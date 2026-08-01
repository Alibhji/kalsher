from __future__ import annotations

from common.models import NormalizedEvent
from storage.clients.redis_store import RedisStore


class RedisSink:
    def __init__(self, store: RedisStore) -> None:
        self.store = store

    async def connect(self) -> None:
        await self.store.connect()

    async def close(self) -> None:
        await self.store.close()

    async def write(self, events: list[NormalizedEvent]) -> None:
        await self.store.write_events(events)
