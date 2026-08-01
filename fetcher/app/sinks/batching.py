from __future__ import annotations

import asyncio
import time
from typing import Iterable

from common.logging import get_logger
from common.models import NormalizedEvent
from fetcher.app.sinks.base import Sink

log = get_logger(__name__)


class BatchingSink:
    def __init__(self, sinks: Iterable[Sink], batch_size: int = 1000, flush_ms: float = 100.0) -> None:
        self.sinks = list(sinks)
        self.batch_size = batch_size
        self.flush_ms = flush_ms
        self._queue: asyncio.Queue[NormalizedEvent] = asyncio.Queue(maxsize=50_000)
        self._running = False
        self.events_written = 0
        self.last_flush_ms = 0.0

    async def connect(self) -> None:
        for s in self.sinks:
            await s.connect()

    async def close(self) -> None:
        self._running = False
        for s in self.sinks:
            await s.close()

    async def run(self) -> None:
        self._running = True
        log.debug("sink_runner_started")
        batch: list[NormalizedEvent] = []
        last_flush = time.monotonic()
        while self._running or not self._queue.empty():
            timeout = max(0.01, self.flush_ms / 1000 - (time.monotonic() - last_flush))
            try:
                if self._queue.qsize() > 0:
                    batch.append(self._queue.get_nowait())
                else:
                    batch.append(await asyncio.wait_for(self._queue.get(), timeout=timeout))
            except asyncio.TimeoutError:
                pass
            now = time.monotonic()
            if batch and (len(batch) >= self.batch_size or (now - last_flush) * 1000 >= self.flush_ms):
                await self._flush(batch)
                batch = []
                last_flush = now
        if batch:
            await self._flush(batch)

    async def enqueue(self, events: list[NormalizedEvent]) -> None:
        for ev in events:
            try:
                self._queue.put_nowait(ev)
            except asyncio.QueueFull:
                pass

    async def _flush(self, batch: list[NormalizedEvent]) -> None:
        start = time.monotonic()
        try:
            for s in self.sinks:
                await s.write(batch)
            self.events_written += len(batch)
            self.last_flush_ms = (time.monotonic() - start) * 1000
            log.debug("sink_flushed", count=len(batch), ms=self.last_flush_ms)
        except Exception as exc:
            log.error("sink_flush_failed", error=str(exc), count=len(batch))
            raise

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()
