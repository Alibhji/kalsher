from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def _fmt_strike(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    text = f"{dec:,.2f}" if dec % 1 else f"{dec:,.0f}"
    return f"${text}"


def build_market_rules_markdown(
    market: dict[str, Any] | None,
    *,
    series: dict[str, Any] | None = None,
) -> str:
    """Render Kalshi contract terms as markdown for the UI."""
    market = market or {}
    series = series or {}

    lines: list[str] = ["## Market Rules", ""]

    yes_sub = (market.get("yes_sub_title") or "").strip()
    if yes_sub:
        lines.append(yes_sub if yes_sub.lower().startswith("target") else f"**Target Price:** {yes_sub}")
    else:
        strike = _fmt_strike(market.get("floor_strike"))
        if strike:
            lines.append(f"**Target Price:** {strike}")
        elif market.get("cap_strike") is not None:
            cap = _fmt_strike(market.get("cap_strike"))
            if cap:
                lines.append(f"**Cap Strike:** {cap}")

    expiration_value = market.get("expiration_value")
    if expiration_value not in (None, ""):
        lines.extend(["", f"**The outcome is** {expiration_value}"])

    result = market.get("result")
    if result not in (None, "") and not expiration_value:
        lines.extend(["", f"**Result:** {result}"])

    rules_primary = (market.get("rules_primary") or "").strip()
    if rules_primary:
        lines.extend(["", rules_primary])

    sources = series.get("settlement_sources") or []
    if isinstance(sources, list) and sources:
        names = [str(s.get("name")).strip() for s in sources if isinstance(s, dict) and s.get("name")]
        if names:
            lines.extend(["", f"Outcome verified from {', '.join(names)}."])

    rules_secondary = (market.get("rules_secondary") or "").strip()
    if rules_secondary:
        lines.extend(["", rules_secondary])

    contract_terms_url = (series.get("contract_terms_url") or "").strip()
    if contract_terms_url:
        lines.extend(["", f"[Full contract terms]({contract_terms_url})"])

    contract_url = (series.get("contract_url") or "").strip()
    if contract_url and contract_url != contract_terms_url:
        lines.extend(["", f"[Original contract filing]({contract_url})"])

    return "\n".join(lines).strip()
