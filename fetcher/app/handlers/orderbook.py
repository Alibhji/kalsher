from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from common.models import EventKind, NormalizedEvent, parse_decimal, parse_ts


class OrderbookState:
    def __init__(self) -> None:
        self.last_seq: dict[str, int] = {}
        self.seq_gaps = 0

    def handle(self, msg: dict[str, Any]) -> list[NormalizedEvent]:
        msg_type = msg.get("type")
        body = msg.get("msg") or {}
        ticker = body.get("market_ticker")
        if not ticker:
            return []

        if msg_type == "orderbook_snapshot":
            return self._snapshot(ticker, body)
        if msg_type == "orderbook_delta":
            return self._delta(ticker, body)
        return []

    def _snapshot(self, ticker: str, body: dict[str, Any]) -> list[NormalizedEvent]:
        seq = body.get("seq")
        if seq is not None:
            self.last_seq[ticker] = int(seq)
        now = datetime.now(timezone.utc)
        events: list[NormalizedEvent] = []
        for side in ("yes", "no"):
            levels = []
            raw_levels = body.get(side) or body.get(f"{side}_dollars") or []
            if isinstance(raw_levels, list):
                for item in raw_levels:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        levels.append({"price": parse_decimal(item[0]), "size": parse_decimal(item[1])})
            events.append(
                NormalizedEvent(
                    kind=EventKind.BOOK_SNAPSHOT,
                    ticker=ticker,
                    ts=now,
                    source_ts=parse_ts(body.get("ts")),
                    payload={"side": side, "levels": levels, "seq": seq, "raw": body},
                )
            )
        return events

    def _delta(self, ticker: str, body: dict[str, Any]) -> list[NormalizedEvent]:
        seq = body.get("seq")
        if seq is not None:
            seq = int(seq)
            prev = self.last_seq.get(ticker)
            if prev is not None and seq != prev + 1:
                self.seq_gaps += 1
                return [
                    NormalizedEvent(
                        kind=EventKind.LIFECYCLE,
                        ticker=ticker,
                        ts=datetime.now(timezone.utc),
                        payload={"event_type": "book_seq_gap", "prev_seq": prev, "seq": seq},
                    )
                ]
            self.last_seq[ticker] = seq

        side = body.get("side", "yes")
        price = parse_decimal(body.get("price_dollars") or body.get("price"))
        delta = parse_decimal(body.get("delta_fp") or body.get("delta"))
        return [
            NormalizedEvent(
                kind=EventKind.BOOK_DELTA,
                ticker=ticker,
                ts=datetime.now(timezone.utc),
                source_ts=parse_ts(body.get("ts")),
                payload={"side": side, "price": price, "delta": delta, "seq": seq, "raw": body},
            )
        ]
