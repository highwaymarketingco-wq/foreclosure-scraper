"""Charleston tax-sale .xlsx and Horry delinquent .xlsx scrapers (added 2026-09-21), plus the
stdlib workbook reader they share.

Workbooks are built in memory with the same structure Excel writes (shared strings, numeric
cells, sparse rows), from the layouts read live. Names and PINs are invented and nothing is
written to disk.
"""
from __future__ import annotations

import asyncio
import io
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

import pytest

import foreclosure_scraper.scrapers.counties_sc.charleston_tax_sale_xlsx as chs
import foreclosure_scraper.scrapers.counties_sc.horry_delinquent_xlsx as hry
from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers import _xlsx_stdlib as xs


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def make_xlsx(rows: list[list], sheets: int = 1) -> bytes:
    """A minimal .xlsx: text cells go through sharedStrings, numbers stay numeric."""
    sst: list[str] = []

    def sid(t: str) -> int:
        if t not in sst:
            sst.append(t)
        return sst.index(t)

    body = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in enumerate(row):
            if v is None or v == "":
                continue
            ref = f"{_col(c)}{r}"
            if isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="s"><v>{sid(str(v))}</v></c>')
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet_xml = f'<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData>{"".join(body)}</sheetData></worksheet>'
    sst_xml = (f'<?xml version="1.0"?><sst xmlns="{ns}">'
               + "".join(f"<si><t>{escape(t)}</t></si>" for t in sst) + "</sst>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for n in range(1, sheets + 1):
            z.writestr(f"xl/worksheets/sheet{n}.xml", sheet_xml if n == 1 else
                       f'<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData/></worksheet>')
        z.writestr("xl/sharedStrings.xml", sst_xml)
    return buf.getvalue()


# --------------------------------------------------------------------------- reader

def test_reader_returns_dense_rows_with_blanks_and_numbers():
    data = make_xlsx([["a", "", "c"], [], ["x", 5, 2.5, "z"]])
    rows = xs.read_rows(data)
    assert rows[0] == ["a", "", "c"]
    assert rows[1] == []
    assert rows[2] == ["x", "5", "2.5", "z"]


def test_reader_rejects_a_non_xlsx():
    with pytest.raises(ValueError):
        xs.read_rows(b"<html>Access Denied</html>")


def test_reader_sheet_numbers_sort_numerically():
    """sheet10 must not sort before sheet2."""
    data = make_xlsx([["only"]], sheets=11)
    assert xs.read_rows(data, sheet=1) == [["only"]]
    assert xs.read_rows(data, sheet=11) == []


def test_header_index_finds_the_row_after_title_rows_case_insensitively():
    rows = [["A long title"], ["PIN", "Owner Name", "x"], ["1", "n", "y"]]
    i, cols = xs.header_index(rows, ("pin", "owner name"))
    assert i == 1 and cols["pin"] == 0 and cols["owner name"] == 1
    assert xs.header_index(rows, ("nope",)) is None


def test_excel_serial_dates():
    assert xs.excel_serial_to_date("46335") == datetime(2026, 11, 9)
    assert xs.excel_serial_to_date("BIDDING CLOSED") is None
    assert xs.excel_serial_to_date("5") is None and xs.excel_serial_to_date(None) is None


def test_cell_is_safe_on_short_rows():
    assert xs.cell(["a"], 3) == "" and xs.cell(["a"], None) == "" and xs.cell([" a "], 0) == "a"


# --------------------------------------------------------------------------- Charleston

CHS_TITLE = ("2026 Real Property Tax Sale Listing\nProperties will be sold in alphabetical order. "
             "Finalized lists will only be available the day of the tax sale, Monday,  "
             "November 9, 2026. You must register as a bidder.")
RP_HDR = ["PIN", "CLASS CODE", "OWNER", "SITUS ADDRESS", "CITY", "TAG", "ACREAGE", "TOTAL DUE", "APPRAISAL"]
RP_URL = chs.FALLBACK_XLSX[0]
MH_URL = chs.FALLBACK_XLSX[1]


def rp_book(extra=()):
    return make_xlsx([
        [CHS_TITLE], RP_HDR,
        ["4261000016", "101 - RESID-SFR", "1075 QUAIL DRIVE LLC", "1075 QUAIL DR", "CHARLESTON", "3-8", 0.45, 5082.49, 464700],
        ["4640000050", "990 - UNDEVELOPABLE", "107 BRIGADE STREET LLC", "North ROMNEY ST", "CHARLESTON", "7-1", 1.23, 798.2, 200],
        ["4261000016", "101 - RESID-SFR", "DUP ROW", "1 X ST", "CHARLESTON", "3-8", 1, 1, 1],
        ["not a pin", "", "JUNK", "", "", "", "", "", ""],
        *extra, [], [],
    ])


def test_charleston_rows_bind_by_header_and_take_the_sale_date_from_the_title():
    rows = chs.parse_workbook(rp_book(), RP_URL)
    assert [r.parcel_id for r in rows] == ["4261000016", "4640000050"]      # dup + junk dropped
    a, b = rows
    assert a.listing_type == ListingType.TAX_SALE and a.sale_date == datetime(2026, 11, 9)
    assert a.source == "counties_sc.charleston_tax_sale_xlsx"
    assert a.state == "SC" and a.county == "Charleston" and a.city == "CHARLESTON"
    assert a.street_address == "1075 QUAIL DR"
    assert a.owner_name == a.defendant == "1075 QUAIL DRIVE LLC"
    assert a.opening_bid == 5082.49 and a.market_value == 464700.0 and a.acreage == 0.45
    assert a.property_kind == PropertyKind.SINGLE_FAMILY
    assert a.foreclosure_process == "tax"
    assert a.raw["tax_owed"] == {"balance": 5082.49, "kind": "delinquent_tax",
                                 "source": "counties_sc.charleston_tax_sale_xlsx", "year": 2025,
                                 "basis": "own_record"}
    # A situs with no house number is not a street address; the road-only text is kept.
    assert b.street_address is None and b.legal_description == "North ROMNEY ST"
    assert b.property_kind == PropertyKind.LAND
    # The raw block reuses the PDF scraper's key and field names: it is the same list, and that
    # key is already in web_artifact.RAW_KEEP so it survives publish.
    blk = a.raw["charleston_delinquent_tax"]
    assert blk["pin"] == "4261000016" and blk["total_due"] == 5082.49 and blk["classcd"] == "101 - RESID-SFR"
    assert blk["dateless"] is False and blk["sale_date"] == "2026-11-09" and blk["list_xlsx"] == RP_URL
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert "charleston_delinquent_tax" in RAW_KEEP


def test_a_workbook_without_a_dated_title_is_a_standing_lien():
    data = make_xlsx([["2026 Real Property Tax Sale Listing"], RP_HDR,
                      ["4261000016", "101 - RESID-SFR", "X LLC", "1 A ST", "CHARLESTON", "3-8", 1, 10, 10]])
    (r,) = chs.parse_workbook(data, RP_URL)
    assert r.sale_date is None and r.listing_type == ListingType.TAX_LIEN


def test_the_mh_layout_is_a_different_column_order():
    hdr = ["PIN", "TAG", "OWNER 1", "OWNER 2", "DESCRIPTION", "SITUS ADDRESS", "CITY", "APPRAISAL", "TOTAL DUE"]
    data = make_xlsx([["2026 Mobile Home Tax Sale Listing ... Monday,  November 9, 2026."], hdr,
                      ["MH00050367", "8-2", "ROE JOHN SR", "ROE JANE", "1997 FLEETWOOD EAGLE", "8255 OLD JACKSONBORO RD",
                       "ADAMS RUN", 20600, "358.46000000000004"]])
    (r,) = chs.parse_workbook(data, MH_URL)
    assert r.parcel_id == "MH00050367" and r.property_kind == PropertyKind.MOBILE
    assert r.owner_name == "ROE JOHN SR ROE JANE"
    assert r.opening_bid == 358.46                        # float noise rounded
    assert r.market_value == 20600.0                      # appraisal is NOT read from TOTAL DUE
    assert "1997 FLEETWOOD EAGLE" in r.description
    assert r.raw["charleston_delinquent_tax"]["kind"] == "mobile_home"


def test_a_workbook_with_no_header_is_an_error_not_an_empty_list():
    with pytest.raises(ValueError):
        chs.parse_workbook(make_xlsx([["nothing", "here"]]), RP_URL)


def test_charleston_link_discovery_orders_rp_first_and_absolutises():
    html = ('<a href="/departments/delinquent-tax/files/tax_sale/MH-Tax-Sale-Listing.xlsx?v=994">m</a>'
            '<a href="https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/RP-Tax-Sale-Listing.xlsx?v=994">r</a>'
            '<a href="/x/RP-Tax-Sale-Listing.pdf">pdf</a>')
    urls = chs.discover_urls(html)
    assert len(urls) == 2 and "/RP-" in urls[0] and urls[1].startswith("https://www.charlestoncounty.gov/")


def test_the_charleston_scraper_falls_back_to_the_known_urls_and_survives_one_bad_file(monkeypatch):
    fetched = []

    async def fake_text(url, **kw):
        raise RuntimeError("landing page down")

    async def fake_bytes(url, **kw):
        fetched.append(url)
        if "MH-" in url:
            return b"<html>403</html>"                    # not an xlsx
        return rp_book()

    monkeypatch.setattr(chs, "get_text", fake_text)
    monkeypatch.setattr(chs, "get_bytes", fake_bytes)
    out = asyncio.run(chs.CharlestonTaxSaleXlsx().fetch())
    assert fetched == list(chs.FALLBACK_XLSX)
    assert len(out) == 2                                  # RP rows survive the MH failure


def test_the_charleston_limit_is_a_hard_cap(monkeypatch):
    async def fake_text(url, **kw):
        return ""

    async def fake_bytes(url, **kw):
        return rp_book()

    monkeypatch.setattr(chs, "get_text", fake_text)
    monkeypatch.setattr(chs, "get_bytes", fake_bytes)
    s = chs.CharlestonTaxSaleXlsx()
    s.limit = 1
    assert len(asyncio.run(s.fetch())) == 1


# --------------------------------------------------------------------------- Horry

HRY_ROWS = [
    ["2026 DELINQUENT TAX SALE LIST AS OF 08/19/2026 (WILL BE UPDATED WEEKLY)"],
    ["ALL ITEMS ON THIS LIST WILL NOT BE SOLD, TAXPAYERS HAVE UNTIL 5:00 PM, MONDAY, NOVEMBER 30, "
     "2026 TO PAY 2025 DELLINQUENT TAXES"],
    ["Item Number", "PIN", "Owner Name", "New Owner Name", "Description"],
    ["00004", "39307010208", "A&K ENTERPRISES LLC", "", "ROYALE PALMS HPR PH I         UNIT 301"],
    ["00007", "44306030075", "AAA CONSTRUCTION SERVICES LLC", "NEW BUYER LLC", "LAKEVIEW VILLAS BLDG 5 UN 101"],
    ["19805", "99800096171", "ZINK MINDY", "", "32700000023                   14X66 81 FLIN STK#132021"],
    ["00004", "39307010208", "DUP", "", "DUP"],
    ["bad", "n/a", "x", "", ""],
]


def test_horry_title_facts():
    f = hry.header_facts(HRY_ROWS)
    assert f["as_of"] == datetime(2026, 8, 19)
    assert f["pay_by"] == datetime(2026, 11, 30) and f["tax_year"] == 2025


def test_horry_rows_are_standing_liens_not_dated_sales():
    rows = hry.parse_workbook(make_xlsx(HRY_ROWS), hry.FALLBACK_XLSX)
    assert [r.parcel_id for r in rows] == ["39307010208", "44306030075", "99800096171"]
    a, b, c = rows
    assert all(r.listing_type == ListingType.TAX_LIEN and r.sale_date is None for r in rows)
    assert a.source == "counties_sc.horry_delinquent_xlsx"
    assert a.state == "SC" and a.county == "Horry" and a.owner_name == "A&K ENTERPRISES LLC"
    blk = a.raw["horry_delinquent_xlsx"]
    assert blk["pay_by_deadline"] == "2026-11-30" and blk["as_of"] == "2026-08-19"
    assert blk["item_number"] == "00004" and blk["amount_on_sheet"] is False
    assert "tax_owed" not in a.raw                        # the sheet carries no amount
    assert a.legal_description == "ROYALE PALMS HPR PH I UNIT 301"     # whitespace collapsed
    # The current owner leads when the sheet names a new one; the billed owner is kept.
    assert b.owner_name == "NEW BUYER LLC"
    assert b.raw["horry_delinquent_xlsx"]["billed_owner"] == "AAA CONSTRUCTION SERVICES LLC"
    assert "owner changed since billing" in b.description
    # A mobile home is recognised by its size string or 998 PIN.
    assert c.property_kind == PropertyKind.MOBILE and a.property_kind == PropertyKind.UNKNOWN
    assert c.raw["horry_delinquent_xlsx"]["land_parcel"] == "32700000023"


def test_horry_link_discovery_picks_the_newest_dated_file():
    summer = ('<a href="/media/aa/delinquent-list-on-website-081226.xlsx">old</a>'
              '<a href="/media/bb/delinquent-list-on-website-082626.xlsx">new</a>')
    assert hry.discover_url(summer).endswith("delinquent-list-on-website-082626.xlsx")
    # The filename is MMDDYY, so a January 2027 file must beat an August 2026 one even though
    # "01" sorts before "08" as text.
    assert hry.discover_url(summer + '<a href="/media/cc/delinquent-list-on-website-011227.xlsx">x</a>'
                            ).endswith("delinquent-list-on-website-011227.xlsx")
    assert hry.discover_url("<html>nothing</html>") is None
    assert hry.discover_url(summer).startswith("https://www.horrycountysc.gov/media/")


def test_the_horry_scraper_uses_the_discovered_link_and_falls_back(monkeypatch):
    seen = []

    async def fake_bytes(url, **kw):
        seen.append(url)
        return make_xlsx(HRY_ROWS)

    async def text_ok(url, **kw):
        return '<a href="/media/bb/delinquent-list-on-website-082626.xlsx">x</a>'

    async def text_bad(url, **kw):
        raise RuntimeError("down")

    monkeypatch.setattr(hry, "get_bytes", fake_bytes)
    monkeypatch.setattr(hry, "get_text", text_ok)
    assert len(asyncio.run(hry.HorryDelinquentXlsx().fetch())) == 3
    assert seen[-1].endswith("delinquent-list-on-website-082626.xlsx")
    monkeypatch.setattr(hry, "get_text", text_bad)
    asyncio.run(hry.HorryDelinquentXlsx().fetch())
    assert seen[-1] == hry.FALLBACK_XLSX


def test_a_failed_horry_download_is_an_empty_list_not_a_crash(monkeypatch):
    async def bad_bytes(url, **kw):
        return b"nope"

    async def text_bad(url, **kw):
        return ""

    monkeypatch.setattr(hry, "get_bytes", bad_bytes)
    monkeypatch.setattr(hry, "get_text", text_bad)
    assert asyncio.run(hry.HorryDelinquentXlsx().fetch()) == []
