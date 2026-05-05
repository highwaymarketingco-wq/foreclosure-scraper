"""Regression tests for judgment-amount text-mining.

The audit found 0 of 1299 listings had judgment_amount populated despite
the field being on the model and shown in the sheet. This enrichment
back-fills it from notice text we already have. Investors use it as a
mortgage-balance-remaining proxy.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_judgment_amount import (
    _extract_from_text,
    _parse_amount,
    enrich_judgment_amount,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(**kw) -> Listing:
    base = dict(
        source="law_firms.hutchens", source_url="http://x",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={},
    )
    base.update(kw)
    return Listing(**base)


# ---- _parse_amount ----------------------------------------------------------

def test_parse_amount_with_commas():
    assert _parse_amount("123,456.78") == 123_456.78


def test_parse_amount_million():
    assert _parse_amount("1.5 million") == 1_500_000.0


def test_parse_amount_no_decimals():
    assert _parse_amount("250000") == 250_000.0


def test_parse_amount_garbage():
    assert _parse_amount("abc") is None


# ---- _extract_from_text -----------------------------------------------------

def test_extract_judgment_amount_simple():
    text = "Pursuant to a Judgment in the amount of $156,789.42 entered..."
    assert _extract_from_text(text) == 156_789.42


def test_extract_outstanding_principal():
    text = "The outstanding principal balance is $98,250.00 plus interest..."
    assert _extract_from_text(text) == 98_250.0


def test_extract_total_amount_due():
    text = "Total amount due: $234,000"
    assert _extract_from_text(text) == 234_000.0


def test_extract_indebtedness():
    text = "...the indebtedness in the amount of $87,500.50 secured by..."
    assert _extract_from_text(text) == 87_500.50


def test_extract_rejects_opening_bid_context():
    """A dollar amount near "opening bid" must NOT be captured as judgment."""
    text = "The opening bid for this sale is $50,000."
    assert _extract_from_text(text) is None


def test_extract_rejects_sale_price_context():
    text = "Sale price: $145,000"
    assert _extract_from_text(text) is None


def test_extract_rejects_tax_value_context():
    text = "Tax value (assessed) is $125,750"
    assert _extract_from_text(text) is None


def test_extract_rejects_too_small():
    """An amount under $1,000 is almost certainly a fee or filing cost."""
    text = "Judgment amount: $250"
    assert _extract_from_text(text) is None


def test_extract_rejects_too_large():
    """Implausibly large — probably a parse / units error."""
    text = "Judgment amount: $9,999,999,999"
    assert _extract_from_text(text) is None


def test_extract_picks_judgment_over_unrelated():
    """Document has both a sale price AND a judgment — take the judgment."""
    text = (
        "Notice of foreclosure sale. Pursuant to a Judgment in the amount "
        "of $187,432.55 entered in case 2026-CP-04-12345. The opening bid "
        "for this sale is $80,000."
    )
    assert _extract_from_text(text) == 187_432.55


# ---- end-to-end -------------------------------------------------------------

def test_enrich_populates_judgment_from_description():
    li = _li(
        description="Foreclosure sale notice. Judgment amount: $89,500.00 entered 04/15/2026."
    )
    enrich_judgment_amount([li])
    assert li.judgment_amount == 89_500.0


def test_enrich_populates_from_raw_blob():
    li = _li(
        description="Sale on May 5",
        raw={"notice_text": "...the principal balance of $145,000.00 plus interest..."},
    )
    enrich_judgment_amount([li])
    assert li.judgment_amount == 145_000.0


def test_enrich_skips_when_already_set():
    li = _li(
        judgment_amount=100_000.0,
        description="Judgment amount: $200,000",  # different value
    )
    stats = enrich_judgment_amount([li])
    assert li.judgment_amount == 100_000.0  # not overwritten
    assert stats["already_set"] == 1


def test_enrich_no_match_leaves_field_none():
    li = _li(description="Foreclosure sale on the steps of the Spartanburg County Courthouse.")
    enrich_judgment_amount([li])
    assert li.judgment_amount is None
