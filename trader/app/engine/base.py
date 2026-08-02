from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any
from uuid import UUID


class ExecutionEngine(ABC):
    @abstractmethod
    async def submit_order(self, order: dict[str, Any], experiment: dict[str, Any]) -> dict[str, Any]:
        ...

    @abstractmethod
    async def cancel_order(self, order: dict[str, Any]) -> dict[str, Any]:
        ...
