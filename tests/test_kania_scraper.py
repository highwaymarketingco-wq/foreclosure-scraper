"""Pin the Kania Law Firm NC tax-foreclosure scraper.

Kania publishes every active tax-foreclosure parcel for ~25 NC counties in a
single WordPress "Ninja Tables" grid. The page HTML holds no rows; the rows
come from a free public admin-ajax JSON endpoint. These tests run against a
fixture captured from that live endpoint on 2026-07-31
(tests/fixtures/kania_ninja_rows.json), so the parser is pinned to the real
column names, the real ``<br />``-joined multi-parcel cells and the real
"Sale date not yet set" placeholder.

No live HTTP here — fetch() is two plain GETs and is smoked separately.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreclosure_scraper.models import PropertyKind
from foreclosure_scraper.scrapers.law_firms.kania import (
    DEFAULT_TABLE_ID,
    KaniaLawFirm,
    _clean_money,
    _pair_up,
    _parse_date,
    _split_address,
    _split_cell,
    extract_data_request_url,
    parse_rows,
)

SLUG = "law_firms.kania"
FIXTURE = Path(__file__).parent / "fixtures" / "kania_ninja_rows.json"


@pytest.fixture(scope="module")
def rows() -> list:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def footprint(rows) -> list:
    """Default behaviour: only the in-footprint NC counties are emitted."""
    return parse_rows(rows, SLUG)


# ---- cell helpers ----

def test_split_cell_splits_on_br():
    assert _split_cell("40313<br />39225") == ["40313", "39225"]
    assert _split_cell("40313<BR>39225") == ["40313", "39225"]


def test_split_cell_strips_tags_and_blanks():
    assert _split_cell("<span class='red'>Sale date not yet set</span>") == [
        "Sale date not yet set"
    ]
    assert _split_cell("") == []
    assert _split_cell(None) == []


def test_split_address_pulls_city():
    assert _split_address("243 Pleasant View Loop, Morganton") == (
        "243 Pleasant View Loop", "Morganton", None
    )


def test_split_address_strips_leading_parcel_parenthetical():
    """Kania prefixes some addresses with the parcel id: '(51411) Afton Dr'."""
    street, city, inline = _split_address("(51411) Afton Dr, Kings Mountain")
    assert street == "Afton Dr"
    assert city == "Kings Mountain"
    assert inline == "51411"


def test_split_address_trailing_comma_leaves_city_none():
    assert _split_address("0 Jack London Street,") == (
        "0 Jack London Street", None, None
    )


def test_split_address_rejects_placeholder():
    assert _split_address("Multiple Parcels") == (None, None, None)


def test_pair_up_broadcasts_single_address_over_many_parcels():
    assert _pair_up(["100 Main St"], ["1", "2", "3"]) == [
        ("100 Main St", "1"), ("100 Main St", "2"), ("100 Main St", "3")
    ]


def test_pair_up_pads_ragged_cells_instead_of_dropping():
    assert _pair_up(["a", "b", "c"], ["1"]) == [("a", "1"), ("b", ""), ("c", "")]


def test_pair_up_empty():
    assert _pair_up([], []) == []


# ---- money + date ----

def test_clean_money_parses_currency():
    assert _clean_money("$12,500.00") == 12500.0


def test_clean_money_blank_is_none():
    assert _clean_money("") is None
    assert _clean_money(None) is None


def test_clean_money_rejects_out_of_band_values():
    assert _clean_money("$0.50") is None            # stray fee
    assert _clean_money("$50,000,000.00") is None   # not a NC tax parcel


def test_parse_date_reads_sale_datetime():
    d = _parse_date("5/5/2026 11:00:00 AM")
    assert d is not None and (d.year, d.month, d.day, d.hour) == (2026, 5, 5, 11)


def test_parse_date_rejects_not_yet_set_placeholder():
    assert _parse_date("<span class='red'>Sale date not yet set</span>") is None
    assert _parse_date("") is None


# ---- row -> Listing ----

def test_fixture_parses_into_listings(footprint):
    assert footprint, "fixture produced no listings"
    for li in footprint:
        assert li.state == "NC"
        assert li.listing_type.value == "tax_sale"
        assert li.foreclosure_process == "tax"
        assert li.source == SLUG
        assert li.source_url.startswith("https://kanialawfirm.com/")


def test_county_comes_from_the_county_column(footprint):
    """The grid has an authoritative county column — never regex it out of
    free text (the old parser did, and tagged the firm's own office)."""
    assert {li.county for li in footprint} == {
        "Burke", "Cleveland", "Rutherford", "Lincoln"
    }


def test_coastal_counties_pass_the_parse_time_gate(rows):
    """Same gate the other statewide firm calendars use: footprint ∪ coastal,
    so the engine's oceanfront lane still gets to judge New Hanover rows."""
    from foreclosure_scraper.scrapers.law_firms._footprint import is_coastal

    assert is_coastal("New Hanover", "NC")
    assert not is_coastal("Mecklenburg", "NC")


def test_out_of_footprint_counties_dropped_by_default(footprint):
    counties = {li.county for li in footprint}
    assert "Mecklenburg" not in counties
    assert "Alexander" not in counties


def test_all_counties_env_emits_everything(rows, footprint, monkeypatch):
    monkeypatch.setenv("KANIA_ALL_COUNTIES", "1")
    out = parse_rows(rows, SLUG)
    counties = {li.county for li in out}
    assert "Mecklenburg" in counties
    assert "Alexander" in counties
    assert len(out) > len(footprint)


def test_multi_parcel_row_becomes_one_listing_per_parcel(footprint):
    """Court file 25CV002743-110 covers two Silver Creek Lane parcels."""
    same_case = [li for li in footprint if li.case_number == "25CV002743-110"]
    assert len(same_case) == 2
    assert {li.parcel_id for li in same_case} == {"40313", "39225"}
    assert {li.street_address for li in same_case} == {
        "7087 Silver Creek Lane", "7091 Silver Creek Lane"
    }


def test_four_parcel_row_expands_fully(footprint):
    four = [li for li in footprint if li.case_number == "26CV000454-110"]
    assert len(four) == 4
    assert {li.parcel_id for li in four} == {"32342", "32276", "9140", "9139"}


def test_multiple_parcels_placeholder_kept_as_case_level_lead(footprint):
    """'Multiple Parcels' has no per-property detail but is still a real
    Burke filing — keep it keyed on the court file rather than dropping it."""
    hits = [li for li in footprint if li.case_number == "25CV002596-110"]
    assert len(hits) == 1
    assert hits[0].county == "Burke"
    assert hits[0].parcel_id is None
    assert hits[0].street_address is None


def test_scheduled_sale_row_carries_bid_dates_and_case(footprint):
    li = next(x for x in footprint if x.parcel_id == "32724")
    assert li.county == "Burke"
    assert li.street_address == "578 E. Settings Blvd. NW"
    assert li.city == "Valdese"
    assert li.opening_bid == 12500.0
    assert li.sale_date is not None and li.sale_date.year == 2026
    assert li.sale_time == "11:00:00 AM"
    assert li.upset_bid_deadline is not None
    assert li.case_number == "25CVD001289-110"
    assert li.property_kind == PropertyKind.LAND  # "Residential Vacant Lot"


def test_unscheduled_rows_are_kept_with_no_sale_date(footprint):
    """~60% of Kania's table has no sale date yet. Those are the earliest
    leads and must survive the parser (main.DATELESS_OK_SOURCES then has to
    let them through)."""
    dateless = [li for li in footprint if li.sale_date is None]
    assert dateless
    for li in dateless:
        assert li.auction_status == "pending_sale_date"


def test_current_bid_and_our_file_stashed_in_raw(footprint):
    li = next(x for x in footprint if x.parcel_id == "32724")
    assert li.raw["kania"]["our_file"] == "23567"
    assert li.raw["kania"]["current_bid"] == 34728.75
    assert li.raw["kania"]["property_type"] == "Residential Vacant Lot"


def test_property_type_maps_to_property_kind(footprint):
    kinds = {li.property_kind for li in footprint}
    assert PropertyKind.SINGLE_FAMILY in kinds  # "Residential Home"
    assert PropertyKind.LAND in kinds           # "Residential Vacant Lot"


def test_inline_parenthetical_parcel_recovered(footprint):
    """Cleveland row '(51411) Afton Dr' — the parcel shows up both in the
    parcel cell and inline in the address text."""
    afton = [li for li in footprint if li.street_address == "Afton Dr"]
    assert len(afton) == 1
    assert afton[0].parcel_id == "51411"
    assert afton[0].county == "Cleveland"


def test_no_duplicate_listings(footprint):
    keys = [
        (li.county, li.parcel_id, li.street_address, li.case_number)
        for li in footprint
    ]
    assert len(keys) == len(set(keys))


def test_parse_rows_accepts_raw_json_text(rows):
    def key(listings):
        return [
            (li.county, li.parcel_id, li.street_address, li.case_number,
             li.opening_bid, li.sale_date)
            for li in listings
        ]

    assert key(parse_rows(json.dumps(rows), SLUG)) == key(parse_rows(rows, SLUG))


def test_parse_rows_survives_garbage():
    assert parse_rows("not json", SLUG) == []
    assert parse_rows({}, SLUG) == []
    assert parse_rows([], SLUG) == []
    assert parse_rows([{"nope": 1}], SLUG) == []


# ---- AJAX URL discovery ----

PAGE_SNIPPET = (
    '<table data-ninja_table_instance="ninja_table_instance_0" '
    'data-footable_id="216745" id="footable_216745"></table>'
    '<script>window[\'ninja_table_instance_0\'] = {"table_id":"216745",'
    '"data_request_url":"https:\\/\\/kanialawfirm.com\\/wp-admin\\/admin-ajax.php'
    '?action=wp_ajax_ninja_tables_public_action&table_id=216745'
    '&target_action=get-all-data&default_sorting=old_first&skip_rows=0'
    '&limit_rows=20&ninja_table_public_nonce=2085dc322e"}</script>'
)


def test_extract_data_request_url_unescapes_and_forces_all_rows():
    url = extract_data_request_url(PAGE_SNIPPET)
    assert url is not None
    assert url.startswith("https://kanialawfirm.com/wp-admin/admin-ajax.php")
    assert "table_id=216745" in url
    assert "target_action=get-all-data" in url
    assert "limit_rows=0" in url and "limit_rows=20" not in url
    assert "\\/" not in url


def test_extract_data_request_url_falls_back_to_footable_id():
    url = extract_data_request_url('<table data-footable_id="999111"></table>')
    assert url is not None and "table_id=999111" in url


def test_extract_data_request_url_none_when_absent():
    assert extract_data_request_url("<html><body>no table</body></html>") is None
    assert extract_data_request_url("") is None


# ---- BaseScraper metadata ----

def test_scraper_metadata():
    s = KaniaLawFirm()
    assert s.slug == "law_firms.kania"
    assert s.category == "law_firm"
    # Public JSON endpoint answers plain httpx — no browser tier needed.
    assert s.requires_render is False
    assert DEFAULT_TABLE_ID.isdigit()


def test_scraper_in_known_fixed():
    """Patch-run --all-fixed must include Kania so manual triggers pick up
    tax-foreclosure listings."""
    from scripts.patch_run_scrapers import KNOWN_FIXED  # noqa

    assert "law_firms.kania" in KNOWN_FIXED
