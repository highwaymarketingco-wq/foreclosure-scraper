"""Tests for Orangeburg County SC Overage Claim List parsers (PDF text + xlsx)."""
from datetime import datetime

from foreclosure_scraper.main import DATELESS_OK_SOURCES, _active_only
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.scrapers.counties_sc.orangeburg_overage_claims import (
    parse_overage_text,
    parse_overage_xlsx,
)


def test_slug_is_dateless_whitelisted():
    """Overage claims never set sale_date (a standing unclaimed-funds
    condition, not a scheduled event) -- without this entry _active_only
    silently drops every row, the exact bug class test_dateless_ok_sources.py
    guards against for other sources."""
    assert "counties_sc.orangeburg_overage_claims" in DATELESS_OK_SOURCES


def test_dateless_row_survives_active_only():
    li = Listing(
        source="counties_sc.orangeburg_overage_claims",
        source_url="https://www.orangeburgcounty.org/DocumentCenter/View/2405",
        listing_type=ListingType.TAX_SALE_OVERAGE,
        state="SC",
        county="Orangeburg",
        parcel_id="0357-06-00-051.000",
        owner_name="ABRAHAM MONETTA",
        sale_date=None,
        raw={},
    )
    assert _active_only(li, horizon_days=120, now=datetime(2026, 10, 4)) is True

# Verbatim excerpt from the live 2021 list PDF (pypdf-extracted text, fetched
# 2026-10-04 from https://www.orangeburgcounty.org/DocumentCenter/View/2405).
# Uses non-breaking spaces (\xa0) as word separators and a Unicode hyphen
# (‐) inside the TMS -- both are real artifacts of this specific PDF's
# text layer, not something this test constructed.
SAMPLE_2021 = (
    "SALE\xa0NUMBER NAME TAX \xa0MPA\xa0NUMBER OVERAGE\n"
    "202100008 ABRAHAM \xa0MONETTA\xa0 0357‐06‐00‐051.000 $1,422.54\n"
    "202100009 ABRAHAM \xa0THELLO\xa0MAE\xa0M\xa0IN\xa0TRUST\xa0FOR\xa0GUINYA 0278 ‐00‐01‐024.000 $11,418.32\n"
    "202100036 ARCITERRA \xa0FD\xa0BOWMAN\xa0SC\xa0LLC 0246 ‐19‐03‐005.000 $145,318.33\n"
    "202100345 ROSS \xa0TARNEAKA\xa0ETAL 0231 ‐00‐02‐051.001 $0.00\n"
    "202100185 BANNUM \xa0JAMES\xa0&\xa0LUELLA 0174‐19‐08‐003‐000 $1,226.25\n"
)

# Verbatim excerpt from the live 2022 list PDF (plain ASCII, no nbsp/Unicode
# hyphen -- fetched 2026-10-04 from
# https://www.orangeburgcounty.org/DocumentCenter/View/3074/2022-Overage-List).
SAMPLE_2022 = (
    "SALE NUMBER NAME TAX MAP NUMBER OVERAGE\n"
    "202200006 ABRAHAM LOMAN SR ETAL 0189-00-05-031.000 $2,575.20\n"
    "202200099 BELZ BRENDA NOLAN ETAL 0059-00-06-072.000 $11,843.52\n"
    "202200286 BUTTS MILTON ETAL 0182-10-02-010.000 $0.00\n"
)


def test_parses_2021_nbsp_and_unicode_hyphen_rows():
    records = parse_overage_text(SAMPLE_2021)
    by_sale = {r["sale_number"]: r for r in records}
    rec = by_sale["202100008"]
    assert rec["name"] == "ABRAHAM MONETTA"
    assert rec["map_number"] == "0357-06-00-051.000"
    assert rec["amount"] == 1422.54


def test_parses_multiword_name_with_trust_phrase():
    records = parse_overage_text(SAMPLE_2021)
    by_sale = {r["sale_number"]: r for r in records}
    rec = by_sale["202100009"]
    assert rec["name"] == "ABRAHAM THELLO MAE M IN TRUST FOR GUINYA"
    assert rec["map_number"] == "0278-00-01-024.000"
    assert rec["amount"] == 11418.32


def test_handles_large_comma_amount():
    records = parse_overage_text(SAMPLE_2021)
    by_sale = {r["sale_number"]: r for r in records}
    assert by_sale["202100036"]["amount"] == 145318.33


def test_zero_amount_row_still_parses_filtering_is_the_scrapers_job():
    """The parser itself must not drop $0.00 rows -- the scraper (not the
    parser) decides a zeroed-out overage isn't a usable lead, matching
    york_overage_claims.py's UNKNOWN-claimant convention."""
    records = parse_overage_text(SAMPLE_2021)
    by_sale = {r["sale_number"]: r for r in records}
    assert by_sale["202100345"]["amount"] == 0.0


def test_hyphen_instead_of_period_final_segment():
    """One live row uses '-000' instead of '.000' before the final TMS
    segment; the parser should still recover a usable parcel id."""
    records = parse_overage_text(SAMPLE_2021)
    by_sale = {r["sale_number"]: r for r in records}
    assert by_sale["202100185"]["map_number"] == "0174-19-08-003-000"
    assert by_sale["202100185"]["name"] == "BANNUM JAMES & LUELLA"


def test_parses_2022_plain_ascii_rows():
    records = parse_overage_text(SAMPLE_2022)
    by_sale = {r["sale_number"]: r for r in records}
    rec = by_sale["202200006"]
    assert rec["name"] == "ABRAHAM LOMAN SR ETAL"
    assert rec["map_number"] == "0189-00-05-031.000"
    assert rec["amount"] == 2575.20


def test_skips_header_line():
    for records in (parse_overage_text(SAMPLE_2021), parse_overage_text(SAMPLE_2022)):
        for r in records:
            assert "SALE" not in r["name"].upper() or "NUMBER" not in r["name"].upper()


def test_empty_text():
    assert parse_overage_text("") == []
    assert parse_overage_text("no data here\njust some text") == []


# --- xlsx parser --------------------------------------------------------
# A minimal in-memory .xlsx built with zipfile + raw XML (no openpyxl
# dependency), shaped exactly like the real 2023 list's columns
# (SALE NUMBER / NAME / TAX MAP NUMBER / OVERAGE), confirmed live 2026-10-04
# against https://www.orangeburgcounty.org/DocumentCenter/View/3534.
def _build_minimal_xlsx(rows: list[list[str]]) -> bytes:
    import zipfile
    from io import BytesIO

    def esc(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    sheet_rows = []
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, val in enumerate(row):
            col_letter = chr(ord("A") + c_idx)
            cells.append(
                f'<c r="{col_letter}{r_idx}" t="inlineStr"><is><t>{esc(str(val))}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml"/></Types>',
        )
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


def test_parses_xlsx_rows():
    data = _build_minimal_xlsx([
        ["SALE NUMBER", "NAME", "TAX MAP NUMBER", "OVERAGE"],
        ["202300016", "ALEXANDER SARAH H & DONALD", "0151-16-05-016.000", "104.16"],
        ["202300034", "ANCRUM TILLMON MILTON ETAL", "0191-15-07-003.000", "1351.43"],
    ])
    records = parse_overage_xlsx(data)
    by_sale = {r["sale_number"]: r for r in records}
    assert by_sale["202300016"]["name"] == "ALEXANDER SARAH H & DONALD"
    assert by_sale["202300016"]["map_number"] == "0151-16-05-016.000"
    assert by_sale["202300016"]["amount"] == 104.16
    assert by_sale["202300034"]["amount"] == 1351.43


def test_xlsx_skips_zero_and_blank_rows_are_kept_for_scraper_to_filter():
    data = _build_minimal_xlsx([
        ["SALE NUMBER", "NAME", "TAX MAP NUMBER", "OVERAGE"],
        ["202300099", "SOMEONE ELSE", "0100-00-00-001.000", "0"],
    ])
    records = parse_overage_xlsx(data)
    assert records[0]["amount"] == 0.0


def test_xlsx_missing_header_returns_empty():
    data = _build_minimal_xlsx([["Unrelated", "Columns", "Here"]])
    assert parse_overage_xlsx(data) == []


def test_xlsx_not_a_zip_returns_empty():
    assert parse_overage_xlsx(b"not a zip at all") == []
