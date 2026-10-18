"""enrich_deed_chain must not fold a fallback-point row's county_sales/assessor_card/gis.last_sale
into that row's OWN deed chain (audit 2026-10-18, block-binding-family-deed-sale: 4,259 rows).
Every parcel, owner and address here is made up."""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_deed_chain import enrich_deed_chain
from foreclosure_scraper.enrichment_geocode import COUNTY_SEAT_CENTROIDS
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

NOW = datetime(2026, 10, 18)
LAT, LNG = next(iter(COUNTY_SEAT_CENTROIDS.values()))


def _li(parcel=None, street=None, raw=None, lat=LAT, lng=LNG):
    return Listing(source="s", source_url="https://x.invalid/1", listing_type=ListingType.TAX_LIEN,
                   property_kind=PropertyKind.UNKNOWN, state="NC", county="Sample",
                   parcel_id=parcel, street_address=street, owner_name="ALPHA ANN",
                   latitude=lat, longitude=lng, first_seen=NOW, last_seen=NOW, raw=raw or {})


def test_county_sales_does_not_become_a_fallback_point_rows_own_deed():
    li = _li(raw={"county_sales": {"sales": [{"date": "2025-02-01", "price": 20000.0}]}})
    enrich_deed_chain([li])
    assert "deed_chain" not in li.raw


def test_assessor_card_and_gis_last_sale_are_also_withheld_at_a_fallback_point():
    li = _li(raw={
        "assessor_card": {"sales": [{"sale_date": "2020-01-01", "price": 1000.0, "grantor": "X"}]},
        "gis": {"last_sale": {"date": "2019-01-01", "amount": 5000.0}},
    })
    enrich_deed_chain([li])
    assert "deed_chain" not in li.raw


def test_a_real_parcel_still_gets_its_own_deed_chain():
    li = _li(parcel="1357-24-6801", street="11 Test Rd", lat=35.111, lng=-81.222,
             raw={"county_sales": {"sales": [{"date": "2025-02-01", "price": 20000.0}]}})
    enrich_deed_chain([li])
    assert li.raw["deed_chain"]["summary"]["chain_length"] == 1


def test_name_matched_sources_still_build_a_chain_at_a_fallback_point():
    li = _li(raw={"relationship_signal": {"date": "2024-05-01", "signal": "divorce_deed",
                                          "grantor": "ALPHA ANN", "grantee": "ALPHA BOB"}})
    enrich_deed_chain([li])
    assert li.raw["deed_chain"]["summary"]["chain_length"] == 1


def test_an_all_null_relationship_signal_builds_no_junk_record():
    li = _li(street="11 Test Rd", parcel="1357-24-6801", lat=35.111, lng=-81.222,
             raw={"relationship_signal": {"date": None, "signal": None, "grantor": None, "grantee": None}})
    enrich_deed_chain([li])
    assert "deed_chain" not in li.raw


def test_a_stale_fallback_point_deed_chain_is_cleared_on_the_next_pass():
    li = _li(raw={"deed_chain": {"transfers": [{"date": "2019-01-01", "price": 5000.0,
                                                "source": "gis.last_sale"}],
                                 "summary": {"chain_length": 1}}})
    enrich_deed_chain([li])
    assert "deed_chain" not in li.raw
