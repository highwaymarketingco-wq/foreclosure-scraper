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


# ---- BaseScraper metadata ----

def test_scraper_metadata():
    s = Zacchaeus()
    assert s.slug == "law_firms.zacchaeus"
    assert s.category == "law_firm"
    assert s.requires_render is True
    assert s.requires_apify is False
