from __future__ import annotations

import time
from typing import Any

import msgspec

from common.models import NormalizedEvent
from storage.clients.redis_store import RedisStore


class FanoutSink:
    """Unbatched publish for latency-sensitive readers (the UI gateway).

    Sits beside BatchingSink, not behind it: the batcher trades up to
    sink_flush_ms for write throughput, which a live terminal cannot afford.
    Errors are counted rather than raised so a stalled subscriber can never
    reach back into the WS read loop.
    """

    CHANNEL = "kalshi:live"

    def __init__(self, store: RedisStore) -> None:
        self._store = store
        self._encoder = msgspec.msgpack.Encoder(enc_hook=str)
        self.published = 0
        self.drops = 0

    async def publish(self, events: list[NormalizedEvent]) -> None:
        if not events:
            return
        try:
            pipe = self._store.client.pipeline(transaction=False)
            for ev in events:
                pipe.publish(self.CHANNEL, self._encoder.encode(self._frame(ev)))
            await pipe.execute()
            self.published += len(events)
        except Exception:
            self.drops += len(events)

    def _frame(self, ev: NormalizedEvent) -> dict[str, Any]:
        # `raw` is the untouched exchange body; it duplicates the parsed fields
        # and, for book snapshots, the entire ladder. Subscribers never need it.
        return {
            "kind": ev.kind.value,
            "ticker": ev.ticker,
            "ts": ev.ts,
            "source_ts": ev.source_ts,
            "t_pub": time.time(),
            "payload": {k: v for k, v in ev.payload.items() if k != "raw"},
        }
