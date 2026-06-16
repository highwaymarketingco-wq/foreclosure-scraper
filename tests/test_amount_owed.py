"""Cross-source amount-owed waterfall.

Owner ask: fill the "amount owed" gap from another source when one lacks
it, without misrepresenting what the number is. Waterfall:
judgment (explicit, high) → opening_bid (≈ debt proxy, medium) →
assessed/tax value (not debt, low).
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_amount_owed import enrich_amount_owed
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(**kw):
    base = dict(
        source="t", source_url="x", listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY, state="NC", county="Burke",
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


def test_explicit_judgment_wins_and_is_flagged_actual():
    li = _li(judgment_amount=187425.0, opening_bid=150000.0)
    enrich_amount_owed([li])
    ao = li.raw["amount_owed"]
    assert ao["value"] == 187425.0
    assert ao["source"] == "judgment"
    assert ao["is_actual_debt"] is True
    assert ao["confidence"] == "high"


def test_opening_bid_used_as_proxy_not_labeled_as_debt():
    li = _li(opening_bid=150000.0)
    enrich_amount_owed([li])
    ao = li.raw["amount_owed"]
    assert ao["value"] == 150000.0
    assert ao["source"] == "opening_bid"
    assert ao["is_actual_debt"] is False           # never misrepresented
    assert "≈" in ao["label"]


def test_assessed_value_last_resort_low_confidence():
    li = _li(assessed_value=95000.0)
    enrich_amount_owed([li])
    ao = li.raw["amount_owed"]
    assert ao["source"] == "assessed_value"
    assert ao["confidence"] == "low"
    assert ao["is_actual_debt"] is False


def test_opening_bid_ignored_for_non_foreclosure():
    """An REO list price isn't 'amount owed' — only foreclosure/LP types
    use opening_bid as the debt proxy."""
    li = _li(listing_type=ListingType.REO, opening_bid=200000.0)
    enrich_amount_owed([li])
    assert "amount_owed" not in li.raw  # no debt concept for a plain REO list price


def test_nothing_when_no_signal():
    li = _li()
    counts = enrich_amount_owed([li])
    assert "amount_owed" not in li.raw
    assert counts["none"] == 1
