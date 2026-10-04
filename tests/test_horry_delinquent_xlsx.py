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
