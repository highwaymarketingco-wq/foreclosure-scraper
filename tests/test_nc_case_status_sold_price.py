"""Pin the sold-price extraction added to enrichment_nc_case_status.

When the Tyler portal's case-detail page shows an "Order Confirming
Sale" / "Report of Sale" docket entry with the hammer price inline,
extract it and tag the listing for promotion into the
foreclosure_sold_comps pool.

Synthetic-text tests since the live Tyler portal is JS-rendered and
not reachable from local test runs.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_nc_case_status import (
    SOLD_PRICE_PATTERNS,
    _extract_sold_price,
)


# ---- pattern coverage ----

def test_high_bid_pattern():
    text = "Order Confirming Sale - high bid of $128,500.00 to ABC LLC"
    assert _extract_sold_price(text) == 128500.0


def test_high_bid_with_colon():
    text = "Report of Sale - High Bid: $45,000"
    assert _extract_sold_price(text) == 45000.0


def test_sold_to_for_pattern():
    text = "Property sold to John Smith Investments LLC for $87,500.00"
    assert _extract_sold_price(text) == 87500.0


def test_sold_for_simple():
    text = "Sold for $32,000"
    assert _extract_sold_price(text) == 32000.0


def test_purchase_price_pattern():
    text = "Confirmation of Sale - purchase price $250,000"
    assert _extract_sold_price(text) == 250000.0


def test_purchased_for_pattern():
    text = "purchased for $99,250.00 by ABC Trust"
    assert _extract_sold_price(text) == 99250.0


def test_amount_near_confirm_pattern():
    text = "Order Confirming Sale entered. Amount $156,000.00 paid in full."
    assert _extract_sold_price(text) == 156000.0


def test_winning_bid_pattern():
    text = "Successful Bid: $44,500.00"
    assert _extract_sold_price(text) == 44500.0


def test_sale_price_pattern():
    text = "Sale Price: $19,250.00"
    assert _extract_sold_price(text) == 19250.0


# ---- rejection paths ----

def test_no_dollar_amount_returns_none():
    text = "Order Confirming Sale entered with no specific amount"
    assert _extract_sold_price(text) is None


def test_implausibly_low_rejected():
    """A $50 'sold for' is almost certainly a filing fee."""
    text = "Sold for $50.00"
    assert _extract_sold_price(text) is None


def test_implausibly_high_rejected():
    """$50M+ on a foreclosure sale is suspicious — hard cap at $10M."""
    text = "high bid of $50,000,000"
    assert _extract_sold_price(text) is None


def test_empty_text_returns_none():
    assert _extract_sold_price("") is None
    assert _extract_sold_price(None) is None  # noqa


# ---- pattern list metadata ----

def test_at_least_six_patterns_defined():
    """If anyone deletes SOLD_PRICE_PATTERNS or trims to 1-2 patterns,
    fail the test — coverage breadth is what makes this work against
    Tyler's varied docket-entry phrasing."""
    assert len(SOLD_PRICE_PATTERNS) >= 6


# ---- integration: prefers most-specific pattern ----

def test_prefers_high_bid_when_multiple_amounts():
    """Docket text has multiple $ values (interest, judgment, hammer);
    the hammer-price pattern (high bid) wins because it appears first
    in SOLD_PRICE_PATTERNS."""
    text = (
        "Judgment Amount: $185,432.10 entered "
        "Order Confirming Sale - high bid of $97,000.00 to Buyer LLC "
        "Excess proceeds: $0.00"
    )
    # 97000 (the hammer) wins over 185432.10 (judgment)
    assert _extract_sold_price(text) == 97000.0
