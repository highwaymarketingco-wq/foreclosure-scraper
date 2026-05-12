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


# ---- broadened patterns (2026-05-12 follow-up) ------------------------------
# Patch run #10 reported text_no_match=729 — too many real notices weren't
# matching. These tests pin the new phrasings the broadened patterns accept.

def test_judgment_amount_of_X_phrasing():
    """Real NC notice: 'The judgment amount of $X was entered.'
    Previous patterns required colon/equals or 'in the amount of';
    plain 'amount of $X' was missing."""
    text = "Pursuant to a judgment entered, the trustee will offer for sale. The judgment amount of $125,750.00 was entered against the defendant."
    assert _extract_from_text(text) == 125_750.00


def test_judgment_after_opening_bid_phrase():
    """'opening bid will not be less than the judgment amount of $X' —
    previously the 80-char before-context filter killed this match.
    Tightened to 30 chars so only adjacent context triggers rejection."""
    text = "The opening bid will not be less than the judgment amount of $85,000.00."
    assert _extract_from_text(text) == 85_000.00


def test_money_judgment_in_amount_of():
    """NC notice variant: 'a money judgment in the amount of $X'"""
    text = "a money judgment in the amount of $340,000 was entered against John Smith."
    assert _extract_from_text(text) == 340_000.0


def test_promissory_note_original_principal_amount():
    """NC notice often includes the original loan amount via promissory
    note — proxies as judgment when no judgment-specific amount appears."""
    text = "NOTICE: evidenced by that certain Promissory Note in the original principal amount of $215,000.00 dated July 15, 2018."
    assert _extract_from_text(text) == 215_000.00


def test_unpaid_principal_balance():
    text = "The unpaid principal balance is $92,450.12 as of the date hereof."
    assert _extract_from_text(text) == 92_450.12


def test_sale_price_alone_still_rejected():
    """We still don't want to capture sale price as judgment."""
    text = "The sale price was $50,000."
    assert _extract_from_text(text) is None


def test_opening_bid_directly_before_amount_rejected():
    """Adjacent 'Opening bid: $X' should NOT be treated as judgment —
    the 30-char before-context filter catches this case."""
    text = "Opening bid: $10,000 starting amount for the auction."
    assert _extract_from_text(text) is None
