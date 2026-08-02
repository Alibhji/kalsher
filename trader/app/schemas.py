from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ExperimentCreate(BaseModel):
    name: str
    mode: Literal["paper", "live"] = "paper"
    initial_capital: Decimal = Field(default=Decimal("10000"))
    strategy: str | None = None
    params: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class ExperimentPatch(BaseModel):
    name: str | None = None
    status: str | None = None
    strategy: str | None = None
    params: dict | None = None
    tags: list[str] | None = None


class CapitalAdjust(BaseModel):
    set: Decimal | None = None
    delta: Decimal | None = None

    @model_validator(mode="after")
    def one_of(self) -> "CapitalAdjust":
        if (self.set is None) == (self.delta is None):
            raise ValueError("provide exactly one of set or delta")
        return self


class OrderRequest(BaseModel):
    ticker: str
    side: Literal["yes", "no"]
    action: Literal["buy", "sell"]
    type: Literal["market", "limit"]
    qty: Decimal
    limit_price: Decimal | None = None
    client_order_id: str | None = None

    @model_validator(mode="after")
    def validate_limit(self) -> "OrderRequest":
        if self.type == "limit" and self.limit_price is None:
            raise ValueError("limit_price required for limit orders")
        if self.type == "market" and self.limit_price is not None:
            raise ValueError("limit_price not allowed for market orders")
        if self.qty <= 0:
            raise ValueError("qty must be positive")
        return self


class CloseAllRequest(BaseModel):
    ticker: str | None = None


class ExperimentOut(BaseModel):
    id: UUID
    name: str
    mode: str
    initial_capital: str
    cash: str
    status: str
    strategy: str | None = None
    params: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    created_at: str
    archived_at: str | None = None


class ExperimentForEventOut(BaseModel):
    id: UUID
    name: str
    mode: str
    fill_count: int
    trade_count: int
    net_pnl: str
    last_activity: str | None = None


class ArchiveEventPnlOut(BaseModel):
    event_ticker: str
    trip_count: int
    trade_count: int
    net_pnl: str


class PositionOut(BaseModel):
    ticker: str
    side: str
    qty: str
    avg_price: str
    realized_pnl: str
    fees_paid: str
    cost_basis: str | None = None
    mark_price: str | None = None
    unrealized_pnl: str | None = None


class ProfileOut(BaseModel):
    experiment_id: UUID
    name: str
    mode: str
    cash: str
    initial_capital: str
    realized_pnl: str
    unrealized_pnl: str
    fees_paid: str
    equity: str
    drawdown: str
    positions: list[PositionOut] = Field(default_factory=list)
    available_funds: str | None = None
    portfolio_value: str | None = None
    total_pnl: str | None = None
    pnl_pct: str | None = None
    capital_invested: str | None = None
    live_trading_enabled: bool = False


class TradingConfigOut(BaseModel):
    live_trading_enabled: bool
    kalshi_configured: bool


class FillOut(BaseModel):
    id: UUID
    ts: str
    ticker: str
    side: str
    action: str
    price: str
    qty: str
    fee: str
    cost: str
    cash_impact: str
    trade_pnl: str | None = None
    trade_pnl_pct: str | None = None


class RoundTripOut(BaseModel):
    id: UUID
    ticker: str
    side: str
    qty: str
    entry_ts: str
    entry_price: str
    exit_ts: str | None = None
    exit_price: str | None = None
    cost_basis: str
    gross_pnl: str | None = None
    fees: str
    net_pnl: str | None = None
    pnl_pct: str | None = None
    exit_kind: str | None = None
    action_at_entry: str


class OrderOut(BaseModel):
    id: UUID
    experiment_id: UUID
    client_order_id: str | None = None
    ticker: str
    side: str
    action: str
    type: str
    limit_price: str | None = None
    qty: str
    filled_qty: str
    status: str
    mode: str
    kalshi_order_id: str | None = None
    reason: str | None = None
    created_at: str
    updated_at: str


class StatsOut(BaseModel):
    experiment_id: UUID
    name: str
    mode: str
    closed_trades: int
    wins: int
    net_pnl: str
    max_drawdown: str
    win_rate: str | None = None
    profit_factor: str | None = None


class PeriodSummaryOut(BaseModel):
    start: str | None = None
    end: str
    realized_pnl: str
    pnl_pct: str | None = None
    closed_trades: int
    wins: int
    fill_count: int
    win_rate: str | None = None
    source: str
    baseline: str
    capital_invested: str | None = None
    net_deposits: str | None = None


class PnlPointOut(BaseModel):
    ts: str
    cumulative_pnl: str
    equity: str | None = None


class PnlSeriesOut(BaseModel):
    points: list[PnlPointOut]
    source: str
