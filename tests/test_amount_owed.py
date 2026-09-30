"""Cross-source amount-owed waterfall.

Owner ask: fill the "amount owed" gap from another source when one lacks
it, without misrepresenting what the number is. Waterfall:
judgment (explicit, high) → opening_bid (≈ debt proxy, medium) →
assessed/tax value (not debt, low).
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_amount_owed import (
    enrich_amount_owed,
    promote_tax_owed_amount_owed,
)
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


# --- promote_tax_owed_amount_owed: second pass, runs after enrich_tax_owed --------------

def test_tax_owed_promotes_when_amount_owed_missing():
    """qpaybill_delinquent_roll-shaped lead: real balance in tax_owed, no amount_owed
    at all yet (enrich_amount_owed ran before tax_owed existed). Live board pattern
    measured 2026-09-29: 35,694 rows in exactly this state."""
    li = _li(listing_type=ListingType.TAX_SALE)
    li.raw["tax_owed"] = {"balance": 219.34, "kind": "delinquent_tax",
                          "source": "counties_sc.qpaybill_delinquent_roll",
                          "year": None, "basis": "own_record"}
    counts = promote_tax_owed_amount_owed([li])
    ao = li.raw["amount_owed"]
    assert ao["value"] == 219.34
    assert ao["source"] == "tax_owed"
    assert ao["is_actual_debt"] is True
    assert ao["confidence"] == "high"
    assert counts["promoted"] == 1


def test_tax_owed_promotes_over_mislabeled_proxy():
    """The other live-board pattern: amount_owed already set, but from the
    assessed-value proxy enrich_amount_owed() fell back to before tax_owed existed --
    exactly the "proxy confused with a real debt amount" defect. 33,576+ rows measured
    2026-09-29."""
    li = _li(listing_type=ListingType.TAX_SALE, assessed_value=95000.0)
    enrich_amount_owed([li])
    assert li.raw["amount_owed"]["source"] == "assessed_value"
    li.raw["tax_owed"] = {"balance": 1842.50, "kind": "delinquent_tax", "source": "t",
                          "year": 2024, "basis": "own_record"}
    promote_tax_owed_amount_owed([li])
    ao = li.raw["amount_owed"]
    assert ao["value"] == 1842.50
    assert ao["source"] == "tax_owed"
    assert ao["is_actual_debt"] is True


def test_tax_owed_never_overwrites_judgment_or_opening_bid():
    """A judgment/opening_bid is a different, often more relevant debt for THIS lead
    (e.g. the mortgage being foreclosed) and must survive even when a delinquent-tax
    balance for the same parcel is also known."""
    li = _li(judgment_amount=187425.0)
    enrich_amount_owed([li])
    li.raw["tax_owed"] = {"balance": 500.0, "kind": "delinquent_tax", "source": "t",
                          "year": None, "basis": "parcel_cross_ref"}
    counts = promote_tax_owed_amount_owed([li])
    ao = li.raw["amount_owed"]
    assert ao["source"] == "judgment"
    assert ao["value"] == 187425.0
    assert counts["unchanged"] == 1

    li2 = _li(opening_bid=150000.0)
    enrich_amount_owed([li2])
    li2.raw["tax_owed"] = {"balance": 500.0, "kind": "delinquent_tax", "source": "t",
                           "year": None, "basis": "own_record"}
    promote_tax_owed_amount_owed([li2])
    assert li2.raw["amount_owed"]["source"] == "opening_bid"


def test_tax_owed_cross_ref_basis_is_medium_confidence():
    """basis == parcel_cross_ref (inherited from a different lead resolved to the same
    parcel) is a real number for the parcel but arrived indirectly, so it is not the
    same confidence as the county's own direct record."""
    li = _li()
    li.raw["tax_owed"] = {"balance": 1200.0, "kind": "delinquent_tax", "source": "t",
                          "year": None, "basis": "parcel_cross_ref"}
    promote_tax_owed_amount_owed([li])
    ao = li.raw["amount_owed"]
    assert ao["confidence"] == "medium"
    assert ao["is_actual_debt"] is True


def test_tax_owed_no_balance_no_promotion():
    li = _li()
    li.raw["tax_owed"] = {"balance": None, "kind": "delinquent_tax", "source": "t",
                          "year": None, "basis": "own_record"}
    counts = promote_tax_owed_amount_owed([li])
    assert "amount_owed" not in li.raw
    assert counts["unchanged"] == 1


def test_tax_owed_promotion_is_idempotent():
    li = _li()
    li.raw["tax_owed"] = {"balance": 300.0, "kind": "delinquent_tax", "source": "t",
                          "year": None, "basis": "own_record"}
    promote_tax_owed_amount_owed([li])
    first = dict(li.raw["amount_owed"])
    promote_tax_owed_amount_owed([li])
    assert li.raw["amount_owed"] == first
