"""The publish-time coastal re-pass (main._resolve_coastal_pending) keeps inland DISTRESS leads.

THE BUG THIS PINS (found 2026-10-06, on the 2026-10-05 VM run)
    _in_scope() tags a coastal-county row that has an address or parcel but no coordinates
    yet (raw.oceanfront_pending). After geocoding, the re-pass in run() re-tested it and
    DROPPED every row that was not within a few hundred metres of the Atlantic or on the
    Charleston peninsula. Only distress leads could carry that tag then (a flip outside the 18
    footprint counties was rejected before the coastal checks, and no coastal county is in
    the footprint; since 2026-10-06 a coastal flip can carry it too and the re-pass applies the
    5 minute drive to it, see tests/test_flip_beach_drive.py), and a distress lead is in scope in
    any NC or SC county (owner rule of 2026-09-15, config.in_scope_distressed). The same inland lead was KEPT when it arrived
    with coordinates. On the 10/5 run the pass dropped 9,840 rows, e.g. every
    nc_heir_estate_parcels row in Brunswick (77), Carteret (61) and Charleston (73 scraped,
    68 published before, 0 after), and qpaybill Colleton fell from 1,198 to 587.

The rows below are real shapes from that run's published board / checkpoint.
"""
from __future__ import annotations

import inspect

from foreclosure_scraper import main as m
from foreclosure_scraper.main import _in_scope, _resolve_coastal_pending
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _lead(source, county, state, listing_type, **kw):
    return Listing(
        source=source, source_url="https://example.gov/x",
        listing_type=listing_type, property_kind=PropertyKind.UNKNOWN,
        county=county, state=state, raw=kw.pop("raw", {}), **kw,
    )


def _ingest_then_geocode(li, lat, lng):
    """What run() does to a row: the scope gate at ingest, geocoding later, then the re-pass."""
    assert _in_scope(li) is True
    assert li.raw.get("oceanfront_pending") is True, "precondition: admitted provisionally"
    li.latitude, li.longitude = lat, lng
    return _resolve_coastal_pending(li)


# ---- distress leads that resolve inland are kept (the bug) -------------------------------

def test_heir_estate_parcel_charleston_inland_is_kept():
    # nc_heir_estate_parcels, Charleston SC, parcel 0120000015, 497 BIG WOODS RD (Ravenel area,
    # well inland and off the peninsula)
    li = _lead("counties_nc.nc_heir_estate_parcels", "Charleston", "SC", ListingType.ESTATE_LEAD,
               parcel_id="0120000015", street_address="497 BIG WOODS RD")
    assert _ingest_then_geocode(li, 32.785, -80.236) is True
    assert not li.raw.get("oceanfront_pending")
    assert not li.raw.get("oceanfront") and not li.raw.get("downtown_charleston"), (
        "kept as a distress lead, not tagged as oceanfront")


def test_qpaybill_colleton_tax_row_inland_is_kept():
    # counties_sc.qpaybill_delinquent_roll, Colleton SC, parcel 179-00-00-077.000 (Walterboro)
    li = _lead("counties_sc.qpaybill_delinquent_roll", "Colleton", "SC", ListingType.TAX_SALE,
               parcel_id="179-00-00-077.000", street_address="191 DELOACH AVE")
    assert _ingest_then_geocode(li, 32.905, -80.666) is True
    assert not li.raw.get("oceanfront")


def test_heir_estate_parcel_brunswick_with_parcel_only_and_no_geocode_is_kept():
    # parcel only, and geocoding never produced coordinates: the beach test cannot pass, and the
    # lead is still in scope
    li = _lead("counties_nc.nc_heir_estate_parcels", "Brunswick", "NC", ListingType.ESTATE_LEAD,
               parcel_id="2000001234")
    assert _in_scope(li) is True
    assert li.raw.get("oceanfront_pending") is True
    assert _resolve_coastal_pending(li) is True


def test_outcome_no_longer_depends_on_whether_coordinates_came_with_the_row():
    kw = dict(parcel_id="179-00-00-077.000", street_address="191 DELOACH AVE")
    with_coords = _lead("counties_sc.qpaybill_delinquent_roll", "Colleton", "SC",
                        ListingType.TAX_SALE, latitude=32.905, longitude=-80.666, **kw)
    assert _in_scope(with_coords) is True              # never provisional
    assert _resolve_coastal_pending(with_coords) is None
    without = _lead("counties_sc.qpaybill_delinquent_roll", "Colleton", "SC",
                    ListingType.TAX_SALE, **kw)
    assert _ingest_then_geocode(without, 32.905, -80.666) is True


# ---- what the re-pass still does -------------------------------------------------------

def test_near_beach_row_is_kept_and_tagged_oceanfront():
    li = _lead("national.landwatch", "New Hanover", "NC", ListingType.DISTRESSED,
               street_address="123 N Lumina Ave", city="Wrightsville Beach")
    assert _ingest_then_geocode(li, 34.222, -77.788) is True
    assert li.raw.get("oceanfront") is True


def test_downtown_charleston_row_is_kept_and_tagged():
    li = _lead("counties_sc.sc_dew_lien_registry", "Charleston", "SC", ListingType.TAX_LIEN,
               street_address="80 BROAD ST", city="Charleston")
    assert _ingest_then_geocode(li, 32.7765, -79.9311) is True
    assert li.raw.get("downtown_charleston") is True


def test_a_provisional_flip_inland_still_drops():
    # Only reachable through a merge (_in_scope rejects a coastal flip at ingest), so set the
    # tag directly: the re-pass must not widen the 18-county flip footprint.
    li = _lead("law_firms.example", "Brunswick", "NC", ListingType.FORECLOSURE_SALE,
               street_address="10 Main St", raw={"oceanfront_pending": True})
    li.latitude, li.longitude = 34.06, -78.23
    assert _resolve_coastal_pending(li) is False


def test_a_coastal_flip_with_an_address_is_provisional_and_the_repass_decides_it():
    """Since 2026-10-06 (owner: a flip is wanted within a 5 minute drive of the beach) a coastal flip with
    a street waits for its point like a distress row; the re-pass then applies the beach-drive cutoff,
    which a distress row never meets (see tests/test_flip_beach_drive.py)."""
    li = _lead("law_firms.example", "Brunswick", "NC", ListingType.FORECLOSURE_SALE,
               street_address="10 Main St")
    assert _in_scope(li) is True
    assert li.raw.get("oceanfront_pending") is True
    li.latitude, li.longitude = 34.06, -78.23          # geocoded well inland
    assert _resolve_coastal_pending(li) is False


def test_non_provisional_row_is_left_to_the_other_passes():
    li = _lead("counties_sc.qpaybill_delinquent_roll", "Colleton", "SC", ListingType.TAX_SALE,
               street_address="191 DELOACH AVE")
    assert _resolve_coastal_pending(li) is None


def test_the_tag_is_consumed_either_way():
    li = _lead("law_firms.example", "Brunswick", "NC", ListingType.FORECLOSURE_SALE,
               street_address="10 Main St", raw={"oceanfront_pending": True,
                                                 "downtown_charleston_pending": True})
    _resolve_coastal_pending(li)
    assert "oceanfront_pending" not in li.raw and "downtown_charleston_pending" not in li.raw


def test_run_uses_the_module_level_verdict():
    src = inspect.getsource(m.run)
    assert "_resolve_coastal_pending(li)" in src
    assert "def _resolve_pending" not in src, "the old closure must not come back beside it"
