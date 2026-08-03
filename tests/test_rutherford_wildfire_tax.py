"""Unit tests for the Sturgis/Avalon Wildfire records scraper (Rutherford NC).

The fixture is a real page-1 payload captured 2026-08-03 from
``POST /data/<client>/Wildfire/Records`` with facets
``Status=Unpaid, Type=Property, Years=2016..2025``, trimmed to six records and
with one record duplicated onto an earlier tax year so the multi-year aggregate
path is exercised. No network.

The scraper itself is robots-walled off by default (both API hosts publish
``Disallow: /``); these tests cover the guard and the parse, which are the parts
that have to be right the day the wall lifts.
"""
import json
from pathlib import Path

from foreclosure_scraper.scrapers.counties_nc import rutherford_wildfire_tax as m

FIX = Path(__file__).parent / "fixtures"
_PAYLOAD = json.loads((FIX / "rutherford_wildfire_records_page1.json").read_text())
_RECORDS = _PAYLOAD["Records"]


def _parsed():
    return m._records_to_listings(_RECORDS, "u")


# --------------------------------------------------------------------------- #
# robots guard — the reason this source is a compliant no-op today
# --------------------------------------------------------------------------- #

_LIVE_ROBOTS = "User-agent: *\nDisallow: /\n"


def test_live_robots_blocks_the_records_path():
    """This is the exact body served by d1ebsyxxbc7tep.cloudfront.net and
    avalon.sturgiswebservices.com on 2026-08-03."""
    assert m._path_disallowed(_LIVE_ROBOTS, "/data/abc/Wildfire/Records") is True


def test_a_relaxed_robots_unblocks_it_without_a_code_change():
    body = "User-agent: *\nDisallow: /\nAllow: /data/\n"
    assert m._path_disallowed(body, "/data/abc/Wildfire/Records") is False


def test_root_only_allow_still_blocks_the_api():
    body = "User-agent: *\nAllow: /$\nDisallow: /\n"
    assert m._path_disallowed(body, "/") is False
    assert m._path_disallowed(body, "/data/abc/Wildfire/Records") is True


def test_empty_robots_allows():
    assert m._path_disallowed("", "/data/abc/Wildfire/Records") is False


def test_named_agent_group_is_not_our_group():
    body = "User-agent: Googlebot\nDisallow: /\n"
    assert m._path_disallowed(body, "/data/abc/Wildfire/Records") is False


# --------------------------------------------------------------------------- #
# endpoint discovery
# --------------------------------------------------------------------------- #

def test_endpoint_discovered_from_the_spa_shell():
    html = ('<script type="text/javascript" src="//d1ebsyxxbc7tep.cloudfront.net/js/'
            '5b88e44b-0038-4361-8c53-7ce1343ad3ad/1.js"></script>')
    assert m._discover_endpoint(html) == (
        "https://d1ebsyxxbc7tep.cloudfront.net",
        "5b88e44b-0038-4361-8c53-7ce1343ad3ad",
    )


def test_endpoint_falls_back_when_the_shell_changes():
    assert m._discover_endpoint("<html></html>") == (
        m.DEFAULT_API_HOST, m.DEFAULT_CLIENT_ID)


# --------------------------------------------------------------------------- #
# facets / year window
# --------------------------------------------------------------------------- #

def test_current_bill_year_is_excluded_from_the_delinquent_window():
    """NC bills for year Y go delinquent 6 Jan of Y+1, so TY2026 'Unpaid' is
    66,578 not-yet-due bills, not distress."""
    import datetime
    years = m._delinquent_years(datetime.date(2026, 8, 3))
    assert years[0] == 2025
    assert 2026 not in years
    assert len(years) == m.YEARS_BACK


def test_facets_shape_matches_the_spa():
    f = m._facets([2025, 2024])
    assert f["Status"] == {"Unpaid": True}
    assert f["Type"] == {"Property": True}
    assert f["Years"] == {"2025": True, "2024": True}


# --------------------------------------------------------------------------- #
# record -> Listing
# --------------------------------------------------------------------------- #

def test_only_real_estate_rows_become_leads():
    """IND (personal) and BUS (business personal property) ride the same
    'Property' facet but are not land; an REI row with no parcel is unusable."""
    out = _parsed()
    assert {li.parcel_id for li in out} == {"232588", "1638529"}


def test_amounts_sum_across_tax_years_into_one_parcel_lead():
    by = {li.parcel_id: li for li in _parsed()}
    li = by["1638529"]
    assert li.judgment_amount == 136.76          # 36.76 (TY2025) + 100.00 (TY2024)
    assert li.raw["rutherford_wildfire"]["tax_years"] == [2025, 2024]
    assert li.raw["rutherford_wildfire"]["bill_count"] == 2


def test_amount_owed_is_first_class_and_never_an_opening_bid():
    for li in _parsed():
        assert li.judgment_amount and li.judgment_amount > 0
        assert li.raw["rutherford_wildfire"]["amount_owed"] == li.judgment_amount
        assert li.opening_bid is None


def test_outside_law_firm_flag_is_promoted():
    by = {li.parcel_id: li for li in _parsed()}
    li = by["232588"]
    raw = li.raw["rutherford_wildfire"]
    assert raw["outside_law_firm"] is True
    assert raw["advertised"] is True
    assert "OUTSIDE LAW FIRM" in raw["flags"]
    assert li.auction_status == "referred_outside_counsel"


def test_advertised_only_parcel_reports_advertised():
    by = {li.parcel_id: li for li in _parsed()}
    li = by["1638529"]
    assert li.raw["rutherford_wildfire"]["outside_law_firm"] is False
    assert li.raw["rutherford_wildfire"]["advertised"] is True
    assert li.auction_status == "advertised"


def test_situs_address_is_split_even_without_a_comma():
    by = {li.parcel_id: li for li in _parsed()}
    li = by["232588"]
    assert li.street_address == "307 PEARTREE DR"
    assert li.city == "Lake Lure"
    assert li.zip_code == "28746"


def test_owner_mailing_address_is_captured_for_skip_trace():
    by = {li.parcel_id: li for li in _parsed()}
    mail = by["232588"].raw["rutherford_wildfire"]["owner_mailing"]
    assert mail["addr"] == "5500 FISH HATCHERY RD"
    assert (mail["city"], mail["state"], mail["zip"]) == ("PELION", "SC", "29123")


def test_assessed_real_value_lands_as_market_value():
    by = {li.parcel_id: li for li in _parsed()}
    assert by["232588"].market_value == 334900.0


def test_legal_description_backfills_when_situs_parses_as_an_address():
    by = {li.parcel_id: li for li in _parsed()}
    assert by["232588"].legal_description == "RIVERBEND HIGHLANDS LO524 PL10-122"


def test_listing_shape():
    for li in _parsed():
        assert li.listing_type.value == "tax_lien"
        assert li.foreclosure_process == "tax"
        assert (li.state, li.county) == ("NC", "Rutherford")
        assert li.raw["rutherford_wildfire"]["dateless"] is True


def test_nul_bytes_in_owner_names_are_scrubbed():
    """This feed writes a lone \\x00 into OwnerName1 on some rows."""
    assert m._clean("\x00") is None
    assert m._clean("SMITH, J\x00") == "SMITH, J"


def test_empty_input_is_not_an_error():
    assert m._records_to_listings([], "u") == []
