from __future__ import annotations

import asyncio
import time
from typing import Iterable

from common.logging import get_logger
from common.models import NormalizedEvent
from fetcher.app.sinks.base import Sink

log = get_logger(__name__)


class BatchingSink:
    def __init__(
        self,
        sinks: Iterable[Sink],
        batch_size: int = 1000,
        flush_ms: float = 100.0,
        queue_size: int = 50_000,
    ) -> None:
        self.sinks = list(sinks)
        self.batch_size = batch_size
        self.flush_ms = flush_ms
        self._queue: asyncio.Queue[NormalizedEvent] = asyncio.Queue(maxsize=queue_size)
        self._running = False
        self.events_written = 0
        self.last_flush_ms = 0.0
        self.dropped = 0
        self.flush_failures = 0
        self._last_drop_log = 0.0

    async def connect(self) -> None:
        for s in self.sinks:
            await s.connect()

    def stop(self) -> None:
        """Let run() drain the queue and exit."""
        self._running = False

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
                self.dropped += 1
                now = time.monotonic()
                if now - self._last_drop_log > 5.0:
                    self._last_drop_log = now
                    log.error("sink_queue_full", dropped=self.dropped, depth=self._queue.qsize())

    async def _flush(self, batch: list[NormalizedEvent]) -> None:
        start = time.monotonic()
        for sink in self.sinks:
            await self._write_with_retry(sink, batch)
        self.events_written += len(batch)
        self.last_flush_ms = (time.monotonic() - start) * 1000
        log.debug("sink_flushed", count=len(batch), ms=self.last_flush_ms)

    async def _write_with_retry(self, sink: Sink, batch: list[NormalizedEvent]) -> None:
        """Retry one sink in isolation so a transient blip cannot kill ingestion,
        and a sink that already succeeded is never rewritten."""
        for attempt in range(3):
            try:
                await sink.write(batch)
                return
            except Exception as exc:
                log.error(
                    "sink_write_failed",
                    sink=type(sink).__name__,
                    error=str(exc),
                    count=len(batch),
                    attempt=attempt,
                )
                await asyncio.sleep(0.2 * (attempt + 1))
        self.flush_failures += 1
        self.dropped += len(batch)

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()
