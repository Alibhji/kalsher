from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# Kalshi tapered_deci_cent books use 0.0010 (= 0.1¢) ticks below 10¢.
MIN_TICK = Decimal("0.001")
MAX_PRICE = Decimal("0.999")


def quote_cents_display(value: Decimal | None) -> float | None:
    """Cents for the UI — one decimal place so 0.0010 dollars → 0.1¢ not 0¢."""
    if value is None:
        return None
    return float((value * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def derived_no_dollars(
    yes_bid: Decimal | None,
    yes_ask: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    no_bid = (Decimal("1") - yes_ask) if yes_ask is not None else None
    no_ask = (Decimal("1") - yes_bid) if yes_bid is not None else None
    return no_bid, no_ask


def quote_row_from_yes_dollars(
    yes_bid: Decimal | None,
    yes_ask: Decimal | None,
) -> dict[str, float | None]:
    no_bid, no_ask = derived_no_dollars(yes_bid, yes_ask)
    return {
        "yes_bid_cents": quote_cents_display(yes_bid),
        "yes_ask_cents": quote_cents_display(yes_ask),
        "no_bid_cents": quote_cents_display(no_bid),
        "no_ask_cents": quote_cents_display(no_ask),
    }
