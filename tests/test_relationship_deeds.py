"""Pin the ROD relationship-deed detection (probate + divorce signals).

Synthetic-data tests since the live ROD pool requires the production
scraper to run first. These exercise the pure-function pattern detectors
+ the emit-new-leads dispatch in enrich_with_relationship_deeds.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_relationship_deeds import (
    PROBATE_KEYWORDS,
    QUITCLAIM_KEYWORDS,
    _looks_divorce,
    _looks_probate,
    enrich_with_relationship_deeds,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(**kw) -> Listing:
    base = dict(
        source="counties_nc.nc_rod_substitute_trustee",
        source_url="https://example.com/rod/123",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Buncombe",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


# ---- _looks_probate ----

def test_executor_deed_matches_probate():
    li = _li(raw={"doc_type": "EXECUTOR'S DEED"})
    assert _looks_probate(li) == "EXECUTOR"


def test_administrator_deed_matches_probate():
    li = _li(raw={"doc_type": "ADMINISTRATOR'S DEED"})
    assert _looks_probate(li) == "ADMINISTRATOR"


def test_estate_of_in_grantor_matches_probate():
    li = _li(raw={"rod": {"grantor": "ESTATE OF JOHN SMITH"}})
    assert _looks_probate(li) == "ESTATE OF"


def test_devise_matches_probate():
    li = _li(raw={"doc_type": "DEVISE"})
    assert _looks_probate(li) == "DEVISE"


def test_letters_testamentary_matches_probate():
    li = _li(raw={"doc_type": "LETTERS TESTAMENTARY"})
    assert _looks_probate(li) == "TESTAMENTARY"


def test_no_probate_keyword_returns_none():
    li = _li(raw={"doc_type": "DEED OF TRUST"})
    assert _looks_probate(li) is None


def test_last_will_matches_but_will_be_does_not():
    """'LAST WILL' / 'WILL AND TESTAMENT' patterns are unambiguous;
    bare 'will be sold' must not match."""
    matched = _li(raw={"doc_type": "LAST WILL AND TESTAMENT"})
    assert _looks_probate(matched) is not None
    not_matched = _li(raw={"notes": "this property will be sold soon"})
    assert _looks_probate(not_matched) is None


def test_at_least_seven_probate_keywords():
    """Coverage breadth is what makes this work against varied vendor
    doc-type strings — fail loud if anyone trims the list."""
    assert len(PROBATE_KEYWORDS) >= 7


# ---- _looks_divorce ----

def test_quitclaim_with_zero_consideration_matches_divorce():
    li = _li(raw={
        "doc_type": "QUITCLAIM DEED",
        "consideration_amount": 0,
        "grantor": "JOHN SMITH AND JANE SMITH",
        "grantee": "JOHN SMITH",
    })
    assert _looks_divorce(li) == "couple_to_single_quitclaim"


def test_quitclaim_with_zero_consideration_no_couple_pattern():
    """Quitclaim + $0 but no couple-grantor pattern still tags as
    weaker zero_consideration_quitclaim signal."""
    li = _li(raw={
        "doc_type": "QUITCLAIM DEED",
        "consideration_amount": 0,
        "grantor": "JOHN SMITH",
        "grantee": "JANE DOE",
    })
    assert _looks_divorce(li) == "zero_consideration_quitclaim"


def test_divorce_decree_tagged():
    li = _li(raw={"doc_type": "DIVORCE DECREE", "consideration_amount": 0})
    assert _looks_divorce(li) is not None


def test_equitable_distribution_tagged():
    li = _li(raw={"doc_type": "EQUITABLE DISTRIBUTION", "consideration_amount": 0})
    assert _looks_divorce(li) is not None


def test_quitclaim_with_real_consideration_not_divorce():
    """Quitclaim + non-zero consideration is a genuine sale, not divorce."""
    li = _li(raw={
        "doc_type": "QUITCLAIM DEED",
        "consideration_amount": 125000.0,
        "grantor": "JOHN SMITH AND JANE SMITH",
        "grantee": "JOHN SMITH",
    })
    assert _looks_divorce(li) is None


def test_warranty_deed_not_divorce():
    """Standard warranty deed (sale) is not divorce regardless of price."""
    li = _li(raw={"doc_type": "WARRANTY DEED", "consideration_amount": 0})
    assert _looks_divorce(li) is None


def test_at_least_six_quitclaim_keywords():
    assert len(QUITCLAIM_KEYWORDS) >= 6


# ---- enrich_with_relationship_deeds integration ----

def test_enrich_emits_probate_lead_with_address():
    rod = _li(
        raw={"doc_type": "EXECUTOR'S DEED"},
        street_address="123 Main St",
        zip_code="28801",
    )
    new = enrich_with_relationship_deeds([rod])
    assert len(new) == 1
    lead = new[0]
    assert lead.listing_type == ListingType.PROBATE_NOTICE
    assert lead.street_address == "123 Main St"
    assert lead.source.startswith("derived.probate_deed")
    # In-place tag on the original
    assert rod.raw["relationship_signal"]["kind"] == "probate"


def test_enrich_emits_divorce_lead_with_address():
    rod = _li(
        raw={
            "doc_type": "QUITCLAIM DEED",
            "consideration_amount": 0,
            "grantor": "JOHN SMITH AND JANE SMITH",
            "grantee": "JOHN SMITH",
        },
        street_address="456 Oak Ave",
        zip_code="28805",
    )
    new = enrich_with_relationship_deeds([rod])
    assert len(new) == 1
    lead = new[0]
    assert lead.listing_type == ListingType.DIVORCE_NOTICE
    assert lead.source.startswith("derived.divorce_deed")
    assert rod.raw["relationship_signal"]["kind"] == "divorce"


def test_enrich_skips_recordings_without_address():
    """Without an address the lead is not actionable — skip the new
    listing emission but still tag the original."""
    rod = _li(
        raw={"doc_type": "EXECUTOR'S DEED"},
        street_address=None,
    )
    new = enrich_with_relationship_deeds([rod])
    assert len(new) == 0
    # Original still tagged
    assert rod.raw["relationship_signal"]["kind"] == "probate"


def test_enrich_dedupes_same_address_county():
    """Two ROD recordings at the same address should emit one lead."""
    rod1 = _li(
        raw={"doc_type": "EXECUTOR'S DEED"},
        street_address="100 Pine Rd",
        zip_code="28704",
    )
    rod2 = _li(
        raw={"doc_type": "ADMINISTRATOR'S DEED"},
        street_address="100 Pine Rd",
        zip_code="28704",
    )
    new = enrich_with_relationship_deeds([rod1, rod2])
    assert len(new) == 1


def test_enrich_handles_empty_list():
    new = enrich_with_relationship_deeds([])
    assert new == []


def test_enrich_scans_sold_pool_too():
    """sold_pool kwarg is also scanned for relationship signals."""
    sold = _li(
        raw={"doc_type": "EXECUTOR'S DEED", "actual_sold_price": 150000},
        street_address="789 Cedar Way",
        zip_code="28806",
    )
    new = enrich_with_relationship_deeds([], sold_pool=[sold])
    assert len(new) == 1
    assert new[0].listing_type == ListingType.PROBATE_NOTICE


def test_listing_types_include_new_values():
    """ListingType enum must have the new values for the rest of the
    pipeline to round-trip them through serialization."""
    assert ListingType.DIVORCE_NOTICE.value == "divorce_notice"
    assert ListingType.PROBATE_NOTICE.value == "probate_notice"
    assert ListingType.ESTATE_LEAD.value == "estate_lead"
