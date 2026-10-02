"""Stokes County NC tax foreclosures via the Kania Law Firm statewide table.

HERMES sec 8 audit, 2026-10-01. The old scraper pointed at the county's own
foreclosures.php page, which carries no data at all -- just a paragraph
telling the reader to search Kania Law Firm's site instead. Fixed to pull
from Kania's real Ninja-Tables-backed AJAX endpoint and filter to Stokes.
"""
from __future__ import annotations

import json

from foreclosure_scraper.scrapers.counties_nc.stokes_delinquent_tax import (
    StokesDelinquentTax,
    _find_ajax_url,
    parse_rows,
)

# Trimmed, field-faithful reproduction of a few live rows from the Kania
# Law Firm AJAX endpoint (read 2026-10-01): one real Stokes sale, one
# combined-parcel Rutherford sale (to prove county filtering AND multi-value
# address/parcel splitting both work), and one "sale date not yet set" row.
SAMPLE_ROWS = [
    {"value": {
        "county": "Stokes", "address": "1057 Mcintosh Lane, Pinnacle",
        "parcel": "597501469717",
        "saledatetime": "<span class='red'>Sale date not yet set</span>",
        "openingbid": "", "currentbid": "", "closedate": "",
        "propertytype": "Residential Home", "courtfile": "26CV000616-840",
        "ourfile": "25298", "salestatus": "", "___id___": 45447,
    }},
    {"value": {
        "county": "Rutherford",
        "address": "147 Rocky Mountain Dr S, Lake Lure<br />153 Mountaintop Pkwy, Lake Lure",
        "parcel": "1641052<br />1646327",
        "saledatetime": "<span class='red'>Sale date not yet set</span>",
        "openingbid": "", "currentbid": "", "closedate": "",
        "propertytype": "Residential Vacant Lot", "courtfile": "24CVD001334-800",
        "ourfile": "23106", "salestatus": "", "___id___": 45442,
    }},
    {"value": {
        "county": "Stokes", "address": "(0000041) NC 90 HWY E, Stony Point",
        "parcel": "0000041",
        "saledatetime": "10/13/2026 11:00:00 AM",
        "openingbid": "$22,400.00", "currentbid": "", "closedate": "10/23/2026",
        "propertytype": "Residential Vacant Lot", "courtfile": "25CV001557-840",
        "ourfile": "24097", "salestatus": "", "___id___": 45275,
    }},
]

SAMPLE_PAGE_HTML = (
    '<div id="footable_parent_216745" class="ninja_table_wrapper">'
    '<script>var opts = {"data_request_url":'
    '"https:\\/\\/kanialawfirm.com\\/wp-admin\\/admin-ajax.php?action='
    'wp_ajax_ninja_tables_public_action\\u0026table_id=216745\\u0026'
    'target_action=get-all-data\\u0026default_sorting=old_first\\u0026'
    'skip_rows=0\\u0026limit_rows=0\\u0026ninja_table_public_nonce=51009e94c7",'
    '"filtering":{"enabled":true}};</script></div>'
)


def test_filters_to_stokes_only():
    out = parse_rows(SAMPLE_ROWS, "Stokes", "http://x")
    assert len(out) == 2
    assert all(li.county == "Stokes" for li in out)


def test_real_street_address_and_parcel_captured():
    out = parse_rows(SAMPLE_ROWS, "Stokes", "http://x")
    by_case = {li.case_number: li for li in out}
    li = by_case["26CV000616-840"]
    assert li.street_address == "1057 Mcintosh Lane, Pinnacle"
    assert li.parcel_id == "597501469717"
    assert li.city == "Pinnacle"


def test_bare_parcel_paren_address_falls_back_to_legal_description():
    """'(0000041) NC 90 HWY E, Stony Point' has no house number -- it must
    not be fabricated into a street_address, matching this audit's broader
    finding that unbounded regexes turn labels/parcel-refs into fake
    addresses elsewhere in this codebase."""
    out = parse_rows(SAMPLE_ROWS, "Stokes", "http://x")
    li = next(li for li in out if li.case_number == "25CV001557-840")
    assert li.street_address is None
    assert "NC 90 HWY E" in (li.legal_description or "")
    assert li.opening_bid == 22400.0
    assert li.sale_date is not None


def test_sale_date_not_yet_set_parses_to_none_not_a_fake_date():
    out = parse_rows(SAMPLE_ROWS, "Stokes", "http://x")
    li = next(li for li in out if li.case_number == "26CV000616-840")
    assert li.sale_date is None


def test_combined_parcel_address_split_and_excluded_by_county_filter():
    """Rutherford's own combined-parcel row must not leak into a Stokes-only
    pull, but the <br/>-split parsing itself (exercised via a Rutherford
    filter) must keep every address/parcel value, not just the first."""
    out = parse_rows(SAMPLE_ROWS, "Rutherford", "http://x")
    assert len(out) == 1
    li = out[0]
    assert li.raw["stokes_delinquent_tax"]["addresses"] == [
        "147 Rocky Mountain Dr S, Lake Lure", "153 Mountaintop Pkwy, Lake Lure",
    ]
    assert li.raw["stokes_delinquent_tax"]["parcels"] == ["1641052", "1646327"]


def test_find_ajax_url_extracts_table_id_and_nonce():
    import asyncio
    url = asyncio.run(_find_ajax_url(SAMPLE_PAGE_HTML))
    assert url is not None
    assert "table_id=216745" in url
    assert "ninja_table_public_nonce=51009e94c7" in url
    assert "\\/" not in url  # unescaped


def test_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "counties_nc.stokes_delinquent_tax" in {s.slug for s in all_scrapers()}
    assert StokesDelinquentTax.slug == "counties_nc.stokes_delinquent_tax"
