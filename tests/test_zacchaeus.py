"""Pin the Zacchaeus Legal Services (ZLS) NC tax-foreclosure grid parser.

ZLS (zls-nc.com/listings) is a Blazor Server app whose DevExpress grid is
paged over WebSocket, so the row capture needs a real browser. The row ->
Listing mapping does not, and that is what breaks silently when ZLS renames a
column or adds a status.

The fixture (tests/fixtures/zls_grid_rows.json) is a slice of a real capture
taken 2026-07-31: one row per distinct status the grid emits, plus the three
non-county "Tax Office" shapes (City of ..., Town of ..., "... County General
Courts of Justice") and one empty pad row.

Note on coverage: as of that capture ZLS carried 219 rows across 30 collecting
offices and ZERO in the 11-county WNC footprint — it is an eastern/piedmont NC
firm (Guilford, Forsyth, Iredell, Cabarrus, Robeson, Scotland ...). It reaches
the board only through the coastal-county bypass.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreclosure_scraper.scrapers.law_firms.zacchaeus import (
    Zacchaeus,
    _clean_address,
    _clean_county,
    _clean_money,
    _is_dead,
    _latlng_from_maps_url,
    _municipality,
    _parse_date,
    _row_to_listing,
)

SLUG = "law_firms.zacchaeus"
FIXTURE = Path(__file__).parent / "fixtures" / "zls_grid_rows.json"


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def listings(rows) -> list:
    return [li for li in (_row_to_listing(r, SLUG) for r in rows) if li is not None]


# ---- tax-office -> county ----

def test_county_office_strips_suffix():
    assert _clean_county("Onslow County Tax Office") == "Onslow"


def test_court_named_office_still_yields_the_county():
    """'County' is mid-string here, so a suffix-only strip left the whole
    sentence as the county."""
    assert _clean_county("Wake County General Courts of Justice") == "Wake"


def test_municipal_office_is_not_a_county():
    assert _clean_county("City of Laurinburg") is None
    assert _clean_county("Town of Plymouth") is None


def test_municipality_extractor():
    assert _municipality("City of Laurinburg") == "Laurinburg"
    assert _municipality("Town of Williamston") == "Williamston"
    assert _municipality("Guilford County Tax Office") is None
    assert _municipality(None) is None


def test_clean_county_blank():
    assert _clean_county("") is None
    assert _clean_county(None) is None


# ---- address / money / date ----

def test_clean_address_strips_warning_glyph():
    assert _clean_address("⚠️ 210 Woodlawn St, West End, NC 27376") == (
        "210 Woodlawn St, West End, NC 27376"
    )


def test_clean_money():
    assert _clean_money("$45,000.00") == 45000.0
    assert _clean_money("n/a") is None
    assert _clean_money("To be announced.") is None
    assert _clean_money(None) is None


def test_parse_date():
    d = _parse_date("8/4/2026 5:00 PM")
    assert d is not None and (d.year, d.month, d.day) == (2026, 8, 4)
    assert _parse_date("n/a") is None
    assert _parse_date("") is None


# ---- status filter ----

def test_dead_statuses():
    assert _is_dead("Redeemed")
    assert _is_dead("Sale Confirmed")
    assert _is_dead("Sale Confirmed / Deed Recorded")


def test_live_statuses_survive():
    for status in (
        "Pending Confirmation",
        "Upset Bidding in Progress",
        "Courthouse Sale",
        "Resale Pending",
        "Stayed by Bankruptcy",
    ):
        assert not _is_dead(status)


def test_dead_rows_are_dropped(rows, listings):
    emitted = {li.auction_status for li in listings}
    assert "Redeemed" not in emitted
    assert "Sale Confirmed" not in emitted
    assert "Sale Confirmed / Deed Recorded" not in emitted
    assert len(listings) < len(rows)


def test_empty_pad_row_dropped():
    assert _row_to_listing(
        {"office": "", "parcel": "", "status": "", "addr": ""}, SLUG
    ) is None


# ---- row -> Listing ----

def test_all_listings_tagged_nc_tax_sale(listings):
    assert listings
    for li in listings:
        assert li.state == "NC"
        assert li.listing_type.value == "tax_sale"
        assert li.foreclosure_process == "tax"
        assert li.source == SLUG


def test_address_split_into_street_city_zip(listings):
    li = next(x for x in listings if x.parcel_id == "00025637")
    assert li.county == "Moore"
    assert li.street_address == "210 Woodlawn St"
    assert li.city == "West End"
    assert li.zip_code == "27376"


def test_upset_row_carries_deadline_and_status(listings):
    li = next(x for x in listings if x.parcel_id == "0021388")
    assert li.county == "Guilford"
    assert li.auction_status == "Upset Bidding in Progress"
    assert li.upset_bid_deadline is not None
    assert li.raw["zls"]["current_bid"] == "$32,029.51"


def test_upset_row_marks_deadline_as_published_so_generic_enrichment_skips_it():
    """Fixed 2026-10-04: the grid's "Upset Bidding Deadline" column is a
    real, site-published date, but without raw["upset_bid"]["source"] =
    "published", enrichment_upset_bid.py's generic NC sale_date+10-day rule
    would silently overwrite it with a weaker derived guess."""
    row = {
        "office": "Guilford County Tax Office",
        "parcel": "0021388",
        "status": "Upset Bidding in Progress",
        "sale": "6/1/2026",
        "upset": "6/15/2026 5:00 PM",
        "current_bid": "$32,029.51",
        "addr": "⚠️ 100 Main St, Greensboro, NC 27401",
    }
    li = _row_to_listing(row, SLUG)
    assert li is not None
    upset = li.raw.get("upset_bid")
    assert upset is not None
    assert upset["source"] == "published"
    assert upset["deadline_iso"].startswith("2026-06-15")
    assert li.upset_bid_deadline.strftime("%Y-%m-%d") == "2026-06-15"


def test_row_without_upset_date_has_no_upset_bid_raw_key():
    row = {
        "office": "Jones County Tax Office",
        "parcel": "4478-83-5588-00",
        "status": "Courthouse Sale",
        "sale": "7/1/2026",
        "opening_bid": "$4,957.42",
        "addr": "⚠️ 1 Main St, Trenton, NC 28585",
    }
    li = _row_to_listing(row, SLUG)
    assert li is not None
    assert "upset_bid" not in li.raw
    assert li.upset_bid_deadline is None


def test_courthouse_sale_row_carries_opening_bid(listings):
    li = next(x for x in listings if x.parcel_id == "4478-83-5588-00")
    assert li.county == "Jones"
    assert li.opening_bid == 4957.42
    assert li.sale_date is not None


def test_municipal_row_keeps_municipality_in_raw(listings):
    li = next(
        x for x in listings if (x.raw.get("zls") or {}).get("municipality") == "Laurinburg"
    )
    # Laurinburg is out-of-footprint, so no county is derivable — but the
    # collecting municipality must be preserved rather than mislabelled as one.
    assert li.county is None
    assert li.raw["zls"]["tax_office"] == "City of Laurinburg"
    assert li.city == "Laurinburg"


def test_no_footprint_counties_in_current_capture(listings):
    """Documents the cross-check result: ZLS adds nothing to the 11-county
    WNC footprint. If this ever starts failing, ZLS has expanded west and the
    coverage note in the module docstring needs updating."""
    footprint = {
        "Rutherford", "Cleveland", "Henderson", "Polk", "Gaston", "Buncombe",
        "Transylvania", "McDowell", "Lincoln", "Mitchell", "Burke",
    }
    assert not ({li.county for li in listings} & footprint)


# ---- links found on the 2026-10-01 re-audit: Google Maps coords + GIS url ----

def test_latlng_parsed_from_google_maps_place_url():
    """The Address column links to a Google Maps place URL that embeds exact
    coordinates in its path -- previously completely unused (0/207 live rows
    had latitude/longitude before this fix)."""
    url = (
        "https://www.google.com/maps/place/210+Woodlawn+St,+West+End,+NC+27376/"
        "@35.2451071,-79.5659757,19z/data=!4m6!3m5"
    )
    lat, lng = _latlng_from_maps_url(url)
    assert lat == 35.2451071
    assert lng == -79.5659757


def test_latlng_from_maps_url_handles_missing_or_malformed():
    assert _latlng_from_maps_url(None) == (None, None)
    assert _latlng_from_maps_url("") == (None, None)
    assert _latlng_from_maps_url("https://example.com/not-a-maps-link") == (None, None)


def test_row_to_listing_sets_latitude_longitude_from_maps_url():
    row = {
        "office": "Moore County Tax Office",
        "parcel": "00025637",
        "status": "Pending Confirmation",
        "sale": "6/8/2026",
        "addr": "⚠️ 210 Woodlawn St, West End, NC 27376",
        "maps_url": (
            "https://www.google.com/maps/place/210+Woodlawn+St/"
            "@35.2451071,-79.5659757,19z/data=!4m6"
        ),
    }
    li = _row_to_listing(row, SLUG)
    assert li is not None
    assert li.latitude == 35.2451071
    assert li.longitude == -79.5659757
    assert li.raw["zls"]["maps_url"] == row["maps_url"]


def test_row_to_listing_captures_parcel_gis_url_and_tax_office_url():
    row = {
        "office": "Moore County Tax Office",
        "tax_office_url": "https://www.moorecountync.gov/202/Tax",
        "parcel": "00025637",
        "parcel_gis_url": "https://gis.moorecountync.gov/mooreinfo2010/Parcel.aspx?PARID=00025637",
        "status": "Pending Confirmation",
        "addr": "⚠️ 210 Woodlawn St, West End, NC 27376",
    }
    li = _row_to_listing(row, SLUG)
    assert li is not None
    assert li.raw["zls"]["parcel_gis_url"] == row["parcel_gis_url"]
    assert li.raw["zls"]["tax_office_url"] == row["tax_office_url"]


def test_row_without_maps_url_leaves_latlng_none():
    """Regression guard: a row missing the new optional keys (the shape every
    pre-2026-10-01 fixture row has) must not crash and must leave
    latitude/longitude unset rather than inventing a value."""
    row = {
        "office": "Guilford County Tax Office",
        "parcel": "0021388",
        "status": "Upset Bidding in Progress",
        "addr": "⚠️ 100 Main St, Greensboro, NC 27401",
    }
    li = _row_to_listing(row, SLUG)
    assert li is not None
    assert li.latitude is None and li.longitude is None


# ---- BaseScraper metadata ----

def test_scraper_metadata():
    s = Zacchaeus()
    assert s.slug == "law_firms.zacchaeus"
    assert s.category == "law_firm"
    assert s.requires_render is True
    assert s.requires_apify is False
