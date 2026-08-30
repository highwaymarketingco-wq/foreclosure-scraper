"""Tests for enrichment_derivation_flags — free_and_clear, tired_landlord, divorce."""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType


def _mk(source="test", raw=None, **kw) -> Listing:
    """Minimal listing for testing."""
    base = dict(
        source=source,
        source_url="https://example.com",
        county="Spartanburg",
        state="SC",
        raw=raw or {},
    )
    base.update(kw)
    return Listing(**base)


def test_free_and_clear_no_mortgage():
    """ROD with instruments but zero mortgages -> free_and_clear."""
    li = _mk(raw={
        "rod": {
            "instrument_count": 5,
            "has_mortgage": False,
            "open_mortgages_est": 0,
            "source": "spartanburg",
        }
    })
    from foreclosure_scraper.enrichment_derivation_flags import _free_and_clear
    result = _free_and_clear(li)
    assert result is not None
    assert result["flag"] is True
    assert result["reason"] == "no_mortgage_recordings"


def test_free_and_clear_with_mortgage():
    """ROD with open mortgages -> NOT free_and_clear."""
    li = _mk(raw={
        "rod": {
            "instrument_count": 3,
            "has_mortgage": True,
            "open_mortgages_est": 1,
            "source": "spartanburg",
        }
    })
    from foreclosure_scraper.enrichment_derivation_flags import _free_and_clear
    result = _free_and_clear(li)
    assert result is None


def test_free_and_clear_no_rod_data():
    """No ROD data -> can't claim free_and_clear."""
    li = _mk(raw={})
    from foreclosure_scraper.enrichment_derivation_flags import _free_and_clear
    result = _free_and_clear(li)
    assert result is None


def test_divorce_flag_from_source():
    """Listing from divorce scraper gets divorce flag."""
    li = _mk(source="counties_nc.nc_ecourts_divorce", raw={
        "case_id": "25-D-1234",
    })
    from foreclosure_scraper.enrichment_derivation_flags import _divorce_flag
    result = _divorce_flag(li)
    assert result is not None
    assert result["flag"] is True
    assert result["source"] == "ecourts_divorce"


def test_divorce_flag_from_listing_type():
    """Listing with DIVORCE_NOTICE type gets flagged."""
    li = _mk(listing_type=ListingType.DIVORCE_NOTICE)
    from foreclosure_scraper.enrichment_derivation_flags import _divorce_flag
    result = _divorce_flag(li)
    assert result is not None
    assert result["flag"] is True


def test_enrich_derivation_flags_runs():
    """End-to-end: enrich a list of listings."""
    from foreclosure_scraper.enrichment_derivation_flags import enrich_derivation_flags
    listings = [
        _mk(raw={"rod": {"instrument_count": 3, "has_mortgage": False, "open_mortgages_est": 0}}),
        _mk(source="counties_nc.nc_ecourts_divorce"),
        _mk(raw={}),
    ]
    stats = enrich_derivation_flags(listings)
    assert stats["free_and_clear"] == 1
    assert stats["divorce"] == 1
    assert stats["rows"] == 2


def test_mechanic_lien_detection():
    """ROD classify counts mechanic liens."""
    from foreclosure_scraper.rod.classify import classify_rod_docs
    from foreclosure_scraper.rod.models import RodDoc

    docs = [
        RodDoc(county="Spartanburg", state="SC", doc_type="MECHANIC LIEN",
               grantor="Builder", grantee="Owner", book="B1", page="P1"),
        RodDoc(county="Spartanburg", state="SC", doc_type="DEED OF TRUST",
               grantor="Owner", grantee="Bank", book="B2", page="P2"),
    ]
    result = classify_rod_docs(docs, source="test")
    assert result["has_mechanic_lien"] is True
    assert result["mechanic_lien_count"] == 1
