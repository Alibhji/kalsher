from __future__ import annotations

from typing import Protocol

from common.models import NormalizedEvent


class Sink(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def write(self, events: list[NormalizedEvent]) -> None: ...
