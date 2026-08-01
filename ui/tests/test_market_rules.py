from common.market_rules import build_market_rules_markdown


def test_build_market_rules_markdown_crypto_strike() -> None:
    md = build_market_rules_markdown(
        {
            "yes_sub_title": "Target Price: $575.88",
            "floor_strike": "575.88",
            "rules_primary": (
                "Resolves Yes if the simple average of the sixty seconds of CF Benchmarks' "
                "BNBUSD_RTI before 6:30 PM EDT on Aug 1, 2026 is at least 575.88."
            ),
            "rules_secondary": "Not all cryptocurrency price data is the same.",
        },
        series={
            "settlement_sources": [{"name": "CF Benchmarks", "url": "https://www.cfbenchmarks.com/"}],
            "contract_terms_url": "https://assets.kalshi.com/contract_terms/BNB.pdf",
        },
    )
    assert "## Market Rules" in md
    assert "Target Price: $575.88" in md
    assert "Resolves Yes if the simple average" in md
    assert "Outcome verified from CF Benchmarks." in md
    assert "Not all cryptocurrency price data is the same." in md
    assert "[Full contract terms]" in md


def test_build_market_rules_markdown_with_outcome() -> None:
    md = build_market_rules_markdown(
        {
            "yes_sub_title": "Target Price: $575.88",
            "expiration_value": "575.92",
            "rules_primary": "Resolves Yes if ...",
        },
        series={"settlement_sources": [{"name": "CF Benchmarks"}]},
    )
    assert "**The outcome is** 575.92" in md
