"""Horry County SC delinquent-tax list (treasurer .xlsx).

No test file existed for this scraper before the 2026-10-04 extraction-
completeness audit, despite it already correctly capturing all 5 real
columns on the live sheet (Item Number, PIN, Owner Name, New Owner Name,
Description) with no gap found. Row/header text below is taken from the
real live 081926 edition (4,952 rows, fetched 2026-10-04), not hand-built.
"""
from __future__ import annotations

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_sc.horry_delinquent_xlsx import (
    discover_url,
    header_facts,
    parse_workbook,
)
from tests._xlsx_fixture import build_xlsx

SLUG = "counties_sc.horry_delinquent_xlsx"
URL = "https://www.horrycountysc.gov/media/b5af14ce/delinquent-list-on-website-081926.xlsx"

# read_rows() (the shared stdlib xlsx reader this module uses) returns dense
# list[str] rows, not {col_idx: value} dicts -- build_xlsx() below still
# wants the dict shape, so ROWS is converted with dict(enumerate(row)) at
# each call site.
ROWS: list[list[str]] = [
    ["2026 DELINQUENT TAX SALE LIST AS OF 08/19/2026 (WILL BE UPDATED WEEKLY)"],
    ["ALL ITEMS ON THIS LIST WILL NOT BE SOLD, TAXPAYERS HAVE UNTIL 5:00 PM, "
     "MONDAY, NOVEMBER 30, 2026 TO PAY 2025 DELLINQUENT TAXES"],
    ["Item Number", "PIN", "Owner Name", "New Owner Name", "Description"],
    ["00004", "39307010208", "A&K ENTERPRISES LLC", "", "ROYALE PALMS HPR PH I UNIT 301"],
    ["00006", "44305030067", "AAA CAPITAL LLC", "", "HOTEL SEC LTS 17-18 BL 24"],
    # A mobile-home account (998-prefixed PIN) with an owner-change row.
    ["00500", "99800082667", "OLD OWNER NAME", "NEW OWNER NAME", "14X66 81 FLIN STK#132021"],
]


def _xlsx_bytes() -> bytes:
    return build_xlsx([dict(enumerate(row)) for row in ROWS])


def test_header_facts_parses_as_of_pay_by_and_tax_year():
    facts = header_facts(ROWS)
    assert facts["as_of"].date().isoformat() == "2026-08-19"
    assert facts["pay_by"].date().isoformat() == "2026-11-30"
    assert facts["tax_year"] == 2025


def test_parses_real_rows_with_both_columns_already_captured():
    out = parse_workbook(_xlsx_bytes(), URL)
    assert len(out) == 3
    akc = next(li for li in out if li.parcel_id == "39307010208")
    assert akc.owner_name == "A&K ENTERPRISES LLC"
    assert akc.listing_type == ListingType.TAX_LIEN  # no sale date on the sheet
    assert akc.state == "SC" and akc.county == "Horry"
    # The sheet genuinely has no amount/situs — confirmed live 2026-10-04,
    # not a parsing gap.
    assert akc.street_address is None


def test_mobile_home_pin_sets_property_kind_and_new_owner_leads():
    out = parse_workbook(_xlsx_bytes(), URL)
    mh = next(li for li in out if li.parcel_id == "99800082667")
    assert mh.property_kind == PropertyKind.MOBILE
    # The sheet says ownership changed since billing — the CURRENT holder
    # should lead, not the originally-billed name.
    assert mh.owner_name == "NEW OWNER NAME"
    assert mh.raw["horry_delinquent_xlsx"]["billed_owner"] == "OLD OWNER NAME"
    assert "owner changed" in mh.description


def test_discover_url_picks_the_newest_dated_link():
    html = (
        '<a href="/media/aaa/delinquent-list-on-website-072326.xlsx">older</a>'
        '<a href="/media/b5af14ce/delinquent-list-on-website-081926.xlsx">newer</a>'
    )
    assert "081926" in discover_url(html)


# --- 2026-10-07 extraction audit: the October 2026 editions split the list into two
# workbooks and added an FLC Bid Amount column. Names below are made up. ---

import asyncio

from foreclosure_scraper.scrapers.counties_sc import horry_delinquent_xlsx as hry

OCT_RE_ROWS: list[list[str]] = [
    ["2026 REAL ESTATE DELINQUENT TAX SALE LIST AS OF 10/05/2026"],
    ["Item Number", "PIN", "Owner Name", "New Owner Name", "Description", "FLC Bid Amount"],
    ["00010", "10000000001", "SAMPLE HOLDINGS LLC", "", "TEST SUBDIVISION LOT 1", "1,234.56"],
    ["00011", "10000000002", "DOE JANE Q", "ROE RICHARD", "TEST SUBDIVISION LOT 2", "987.65"],
]
OCT_MH_ROWS: list[list[str]] = [
    ["2026 MOBILE HOME DELINQUENT TAX SALE LIST AS OF 10/01/2026 (MOBILE HOMES ONLY)"],
    ["Item Number", "PIN", "Owner Name", "New Owner Name", "Description", "FLC Bid Amount"],
    ["14000", "99800000001", "EXAMPLE PAT", "", "10000000003 16X66 21 TEST", "500.00"],
]
OCT_PAGE = (
    '<a href="https://www.horrycountysc.gov/media/aa/2026-real-estate-delinquent-list-10052026.xlsx">re</a>'
    '<a href="https://www.horrycountysc.gov/media/bb/2026-mobile-home-delinquent-list-100126.xlsx">mh</a>'
    '<a href="/media/cc/delinquent-list-on-website-081926.xlsx">old combined</a>'
)


def _wb(rows):
    return build_xlsx([dict(enumerate(r)) for r in rows])


def test_an_eight_digit_date_stamp_is_read_as_a_date():
    assert hry._stamp("x-10052026.xlsx") == "20261005"
    assert hry._stamp("x-100126.xlsx") == "20261001"
    assert hry._stamp("no-stamp.xlsx") == ""


def test_both_current_workbooks_are_discovered_and_the_stale_combined_one_dropped():
    urls = hry.discover_urls(OCT_PAGE)
    assert len(urls) == 2
    assert "real-estate" in urls[0] and "mobile-home" in urls[1]
    assert hry.discover_url(OCT_PAGE) == urls[0]


def test_the_flc_bid_amount_is_captured():
    out = parse_workbook(_wb(OCT_RE_ROWS), "https://example.invalid/re.xlsx")
    by = {li.parcel_id: li for li in out}
    b = by["10000000001"].raw["horry_delinquent_xlsx"]
    assert b["flc_bid_amount"] == 1234.56 and b["amount_on_sheet"] is True
    assert by["10000000001"].opening_bid == 1234.56
    assert b["sale_list_year"] == 2026 and b["list_kind"] == "real_estate"
    assert b["as_of"] == "2026-10-05"
    assert by["10000000002"].owner_name == "ROE RICHARD"


def test_an_old_sheet_without_the_column_still_says_no_amount():
    out = parse_workbook(_xlsx_bytes(), URL)
    assert all(li.raw["horry_delinquent_xlsx"]["amount_on_sheet"] is False for li in out)
    assert all(li.opening_bid is None for li in out)


def test_fetch_reads_both_workbooks(monkeypatch):
    seen = []

    async def fake_text(url, **kw):
        return OCT_PAGE

    async def fake_bytes(url, **kw):
        seen.append(url)
        return _wb(OCT_MH_ROWS if "mobile-home" in url else OCT_RE_ROWS)

    monkeypatch.setattr(hry, "get_text", fake_text)
    monkeypatch.setattr(hry, "get_bytes", fake_bytes)
    rows = asyncio.run(hry.HorryDelinquentXlsx().fetch())
    assert len(seen) == 2
    assert {li.parcel_id for li in rows} == {"10000000001", "10000000002", "99800000001"}
    mh = next(li for li in rows if li.parcel_id == "99800000001")
    assert mh.property_kind == PropertyKind.MOBILE
    assert mh.raw["horry_delinquent_xlsx"]["list_kind"] == "mobile_home"


def test_the_flc_bid_reaches_tax_owed():
    from foreclosure_scraper import enrichment_tax_owed as t
    assert t._SOURCES["horry_delinquent_xlsx"][1] == "flc_bid_amount"
