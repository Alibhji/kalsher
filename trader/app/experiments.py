from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException

from trader.app.store import TradingStore
from trader.app.tags import merge_tags_into_params, normalize_tags, tags_from_params


class ExperimentService:
    def __init__(self, store: TradingStore) -> None:
        self.store = store

    async def create(self, name: str, mode: str, initial_capital: Decimal, strategy: str | None, params: dict, tags: list[str] | None = None):
        existing = await self.store.list_experiments(include_archived=True)
        if any(e["name"] == name for e in existing):
            raise HTTPException(409, "experiment name already exists")
        merged = merge_tags_into_params(params, tags or [])
        return await self.store.create_experiment(name, mode, initial_capital, strategy, merged)

    async def get(self, exp_id: UUID):
        exp = await self.store.get_experiment(exp_id)
        if not exp:
            raise HTTPException(404, "experiment not found")
        return exp

    async def list_all(self, include_archived: bool = False, tag: str | None = None):
        return await self.store.list_experiments(include_archived=include_archived, tag=tag)

    async def patch(self, exp_id: UUID, **fields):
        exp = await self.get(exp_id)
        if exp["archived_at"]:
            raise HTTPException(409, "experiment archived")
        if "tags" in fields and fields["tags"] is not None:
            params = exp.get("params")
            if isinstance(params, str):
                import json

                try:
                    params = json.loads(params)
                except json.JSONDecodeError:
                    params = {}
            fields["params"] = merge_tags_into_params(params if isinstance(params, dict) else {}, fields.pop("tags"))
        if "name" in fields and fields["name"] is not None:
            name = fields["name"].strip()
            if not name:
                raise HTTPException(400, "name cannot be empty")
            existing = await self.store.list_experiments(include_archived=True)
            if any(e["name"] == name and str(e["id"]) != str(exp_id) for e in existing):
                raise HTTPException(409, "experiment name already exists")
            fields["name"] = name
        return await self.store.patch_experiment(exp_id, **fields)

    async def adjust_capital(self, exp_id: UUID, set_val: Decimal | None, delta: Decimal | None):
        exp = await self.get(exp_id)
        if exp["mode"] == "live":
            raise HTTPException(409, "cannot adjust capital on live experiment")
        cash = Decimal(str(exp["cash"]))
        new_cash = set_val if set_val is not None else cash + (delta or Decimal("0"))
        if new_cash < 0:
            raise HTTPException(400, "cash cannot be negative")
        return await self.store.adjust_capital(exp_id, new_cash)

    async def reset(self, exp_id: UUID):
        exp = await self.get(exp_id)
        if exp["mode"] == "live":
            raise HTTPException(409, "refusing to reset a live experiment")
        await self.store.reset_experiment(exp_id)
        return await self.get(exp_id)

    async def archive(self, exp_id: UUID):
        exp = await self.get(exp_id)
        positions = await self.store.list_positions(exp_id)
        if exp["mode"] == "live" and positions:
            raise HTTPException(409, "close live positions before archive")
        row = await self.store.archive_experiment(exp_id)
        if not row:
            raise HTTPException(404, "experiment not found")
        return row

    async def delete_permanent(self, exp_id: UUID):
        exp = await self.get(exp_id)
        if exp["mode"] == "live":
            raise HTTPException(409, "cannot permanently delete a live experiment")
        positions = await self.store.list_positions(exp_id)
        if positions:
            raise HTTPException(409, "close open positions before deleting")
        open_orders = await self.store.list_open_orders(exp_id)
        if open_orders:
            raise HTTPException(409, "cancel open orders before deleting")
        ok = await self.store.delete_experiment(exp_id)
        if not ok:
            raise HTTPException(404, "experiment not found")
        return exp
