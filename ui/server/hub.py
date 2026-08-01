from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from common.liquidity import market_has_liquidity
from common.trade_flow import trade_signed_usd

from ui.server.markets import _derived_no_cents, _is_live, _kalshi_url, _event_kalshi_url, _parse_decimal, _price_cents


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass
class MarketState:
    row: dict[str, Any]
    seq: int = 0
    dirty: bool = False


class MarketHub:
    def __init__(self, *, web_base: str = "https://kalshi.com") -> None:
        self.web_base = web_base
        self._markets: dict[str, MarketState] = {}
        self._seq = 0

    def seed_rows(self, rows: list[dict[str, Any]]) -> None:
        self._markets.clear()
        for row in rows:
            self._markets[row["ticker"]] = MarketState(row=dict(row), seq=0, dirty=False)

    def all_rows(self) -> list[dict[str, Any]]:
        return [state.row for state in self._markets.values()]

    def get_row(self, ticker: str) -> dict[str, Any] | None:
        state = self._markets.get(ticker)
        return state.row if state else None

    def dirty_tickers(self) -> set[str]:
        return {t for t, s in self._markets.items() if s.dirty}

    def mark_clean(self, tickers: set[str]) -> None:
        for ticker in tickers:
            state = self._markets.get(ticker)
            if state:
                state.dirty = False

    def remove(self, ticker: str) -> None:
        self._markets.pop(ticker, None)

    def upsert_meta_row(self, row: dict[str, Any]) -> None:
        ticker = row["ticker"]
        existing = self._markets.get(ticker)
        if existing:
            merged = dict(existing.row)
            for key, value in row.items():
                if value is not None:
                    merged[key] = value
            existing.row = merged
        else:
            self._markets[ticker] = MarketState(row=dict(row))
        self._touch(ticker)

    def apply_tick(self, ticker: str, payload: dict[str, Any]) -> bool:
        state = self._markets.get(ticker)
        if not state:
            return False
        row = dict(state.row)
        yes_bid = _parse_decimal(payload.get("yes_bid"))
        yes_ask = _parse_decimal(payload.get("yes_ask"))
        if yes_bid is not None:
            row["yes_bid_cents"] = _price_cents(yes_bid)
        if yes_ask is not None:
            row["yes_ask_cents"] = _price_cents(yes_ask)
        no_bid, no_ask = _derived_no_cents(row.get("yes_bid_cents"), row.get("yes_ask_cents"))
        row["no_bid_cents"] = no_bid
        row["no_ask_cents"] = no_ask
        volume = _parse_decimal(payload.get("volume"))
        if volume is not None:
            row["volume"] = str(volume)
        oi = _parse_decimal(payload.get("open_interest"))
        if oi is not None:
            row["open_interest"] = str(oi)
        row["has_quotes"] = row.get("yes_bid_cents") is not None or row.get("yes_ask_cents") is not None
        vol_num = float(volume) if volume is not None else (float(row["volume"]) if row.get("volume") else None)
        row["has_liquidity"] = market_has_liquidity(
            row.get("yes_bid_cents"),
            row.get("yes_ask_cents"),
            volume_usd=vol_num,
        )
        now = datetime.now(timezone.utc)
        close = _parse_dt(row.get("close_time"))
        if close:
            row["seconds_to_close"] = max(0, int((close - now).total_seconds()))
        row["is_live"] = _is_live(
            {
                "status": row.get("status"),
                "open_time": _parse_dt(row.get("open_time")),
                "close_time": close,
            },
            now,
        )
        state.row = row
        self._touch(ticker)
        return True

    def apply_trade(self, ticker: str, payload: dict[str, Any], *, frame_ts: Any = None) -> dict[str, Any] | None:
        if self._markets.get(ticker) is None:
            return None
        signed = trade_signed_usd(payload)
        if signed is None:
            return None
        price = _parse_decimal(payload.get("price"))
        count = _parse_decimal(payload.get("count"))
        ts = _parse_dt(frame_ts) or datetime.now(timezone.utc)
        trade_id = payload.get("trade_id")
        return {
            "ticker": ticker,
            "trade_id": str(trade_id) if trade_id is not None else None,
            "taker_side": payload.get("taker_side"),
            "signed_usd": round(signed, 2),
            "price_cents": _price_cents(price),
            "count": float(count) if count is not None else None,
            "ts": ts.isoformat(),
        }

    def apply_market_meta(self, ticker: str, payload: dict[str, Any]) -> bool:
        market = payload.get("market") or {}
        event = payload.get("event") or {}
        series = payload.get("series") or {}
        state = self._markets.get(ticker)
        row: dict[str, Any] = dict(state.row) if state else {"ticker": ticker}
        row["title"] = market.get("title") or row.get("title")
        row["event_ticker"] = market.get("event_ticker") or event.get("event_ticker") or row.get("event_ticker")
        row["event_title"] = event.get("title") or row.get("event_title")
        row["series_ticker"] = market.get("series_ticker") or event.get("series_ticker") or row.get("series_ticker")
        row["series_title"] = series.get("title") or row.get("series_title")
        row["category"] = event.get("category") or row.get("category")
        row["status"] = market.get("status") or row.get("status")
        for key in ("open_time", "close_time"):
            if market.get(key):
                row[key] = market[key]
        if market.get("floor_strike") is not None:
            row["floor_strike"] = float(market["floor_strike"])
        if market.get("cap_strike") is not None:
            row["cap_strike"] = float(market["cap_strike"])
        row["strike_type"] = market.get("strike_type") or row.get("strike_type")
        vol = _parse_decimal(market.get("volume_fp"))
        if vol is not None and not row.get("volume"):
            row["volume"] = str(vol)
        oi = _parse_decimal(market.get("open_interest_fp"))
        if oi is not None and not row.get("open_interest"):
            row["open_interest"] = str(oi)
        row["kalshi_url"] = _kalshi_url(
            self.web_base,
            ticker,
            event_ticker=row.get("event_ticker"),
            series_ticker=row.get("series_ticker"),
            series_title=row.get("series_title"),
            event_title=row.get("event_title"),
        )
        row["event_kalshi_url"] = _event_kalshi_url(
            self.web_base,
            event_ticker=row.get("event_ticker"),
            series_ticker=row.get("series_ticker"),
            series_title=row.get("series_title"),
            event_title=row.get("event_title"),
        )
        now = datetime.now(timezone.utc)
        close = _parse_dt(row.get("close_time"))
        if close:
            row["seconds_to_close"] = max(0, int((close - now).total_seconds()))
        row["is_live"] = _is_live(
            {
                "status": row.get("status"),
                "open_time": _parse_dt(row.get("open_time")),
                "close_time": close,
            },
            now,
        )
        if state:
            state.row = row
        else:
            self._markets[ticker] = MarketState(row=row)
        self._touch(ticker)
        return True

    def quote_delta(self, ticker: str) -> dict[str, Any] | None:
        state = self._markets.get(ticker)
        if not state:
            return None
        row = state.row
        return {
            "ticker": ticker,
            "yes_bid_cents": row.get("yes_bid_cents"),
            "yes_ask_cents": row.get("yes_ask_cents"),
            "no_bid_cents": row.get("no_bid_cents"),
            "no_ask_cents": row.get("no_ask_cents"),
            "volume": row.get("volume"),
            "open_interest": row.get("open_interest"),
            "has_quotes": row.get("has_quotes"),
            "has_liquidity": row.get("has_liquidity"),
            "is_live": row.get("is_live"),
            "seconds_to_close": row.get("seconds_to_close"),
            "seq": state.seq,
        }

    def _touch(self, ticker: str) -> None:
        state = self._markets[ticker]
        self._seq += 1
        state.seq = self._seq
        state.dirty = True
