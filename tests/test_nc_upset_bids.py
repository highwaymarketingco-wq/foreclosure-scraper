"""NC upset-bid capture — pinned to saved fixtures of the real payloads.

Fixtures (captured live 2026-08-02):
  nc_upset_bids_kania_feed.json          — the NESTED Ninja Tables JSON. Every
      published column sits under row["value"]; a top-level read sees nothing,
      which is exactly the trap that made the old scraper return zero.
  nc_upset_bids_rutherford_inhouse.html  — county-prosecuted sale table.
  nc_upset_bids_rutherford_outside.html  — outside-counsel text blocks, the
      only source in the stack that publishes the OWNER of record.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from foreclosure_scraper.enrichment_upset_bid import enrich_upset_bid
from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.national.nc_upset_bids import (
    COUNTY_UPSET_PAGES,
    KANIA_AJAX_TEMPLATE,
    NCUpsetBids,
    _min_upset_bid,
    extract_data_request_url,
    feed_stats,
    parse_county_page,
    parse_county_table,
    parse_county_text_blocks,
    parse_kania_feed,
)

FIXTURES = Path(__file__).parent / "fixtures"
KANIA_FEED = FIXTURES / "nc_upset_bids_kania_feed.json"
INHOUSE = FIXTURES / "nc_upset_bids_rutherford_inhouse.html"
OUTSIDE = FIXTURES / "nc_upset_bids_rutherford_outside.html"

#: Pinned "today" so deadline/`in_window` assertions never rot.
NOW = datetime(2026, 8, 2)

INHOUSE_URL, OUTSIDE_URL = COUNTY_UPSET_PAGES[0][2], COUNTY_UPSET_PAGES[1][2]


@pytest.fixture(scope="module")
def feed() -> list:
    return json.loads(KANIA_FEED.read_text())


@pytest.fixture(scope="module")
def kania_rows(feed):
    return parse_kania_feed(feed, all_rows=False, now=NOW)


# --- the nested-shape trap --------------------------------------------------

def test_rows_are_nested_under_value(feed):
    """Guards the bug: county lives at row['value']['county'], not row['county']."""
    assert feed and all("value" in row for row in feed)
    assert not any("county" in row for row in feed)
    assert all("county" in row["value"] for row in feed)


def test_parses_the_nested_shape_not_the_top_level(feed):
    assert parse_kania_feed(feed, all_rows=True, now=NOW)
    # A flattened payload (what a naive top-level reader would build) yields 0,
    # which is what the old scraper effectively saw.
    flattened = [row["value"] for row in feed]
    assert parse_kania_feed(flattened, all_rows=True, now=NOW) == []


def test_garbage_payloads_do_not_raise():
    for payload in ("", "not json", "{}", [], [None, 3, {"value": "x"}]):
        assert parse_kania_feed(payload, now=NOW) == []


# --- coverage accounting ----------------------------------------------------

def test_feed_stats_reports_total_and_in_footprint(feed):
    stats = feed_stats(feed)
    assert stats["feed_rows_total"] == len(feed)
    # More counties in the feed than in our footprint — the point of reporting both.
    assert stats["counties_total"] > stats["counties_in_footprint"] > 0
    assert 0 < stats["rows_in_footprint"] < stats["feed_rows_total"]
    assert stats["with_current_bid"] > 0
    assert stats["with_upset_deadline"] > 0


def test_out_of_footprint_counties_are_dropped(feed, kania_rows):
    counties = {li.county for li in kania_rows}
    assert counties <= {"Rutherford", "Cleveland", "Lincoln", "Polk", "Burke",
                        "Henderson", "Gaston", "Transylvania", "McDowell",
                        "Mitchell", "Buncombe"}
    # Cherokee NC and Madison NC ride in the feed but are not NC footprint
    # counties (Cherokee is only in scope on the SC side).
    assert "Alexander" not in counties
    assert "Cherokee" not in counties


def test_all_rows_flag_widens_to_pre_sale_inventory(feed):
    posture_only = parse_kania_feed(feed, all_rows=False, now=NOW)
    everything = parse_kania_feed(feed, all_rows=True, now=NOW)
    assert len(everything) > len(posture_only)
    # Default keeps only rows with a live bid or a published close date.
    for li in posture_only:
        u = li.raw["upset_bid"]
        assert u["current_bid"] is not None or u["deadline_iso"] is not None


# --- the target property ----------------------------------------------------

def test_141_duncan_street_spindale_is_captured(kania_rows):
    hits = [li for li in kania_rows if "141 Duncan" in (li.street_address or "")]
    assert len(hits) == 1
    li = hits[0]
    assert li.county == "Rutherford"
    assert li.state == "NC"
    assert li.city == "Spindale"
    assert li.parcel_id == "1206540"
    assert li.case_number == "25CVD000199-800"
    assert li.opening_bid == 12000.0
    assert li.upset_bid_deadline == datetime(2026, 8, 6)
    # Sold 7/7 but still open to 8/6, so the sale datetime is withheld from the
    # model field and preserved in raw — see _effective_sale_date.
    assert li.raw["upset_bid"]["sale_datetime_iso"] == "2026-07-07T00:00:00"
    assert li.sale_date is None
    assert li.auction_status == "upset_bid_period"
    assert li.property_kind is PropertyKind.SINGLE_FAMILY
    u = li.raw["upset_bid"]
    assert u["current_bid"] == 46305.0
    assert u["source"] == "published"
    assert u["in_window"] is True
    assert u["days_remaining"] == 4


def test_239_florida_avenue_spindale_is_captured(feed):
    rows = parse_kania_feed(feed, all_rows=True, now=NOW)
    hits = [li for li in rows if "239 Florida" in (li.street_address or "")]
    assert len(hits) == 1
    assert hits[0].county == "Rutherford"


# --- upset economics as first-class fields ---------------------------------

def test_bid_economics_are_first_class(kania_rows):
    assert any(li.opening_bid for li in kania_rows)
    assert any(li.upset_bid_deadline for li in kania_rows)
    assert any(li.raw["upset_bid"]["current_bid"] for li in kania_rows)
    assert any(li.case_number for li in kania_rows)
    assert any(li.parcel_id for li in kania_rows)
    for li in kania_rows:
        assert li.listing_type is ListingType.TAX_SALE
        assert li.foreclosure_process == "tax"
        assert li.source == "national.nc_upset_bids"
        assert set(li.raw) == {"upset_bid"}


def test_status_reflects_whether_the_window_is_still_open(feed):
    """Same payload, read from two different days."""
    early = {li.parcel_id: li.auction_status
             for li in parse_kania_feed(feed, all_rows=True, now=datetime(2026, 8, 2))}
    late = {li.parcel_id: li.auction_status
            for li in parse_kania_feed(feed, all_rows=True, now=datetime(2026, 12, 1))}
    assert "upset_bid_period" in early.values()
    assert "upset_bid_period" not in late.values()
    assert "upset_bid_closed" in late.values()


def test_minimum_upset_is_derived_when_not_published():
    # NCGS §45-21.27: raise by 5%, floor of $750 in absolute terms.
    assert _min_upset_bid(46305.0) == 48620.25       # 5% governs
    assert _min_upset_bid(1000.0) == 1750.0          # $750 floor governs
    assert _min_upset_bid(None) is None
    assert _min_upset_bid(0) is None


def test_published_minimum_upset_wins_over_the_derived_one():
    rows = parse_county_text_blocks(OUTSIDE.read_text(), OUTSIDE_URL,
                                    "Rutherford", now=NOW)
    li = next(r for r in rows if "141 Duncan" in (r.street_address or ""))
    u = li.raw["upset_bid"]
    assert u["minimum_upset_bid"] == 48620.25          # printed by the county
    assert u["minimum_upset_bid_estimated"] is None    # so we do not guess


def test_derived_minimum_upset_matches_what_the_county_publishes():
    """Cross-check of the §45-21.27 formula against the clerk's own arithmetic.

    Rutherford prints both the current bid and the amount needed to upset it,
    so the published pairs are a free oracle for the derived figure.
    """
    rows = parse_county_text_blocks(OUTSIDE.read_text(), OUTSIDE_URL,
                                    "Rutherford", now=NOW)
    checked = 0
    for li in rows:
        u = li.raw["upset_bid"]
        if u["current_bid"] and u["minimum_upset_bid"]:
            assert _min_upset_bid(u["current_bid"]) == pytest.approx(
                u["minimum_upset_bid"], abs=0.02)
            checked += 1
    assert checked >= 4


def test_fold_drops_the_derived_estimate_once_a_real_one_arrives():
    from foreclosure_scraper.scrapers.national.nc_upset_bids import _fold
    kania = next(li for li in parse_kania_feed(json.loads(KANIA_FEED.read_text()),
                                               all_rows=True, now=NOW)
                 if li.parcel_id == "1206540")
    county = next(li for li in parse_county_text_blocks(
        OUTSIDE.read_text(), OUTSIDE_URL, "Rutherford", now=NOW)
        if li.parcel_id == "1206540")
    assert kania.raw["upset_bid"]["minimum_upset_bid_estimated"] is not None
    merged = _fold(kania, county)
    assert merged.raw["upset_bid"]["minimum_upset_bid"] == 48620.25
    assert merged.raw["upset_bid"]["minimum_upset_bid_estimated"] is None
    # The county's owner name folds in; Kania's sale datetime survives in raw.
    assert merged.owner_name == "Abrams, Christeen Logan"
    assert merged.raw["upset_bid"]["sale_datetime_iso"] == "2026-07-07T00:00:00"
    assert merged.raw["upset_bid"]["sale_date_withheld"] is True


def test_fold_prefers_the_address_that_has_a_house_number():
    from foreclosure_scraper.scrapers.national.nc_upset_bids import _fold
    kania = next(li for li in parse_kania_feed(json.loads(KANIA_FEED.read_text()),
                                               all_rows=True, now=NOW)
                 if li.parcel_id == "908440")
    county = next(li for li in parse_county_text_blocks(
        OUTSIDE.read_text(), OUTSIDE_URL, "Rutherford", now=NOW)
        if li.parcel_id == "908440")
    assert kania.street_address == "Harris Henrietta"        # no house number
    assert county.street_address == "0 Harris Henrietta Rd"
    assert _fold(kania, county).street_address == "0 Harris Henrietta Rd"


def test_placeholder_text_never_becomes_a_value(feed):
    for li in parse_kania_feed(feed, all_rows=True, now=NOW):
        # "Sale date not yet set" must not parse into a fake sale date, and
        # "Multiple Parcels" must not become a parcel id.
        assert (li.parcel_id or "").lower() not in ("multiple", "multiple parcels", "tbd")
        assert (li.street_address or "").lower() != "multiple parcels"


def test_multi_parcel_rows_expand_to_one_lead_each(feed):
    """One court file over several parcels -> one lead per parcel."""
    rows = parse_kania_feed(feed, all_rows=True, now=NOW)
    afton = [li for li in rows if li.case_number == "25CV003091-220"]
    assert {li.parcel_id for li in afton} == {"51411", "12005"}


# --- county page: HTML table shape -----------------------------------------

def test_county_table_parses_the_inhouse_list():
    rows = parse_county_table(INHOUSE.read_text(), INHOUSE_URL, "Rutherford", now=NOW)
    assert len(rows) >= 16
    assert all(li.county == "Rutherford" and li.state == "NC" for li in rows)
    by_parcel = {li.parcel_id: li for li in rows}

    sherwood = by_parcel["1210231"]
    assert sherwood.street_address == "0 Sherwood Pl"
    assert sherwood.city == "Spindale"
    assert sherwood.case_number == "24M236"
    assert sherwood.tax_value == 12000.0

    alabama = by_parcel["1201820"]
    assert alabama.street_address == "107 Alabama St"
    assert alabama.case_number == "26M38"
    assert alabama.tax_value == 6000.0


def test_county_table_refuses_to_invent_dates_from_season_text():
    rows = parse_county_table(INHOUSE.read_text(), INHOUSE_URL, "Rutherford", now=NOW)
    calhoun = next(li for li in rows if li.parcel_id == "1614173")
    # Sale Date column reads "Summer 2026" — kept as an operator hint only.
    assert calhoun.sale_date is None
    assert calhoun.upset_bid_deadline is None
    assert calhoun.auction_status == "pending_sale_date"
    assert calhoun.raw["upset_bid"]["sale_date_hint"] == "Summer 2026"
    # "tbd" in the Opening Bid column is not a bid.
    assert calhoun.opening_bid is None


def test_county_table_splits_comma_joined_parcels():
    rows = parse_county_table(INHOUSE.read_text(), INHOUSE_URL, "Rutherford", now=NOW)
    rock = [li for li in rows if li.case_number == "25M283"]
    assert {li.parcel_id for li in rock} == {"615595", "1603783"}


def test_county_table_generalizes_to_a_page_it_was_not_tuned_for():
    """Proof the table parser is generic, not Rutherford-shaped.

    Henderson's CMS emits <th> for EVERY cell — header and data alike — and
    names its columns differently ("Listing Owner's Name:", "Parcel #:",
    "Clerk of Court File #", "Estimated Opening Bid*"). A td-only read returns
    nothing here, which is the failure mode this fixture pins.
    """
    html = (FIXTURES / "nc_upset_bids_henderson_th_table.html").read_text()
    url = "https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales"
    rows = parse_county_table(html, url, "Henderson", now=NOW)
    assert len(rows) >= 15
    li = next(r for r in rows if r.parcel_id == "301249")
    assert li.owner_name == "CASE, GREGORY P HEIRS"
    assert li.case_number == "25M000267-440"
    assert li.opening_bid == 777.17
    assert li.legal_description.startswith("L#4 SEC B HUCKLEBERRY")
    assert li.county == "Henderson"


def test_county_table_ignores_tables_without_listing_columns():
    html = "<table><tr><th>Phone</th><th>Email</th></tr><tr><td>1</td><td>2</td></tr></table>"
    assert parse_county_table(html, INHOUSE_URL, "Rutherford", now=NOW) == []


# --- county page: text-block shape -----------------------------------------

def test_county_text_blocks_capture_owner_and_full_economics():
    rows = parse_county_text_blocks(OUTSIDE.read_text(), OUTSIDE_URL,
                                    "Rutherford", now=NOW)
    assert len(rows) >= 5
    li = next(r for r in rows if r.parcel_id == "1206540")
    assert li.street_address == "141 Duncan St"
    assert li.owner_name == "Abrams, Christeen Logan"
    assert li.case_number == "25CVD000199-800"
    assert li.upset_bid_deadline == datetime(2026, 8, 6)
    assert li.auction_status == "upset_bid_period"
    u = li.raw["upset_bid"]
    assert u["current_bid"] == 46305.0
    assert u["minimum_upset_bid"] == 48620.25
    assert u["our_file"] == "23516"


def test_county_text_blocks_handle_en_dash_and_hyphen_separators():
    """The county types some rows with '-' and some with '–'; both must parse."""
    rows = parse_county_text_blocks(OUTSIDE.read_text(), OUTSIDE_URL,
                                    "Rutherford", now=NOW)
    owners = {li.owner_name for li in rows}
    assert "Sexton, William Clyde Heirs; Sexton, Alice Heirs" in owners  # hyphen row
    assert "Taylor, Allen Steven" in owners                              # en-dash row


def test_county_text_blocks_read_opening_bid_for_not_yet_sold_parcels():
    rows = parse_county_text_blocks(OUTSIDE.read_text(), OUTSIDE_URL,
                                    "Rutherford", now=NOW)
    li = next(r for r in rows if r.parcel_id == "1201941")
    assert li.opening_bid == 12100.0
    assert li.raw["upset_bid"]["current_bid"] is None
    assert li.upset_bid_deadline is None


def test_parse_county_page_runs_both_shapes():
    """Shape is detected, not declared — the same entry point handles both pages."""
    table_page = parse_county_page(INHOUSE.read_text(), INHOUSE_URL, "Rutherford", now=NOW)
    text_page = parse_county_page(OUTSIDE.read_text(), OUTSIDE_URL, "Rutherford", now=NOW)
    assert {li.raw["upset_bid"]["feed"] for li in table_page} == {"county_table"}
    assert {li.raw["upset_bid"]["feed"] for li in text_page} == {"county_text_block"}


def test_county_parsers_survive_an_empty_page():
    for parser in (parse_county_table, parse_county_text_blocks, parse_county_page):
        assert parser("", INHOUSE_URL, "Rutherford", now=NOW) == []
        assert parser("<html><body><p>No sales scheduled.</p></body></html>",
                      INHOUSE_URL, "Rutherford", now=NOW) == []


# --- feed discovery ---------------------------------------------------------

def test_extract_data_request_url_unescapes_and_forces_all_rows():
    html = (r'{"data_request_url":"https:\/\/kanialawfirm.com\/wp-admin\/admin-ajax.php'
            r'?action=wp_ajax_ninja_tables_public_action&table_id=216745'
            r'&target_action=get-all-data&skip_rows=10&limit_rows=25"}')
    url = extract_data_request_url(html)
    assert url.startswith("https://kanialawfirm.com/wp-admin/admin-ajax.php")
    assert "limit_rows=0" in url and "skip_rows=0" in url


def test_extract_data_request_url_falls_back_to_footable_id():
    url = extract_data_request_url('<table data-footable_id="999111"></table>')
    assert url == KANIA_AJAX_TEMPLATE.format(table_id="999111")
    assert extract_data_request_url("") is None
    assert extract_data_request_url("<p>nothing here</p>") is None


# --- interaction with main._active_only ------------------------------------

def test_open_window_rows_survive_the_active_only_filter(kania_rows):
    """The regression this build exists to prevent.

    main._active_only drops NC rows whose sale_date is >14 days past, because
    it assumes the upset window is 10 days from the sale. Stacked upsets break
    that: measured live 2026-08-02, that filter discarded ALL 12 rows carrying
    a live current bid. Withholding the past sale date on open-window rows puts
    them on the dateless lane instead.
    """
    from foreclosure_scraper.main import _active_only
    live = [li for li in kania_rows
            if li.upset_bid_deadline and li.upset_bid_deadline >= NOW]
    assert live
    dropped = [li for li in live if not _active_only(li, 120, now=NOW)]
    assert dropped == [], [li.street_address for li in dropped]


def test_past_sale_with_open_window_withholds_the_sale_date(kania_rows):
    li = next(r for r in kania_rows if "141 Duncan" in (r.street_address or ""))
    assert li.sale_date is None          # withheld so the row is not aged out
    assert li.sale_time is None
    u = li.raw["upset_bid"]
    assert u["sale_date_withheld"] is True
    assert u["sale_datetime_iso"] == "2026-07-07T00:00:00"   # nothing lost


def test_future_sale_date_is_kept(kania_rows):
    """A sale still ahead is the actionable date and passes the filter as-is."""
    li = next(r for r in kania_rows if r.parcel_id == "1201941")   # sale 8/6
    assert li.sale_date == datetime(2026, 8, 6)
    assert li.raw["upset_bid"]["sale_date_withheld"] is False


def test_closed_window_keeps_its_sale_date_and_ages_out(feed):
    """Once the window shuts, the sale date is the story again."""
    rows = parse_kania_feed(feed, all_rows=True, now=datetime(2026, 12, 1))
    li = next(r for r in rows if "141 Duncan" in (r.street_address or ""))
    assert li.sale_date == datetime(2026, 7, 7)
    assert li.auction_status == "upset_bid_closed"
    assert li.raw["upset_bid"]["sale_date_withheld"] is False


# --- interaction with the derived-deadline enrichment ----------------------

def test_published_deadline_survives_the_derived_enrichment(kania_rows):
    """A stacked upset legitimately pushes the close date past sale_date + 10.

    enrichment_upset_bid derives deadline = sale_date + 10 days and clears
    anything outside that window. 141 Duncan sold 7/7 and is still open to
    8/6 — 30 days — so without the `source: published` guard the enrichment
    would null out a real, still-live deadline.
    """
    li = next(r for r in kania_rows if "141 Duncan" in (r.street_address or ""))
    sold = datetime.fromisoformat(li.raw["upset_bid"]["sale_datetime_iso"])
    assert (li.upset_bid_deadline - sold).days > 10  # the trap
    stats = enrich_upset_bid([li])
    assert stats["published_skipped"] == 1
    assert li.upset_bid_deadline == datetime(2026, 8, 6)
    assert li.raw["upset_bid"]["current_bid"] == 46305.0


def test_enrichment_still_processes_ordinary_listings(kania_rows):
    li = next(r for r in kania_rows if "141 Duncan" in (r.street_address or "")).model_copy(deep=True)
    li.raw = {}
    stats = enrich_upset_bid([li])
    assert stats["published_skipped"] == 0


# --- scraper wiring ---------------------------------------------------------

def test_scraper_registers_with_the_expected_slug():
    s = NCUpsetBids()
    assert s.slug == "national.nc_upset_bids"
    assert s.category == "upset_bid"


def test_slug_is_dateless_ok():
    """Most rows carry a close date but no scheduled sale date."""
    from foreclosure_scraper.main import DATELESS_OK_SOURCES
    assert "national.nc_upset_bids" in DATELESS_OK_SOURCES


def test_scraper_is_discovered_by_the_registry():
    """Auto-discovery is by module scan, so only the national package matters.

    Scoped to that package on purpose: `_registry.discover()` imports every
    scraper in the tree, so an unrelated module with a broken import would
    fail this test for reasons that have nothing to do with this source.
    """
    import importlib
    import inspect
    import pkgutil

    from foreclosure_scraper.base_scraper import BaseScraper

    pkg = importlib.import_module("foreclosure_scraper.scrapers.national")
    found = []
    for _, name, ispkg in pkgutil.iter_modules(pkg.__path__):
        if ispkg or name.startswith("_") or name != "nc_upset_bids":
            continue
        mod = importlib.import_module(f"{pkg.__name__}.{name}")
        found += [obj for _, obj in inspect.getmembers(mod, inspect.isclass)
                  if issubclass(obj, BaseScraper) and obj is not BaseScraper
                  and obj.__module__ == mod.__name__]
    assert found == [NCUpsetBids]
