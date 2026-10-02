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


def test_unreleased_mortgage_with_open_mortgage():
    """ROD showing an open (unsatisfied) mortgage -> unreleased_mortgage flag."""
    li = _mk(raw={
        "rod": {
            "instrument_count": 3,
            "has_mortgage": True,
            "open_mortgages_est": 1,
            "mortgage_count": 1,
            "satisfaction_count": 0,
            "source": "spartanburg",
        }
    })
    from foreclosure_scraper.enrichment_derivation_flags import _unreleased_mortgage
    result = _unreleased_mortgage(li)
    assert result is not None
    assert result["flag"] is True
    assert result["open_mortgages_est"] == 1


def test_unreleased_mortgage_free_and_clear_is_not_flagged():
    """Zero open mortgages -> NOT unreleased_mortgage (the free_and_clear case)."""
    li = _mk(raw={
        "rod": {
            "instrument_count": 5,
            "has_mortgage": False,
            "open_mortgages_est": 0,
            "source": "spartanburg",
        }
    })
    from foreclosure_scraper.enrichment_derivation_flags import _unreleased_mortgage
    assert _unreleased_mortgage(li) is None


def test_unreleased_mortgage_no_rod_data():
    """No ROD data -> can't claim unreleased_mortgage either."""
    li = _mk(raw={})
    from foreclosure_scraper.enrichment_derivation_flags import _unreleased_mortgage
    assert _unreleased_mortgage(li) is None


def test_unreleased_mortgage_respects_name_order_suspect_guard():
    """Same surname-first-parser guard as free_and_clear: a Title Case owner
    name fetched by a surname-first ROD parser before the 2026-09-18 fix must
    not produce either claim."""
    li = _mk(owner_name="Joshua D Smith", raw={
        "rod": {
            "instrument_count": 2,
            "has_mortgage": True,
            "open_mortgages_est": 1,
            "source": "spartanburg_rod_render",
            "fetched_at": "2026-09-01T00:00:00+00:00",
        }
    })
    from foreclosure_scraper.enrichment_derivation_flags import _unreleased_mortgage
    assert _unreleased_mortgage(li) is None


def test_enrich_derivation_flags_counts_unreleased_mortgage():
    from foreclosure_scraper.enrichment_derivation_flags import enrich_derivation_flags
    listings = [
        _mk(raw={"rod": {"instrument_count": 3, "has_mortgage": True, "open_mortgages_est": 2,
                          "source": "spartanburg"}}),
    ]
    stats = enrich_derivation_flags(listings)
    assert stats["unreleased_mortgage"] == 1
    assert listings[0].raw["derivation_flags"]["unreleased_mortgage"]["flag"] is True


def _mortgage_instrument(date, grantee, book="B1", page="P1"):
    return {"date": date, "type": "DEED OF TRUST", "grantor": "OWNER NAME",
            "grantee": grantee, "book": book, "page": page}


def test_subordinate_lien_foreclosure_flags_junior_mortgage_match():
    """Two active mortgages on file; the foreclosing plaintiff's name matches
    the grantee of the newer (junior) one -> subordinate_lien_foreclosure."""
    li = _mk(
        plaintiff="PennyMac Loan Services LLC",
        raw={"rod": {
            "instrument_count": 2, "has_mortgage": True, "open_mortgages_est": 2,
            "source": "cchs_rod",
            "instruments": [
                _mortgage_instrument("2020-06-01", "PennyMac Loan Services LLC", page="P2"),
                _mortgage_instrument("2015-01-01", "Wells Fargo Bank NA", page="P1"),
            ],
        }},
    )
    from foreclosure_scraper.enrichment_derivation_flags import _subordinate_lien_foreclosure
    result = _subordinate_lien_foreclosure(li)
    assert result is not None
    assert result["flag"] is True
    assert result["foreclosing_position"] == 2
    assert result["senior_lien_count"] == 1


def test_subordinate_lien_foreclosure_no_match_stays_unflagged():
    """Same lien stack, but the plaintiff is the SENIOR lender (Wells Fargo),
    not the most-recently-recorded mortgage PennyMac infers to. The name
    mismatch must suppress the flag rather than trust the date-order guess."""
    li = _mk(
        plaintiff="Wells Fargo Bank NA",
        raw={"rod": {
            "instrument_count": 2, "has_mortgage": True, "open_mortgages_est": 2,
            "source": "cchs_rod",
            "instruments": [
                _mortgage_instrument("2020-06-01", "PennyMac Loan Services LLC", page="P2"),
                _mortgage_instrument("2015-01-01", "Wells Fargo Bank NA", page="P1"),
            ],
        }},
    )
    from foreclosure_scraper.enrichment_derivation_flags import _subordinate_lien_foreclosure
    assert _subordinate_lien_foreclosure(li) is None


def test_subordinate_lien_foreclosure_single_mortgage_is_not_subordinate():
    """Only one mortgage on file -> nothing to be subordinate to."""
    li = _mk(
        plaintiff="PennyMac Loan Services LLC",
        raw={"rod": {
            "instrument_count": 1, "has_mortgage": True, "open_mortgages_est": 1,
            "source": "cchs_rod",
            "instruments": [_mortgage_instrument("2020-06-01", "PennyMac Loan Services LLC")],
        }},
    )
    from foreclosure_scraper.enrichment_derivation_flags import _subordinate_lien_foreclosure
    assert _subordinate_lien_foreclosure(li) is None


def test_subordinate_lien_foreclosure_no_instruments_list():
    """rod dict present but no instruments array (summary-only shape) -> None."""
    li = _mk(plaintiff="PennyMac Loan Services LLC",
              raw={"rod": {"instrument_count": 2, "has_mortgage": True, "open_mortgages_est": 2}})
    from foreclosure_scraper.enrichment_derivation_flags import _subordinate_lien_foreclosure
    assert _subordinate_lien_foreclosure(li) is None


def test_enrich_derivation_flags_counts_subordinate_lien():
    from foreclosure_scraper.enrichment_derivation_flags import enrich_derivation_flags
    listings = [
        _mk(plaintiff="PennyMac Loan Services LLC", raw={"rod": {
            "instrument_count": 2, "has_mortgage": True, "open_mortgages_est": 2,
            "source": "cchs_rod",
            "instruments": [
                _mortgage_instrument("2020-06-01", "PennyMac Loan Services LLC", page="P2"),
                _mortgage_instrument("2015-01-01", "Wells Fargo Bank NA", page="P1"),
            ],
        }}),
    ]
    stats = enrich_derivation_flags(listings)
    assert stats["subordinate_lien_foreclosure"] == 1
    assert listings[0].raw["derivation_flags"]["subordinate_lien_foreclosure"]["flag"] is True


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
