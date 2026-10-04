"""Horry County SC Forfeited Land Commission (FLC) xlsx parser.

Row values below are taken from the real live 2025-flc-list-92926.xlsx
workbook (fetched 2026-10-04), not hand-built, reproducing the two-section
(REAL ESTATE / MOBILE HOMES ONLY) layout and the exact header-token spelling
quirks (e.g. "DESCRIPTON" with no 'I') the real file carries.

WHY test_parses_bids_received_and_bidding_closed EXISTS
    The live header row carries a "BIDS RECEIVED" column `_header_map` never
    matched, and "LAST DAY TO BID" is sometimes the literal text "BIDDING
    CLOSED" instead of a date serial — both silently dropped before the
    2026-10-04 fix. See the module docstring's "BIDS RECEIVED /
    'BIDDING CLOSED'" note.
"""
from __future__ import annotations

from foreclosure_scraper.models import PropertyKind
from foreclosure_scraper.scrapers.counties_sc.horry_flc import _discover_xlsx_url, _parse_listings
from tests._xlsx_fixture import build_xlsx

SLUG = "counties_sc.horry_flc"
URL = "https://www.horrycountysc.gov/media/f43cjkfh/2025-flc-list-92926.xlsx"

HEADER_REAL_ESTATE = {
    0: "PIN", 1: "ITEM #", 2: "TAXPAYER", 3: "NEW OWNER", 4: "DESCRIPTON",
    5: "POSSIBLE SITUS ADDRESS", 6: "MARKET IMP", 7: "TAX OWED AT TIME OF SALE",
    8: "MINIMUM BID", 9: "BIDS RECEIVED", 10: "LAST DAY TO BID",
    11: "DATE REDEMPTION ENDS",
}

ROWS = [
    {0: "2025 FLC LIST"},
    {0: "REAL ESTATE"},
    HEADER_REAL_ESTATE,
    # No bid yet, no closed status — the common case.
    {0: "39107020005", 1: "140", 2: "ALKASSAR, SHERIF", 4: "MARY A LEWIS LT 1 BL G",
     5: "4711 EYERLY ST, North Myrtle Beach, SC 29582", 6: "27714", 7: "4037.26",
     8: "4942.849", 11: "46358"},
    # One bid received, a real LAST DAY TO BID date serial.
    {0: "42700000016", 1: "6639", 2: "HIGHLAND WOODS HOA INC",
     4: "HIGHLAND WOODS O.S/PND/WETLD,BUFFER",
     5: "TBD BURCALE RD, Myrtle Beach, SC 29579", 6: "9200", 7: "503.72",
     8: "879.278", 9: "1", 10: "46310", 11: "46358"},
    # Two bids received AND bidding already closed (literal text, not a serial).
    {0: "36808010099", 1: "10384", 2: "MULDROW, MOSES E III",
     4: "MCCRAY COURT COMMON AREA-PHASE 6", 5: "1020 CREEL ST, Conway, SC 29527",
     6: "140", 7: "911.48", 8: "1348.202", 9: "2", 10: "BIDDING CLOSED", 11: "46358"},
    {0: "MOBILE HOMES ONLY (LAND NOT INCLUDED)"},
    HEADER_REAL_ESTATE,
    {0: "99800048186", 1: "11900", 2: "GILES, SOME OWNER",
     4: "16 x 66 93 GILES/28110020008", 6: "0", 7: "250.00", 8: "275.00",
     9: "1", 11: "46358"},
]


def test_discover_xlsx_url_prefers_highest_year():
    html = (
        '<a href="/media/om1d2bwo/2024-flc-list-42126.xlsx">2024 FLC LIST</a>'
        '<a href="/media/f43cjkfh/2025-flc-list-92926.xlsx">2025 FLC List</a>'
    )
    assert "92926" in _discover_xlsx_url(html)


def test_parses_real_estate_and_mobile_home_sections():
    out = _parse_listings(build_xlsx(ROWS), SLUG, URL)
    assert len(out) == 4
    kinds = {li.parcel_id: li.property_kind for li in out}
    assert kinds["39107020005"] == PropertyKind.UNKNOWN
    assert kinds["99800048186"] == PropertyKind.MOBILE


def test_mobile_home_row_surfaces_underlying_real_parcel():
    out = _parse_listings(build_xlsx(ROWS), SLUG, URL)
    mh = next(li for li in out if li.parcel_id == "99800048186")
    assert mh.raw["horry_flc"]["underlying_parcel"] == "28110020008"


def test_tbd_situs_keeps_street_address_none_but_city_state():
    out = _parse_listings(build_xlsx(ROWS), SLUG, URL)
    hoa = next(li for li in out if li.parcel_id == "42700000016")
    assert hoa.street_address is None
    assert hoa.city == "Myrtle Beach"


def test_parses_bids_received_and_bidding_closed():
    """The real fix under audit: BIDS RECEIVED and the literal 'BIDDING
    CLOSED' text must both be captured, not silently dropped."""
    out = _parse_listings(build_xlsx(ROWS), SLUG, URL)
    no_bid = next(li for li in out if li.parcel_id == "39107020005")
    one_bid = next(li for li in out if li.parcel_id == "42700000016")
    closed = next(li for li in out if li.parcel_id == "36808010099")

    assert no_bid.raw["horry_flc"]["bids_received"] is None
    assert no_bid.raw["horry_flc"]["bidding_closed"] is False
    assert no_bid.auction_status is None

    assert one_bid.raw["horry_flc"]["bids_received"] == 1
    assert one_bid.raw["horry_flc"]["bidding_closed"] is False
    assert one_bid.upset_bid_deadline is not None  # real LAST DAY TO BID serial
    assert one_bid.auction_status is None
    assert "1 bid received" in one_bid.description

    assert closed.raw["horry_flc"]["bids_received"] == 2
    assert closed.raw["horry_flc"]["bidding_closed"] is True
    # A status string, never a fake date — _excel_serial_to_dt must reject it.
    assert closed.upset_bid_deadline is None
    assert closed.auction_status == "bidding_closed"
    assert "bidding closed" in closed.description


def test_not_xlsx_bytes_returns_empty_without_raising():
    # _parse_listings assumes a real zip; callers (fetch()) guard the magic
    # bytes before calling it, but the function itself should not be the
    # thing that explodes on garbage input.
    import pytest
    with pytest.raises(Exception):
        _parse_listings(b"not a zip", SLUG, URL)
