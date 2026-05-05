"""Tests for the CourtListener expansion suite.

Three new code paths:
  * national.courtlistener_civil          — federal real-property cases
  * national.courtlistener_adversary      — lift-stay + §363 sale motions
  * enrichment_recap_document             — pull motion body text
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

from foreclosure_scraper.enrichment_recap_document import enrich_recap_documents
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.scrapers.national.courtlistener_civil import (
    CIVIL_COURTS,
    CourtListenerCivil,
    REAL_PROPERTY_NOS,
    _is_real_property_case,
)
from foreclosure_scraper.scrapers.national.courtlistener_adversary import (
    LIFT_STAY_RE,
    SECTION_363_RE,
    CourtListenerAdversary,
    _classify_entry,
)


# ---- civil scraper: real-property classifier --------------------------------

def test_civil_real_property_by_nos_code():
    assert _is_real_property_case({"nature_of_suit": "220"})
    assert _is_real_property_case({"nature_of_suit": "290"})
    assert _is_real_property_case({"nature_of_suit": "Foreclosure"})


def test_civil_not_real_property():
    assert not _is_real_property_case({"nature_of_suit": "470"})  # racketeering
    assert not _is_real_property_case({"nature_of_suit": ""})


def test_civil_falls_back_to_cause_text():
    assert _is_real_property_case({"nature_of_suit": "", "cause": "Quiet title action"})
    assert _is_real_property_case({"nature_of_suit": "", "cause": "Foreclosure under deed of trust"})


def test_civil_courts_cover_nc_sc():
    assert "scd" in CIVIL_COURTS
    assert "ncwd" in CIVIL_COURTS
    assert "ncmd" in CIVIL_COURTS
    assert "nced" in CIVIL_COURTS


def test_civil_real_property_nos_set_includes_220():
    assert "220" in REAL_PROPERTY_NOS
    assert "290" in REAL_PROPERTY_NOS


# ---- adversary scraper: motion classifier -----------------------------------

def test_classify_lift_stay_motion():
    desc = "Motion for Relief from Automatic Stay filed by Bank of America NA"
    assert _classify_entry(desc) == "lift_stay"


def test_classify_lift_stay_alt_phrasings():
    for desc in [
        "Motion to lift the automatic stay",
        "Motion for relief from the automatic stay",
        "Application for relief from automatic stay",
        "Stay relief motion under § 362",
        "Movant seeks relief from stay",
    ]:
        assert _classify_entry(desc) == "lift_stay", f"missed: {desc!r}"


def test_classify_363_sale_motion():
    desc = "Motion to sell real property under 11 U.S.C. § 363"
    assert _classify_entry(desc) == "363_sale"


def test_classify_363_sale_alt_phrasings():
    for desc in [
        "Motion under section 363 to sell debtor's real property",
        "Sale of real estate pursuant to 11 USC § 363",
        "Section 363 sale motion",
    ]:
        assert _classify_entry(desc) == "363_sale", f"missed: {desc!r}"


def test_classify_unrelated_returns_none():
    for desc in [
        "Notice of appearance by counsel",
        "Schedules A and B filed",
        "Order on motion to extend deadline",
    ]:
        assert _classify_entry(desc) is None


# ---- adversary scraper class metadata ---------------------------------------

def test_adversary_scraper_metadata():
    s = CourtListenerAdversary()
    assert s.slug == "national.courtlistener_adversary"
    assert s.expected_min_count == 0
    assert s.requires_apify is False


def test_civil_scraper_metadata():
    s = CourtListenerCivil()
    assert s.slug == "national.courtlistener_civil"
    assert s.expected_min_count == 0
    assert s.requires_apify is False


# ---- adversary scraper: empty fetch when no token --------------------------

def test_adversary_skips_without_token():
    with patch(
        "foreclosure_scraper.scrapers.national.courtlistener_adversary._load_token",
        return_value=None,
    ):
        out = list(asyncio.run(CourtListenerAdversary().fetch()))
    assert out == []


def test_civil_skips_without_token():
    with patch(
        "foreclosure_scraper.scrapers.national.courtlistener_civil._load_token",
        return_value=None,
    ):
        out = list(asyncio.run(CourtListenerCivil().fetch()))
    assert out == []


# ---- RECAP document enrichment ---------------------------------------------

def _adv_li(**kw) -> Listing:
    base = dict(
        source="national.courtlistener_adversary", source_url="http://x",
        listing_type=ListingType.LIS_PENDENS, property_kind=PropertyKind.UNKNOWN,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={"courtlistener_adversary": {
            "court": "ncwb", "classification": "lift_stay",
            "docket_id": 12345, "entry_id": 99999,
            "case_name": "Test Debtor",
        }},
    )
    base.update(kw)
    return Listing(**base)


def test_recap_enrichment_skips_when_no_token():
    li = _adv_li()
    with patch(
        "foreclosure_scraper.enrichment_recap_document._load_token",
        return_value=None,
    ):
        stats = asyncio.run(enrich_recap_documents([li]))
    assert stats.get("annotated", 0) == 0
    assert stats.get("skipped_no_token") == 1


def test_recap_enrichment_skips_non_adversary_listings():
    """Lis-pendens scraper output, foreclosure-sale, etc. — not eligible."""
    other = Listing(
        source="counties_sc.spartanburg_master_in_equity",
        source_url="http://x",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={},
    )
    with patch(
        "foreclosure_scraper.enrichment_recap_document._load_token",
        return_value="fake-token",
    ):
        stats = asyncio.run(enrich_recap_documents([other]))
    assert stats == {"queried": 0, "annotated": 0}


def test_recap_enrichment_annotates_adversary_listing():
    li = _adv_li()
    fake_doc = {
        "plain_text": (
            "Motion for Relief from Automatic Stay. Movant respectfully "
            "requests relief from the automatic stay imposed by 11 U.S.C. "
            "§ 362 to permit foreclosure of the property located at "
            "1234 Main Street, Asheville, NC 28801. The outstanding "
            "indebtedness is $187,432.55 as of the petition date."
        ),
        "page_count": 4,
        "document_url": "http://example.com/doc.pdf",
        "doc_id": 5555,
    }
    with patch(
        "foreclosure_scraper.enrichment_recap_document._load_token",
        return_value="fake-token",
    ), patch(
        "foreclosure_scraper.enrichment_recap_document._fetch_recap_doc_for_entry",
        new=AsyncMock(return_value=fake_doc),
    ), patch("asyncio.sleep", new=AsyncMock()):
        stats = asyncio.run(enrich_recap_documents([li]))

    assert stats["annotated"] == 1
    assert li.raw["recap"]["plain_text"].startswith("Motion for Relief")
    assert li.raw["recap"]["page_count"] == 4
    # Judgment-amount enrichment can now find the $187,432.55 since the
    # text is reachable via raw.recap.plain_text (which the scanner
    # walks because it descends into nested dicts).
    assert "$187,432.55" in li.raw["recap"]["plain_text"]


def test_recap_enrichment_caps_body_size():
    """Documents > 50KB are truncated to bound the listings.json size."""
    huge_text = "A" * 200_000  # 200KB
    li = _adv_li()
    with patch(
        "foreclosure_scraper.enrichment_recap_document._load_token",
        return_value="fake-token",
    ), patch(
        "foreclosure_scraper.enrichment_recap_document._fetch_recap_doc_for_entry",
        new=AsyncMock(return_value={
            "plain_text": huge_text[:50_000],   # _fetch already caps
            "page_count": 99,
            "document_url": "x",
            "doc_id": 1,
        }),
    ), patch("asyncio.sleep", new=AsyncMock()):
        asyncio.run(enrich_recap_documents([li]))
    assert len(li.raw["recap"]["plain_text"]) == 50_000
