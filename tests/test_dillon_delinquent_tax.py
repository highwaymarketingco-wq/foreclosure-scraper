"""Tests for Dillon County SC's delinquent-tax parsers.

Covers BOTH export formats the live county site has used: the original
proprietary tagged-binary stream (parse_paper_xls) and the real .xlsx the
county migrated to on or before 2026-10-01 (parse_xlsx_rows) -- see the
module docstring's "AUDITED 2026-10-01" note for why both must stay.
"""
import io
import struct
import zipfile
from xml.sax.saxutils import escape

from foreclosure_scraper.models import PropertyKind
from foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax import (
    _HEADERS, parse_paper_xls, parse_xlsx_rows,
)


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def make_xlsx(rows: list[list]) -> bytes:
    """A minimal real .xlsx (shared strings + a single sheet), same builder
    shape as tests/test_charleston_horry_xlsx.py uses for the sibling xlsx
    sources, so parse_xlsx_rows() is exercised against the SAME on-disk
    format the live stdlib reader (_xlsx_stdlib.read_rows) actually parses,
    not a hand-rolled list of lists."""
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
            cells.append(f'<c r="{ref}" t="s"><v>{sid(str(v))}</v></c>')
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet_xml = f'<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData>{"".join(body)}</sheetData></worksheet>'
    sst_xml = (f'<?xml version="1.0"?><sst xmlns="{ns}">'
               + "".join(f"<si><t>{escape(t)}</t></si>" for t in sst) + "</sst>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        z.writestr("xl/sharedStrings.xml", sst_xml)
    return buf.getvalue()


def _str_tok(text: str) -> bytes:
    return bytes([len(text)]) + text.encode("ascii")


def _meta(text_len: int, row_idx: int, col_idx: int) -> bytes:
    """The 11-byte block that PRECEDES a token and describes THAT token
    (verified live: the gap before "Owner Name" encodes Owner Name's own
    col_idx=1, etc.) — not a trailing marker for the token before it."""
    return (b"\x04\x00" + struct.pack("<H", text_len + 8) +
            struct.pack("<H", row_idx) + struct.pack("<H", col_idx) + b"\x27\x00\x00")


def _build_file(rows: list[dict[str, str]]) -> bytes:
    """Headers (real file has metadata between them too, but the parser
    never reads it — only their TEXT is validated, so plain concatenation
    is sufficient) + each row's present fields, metadata-then-string, in
    the real file's actual encoding (blank fields simply omitted)."""
    buf = b"".join(_str_tok(h) for h in _HEADERS)
    for r_idx, row in enumerate(rows, start=1):
        for col_idx, h in enumerate(_HEADERS):
            if h in row:
                text = row[h]
                buf += _meta(len(text), r_idx, col_idx) + _str_tok(text)
    return buf


ROW1 = {
    "Item Number": "00001", "Owner Name": "ABDULLAH BARBARA", "District": "3",
    "Map Number": "104-16-12-018", "Description": "117 LEGARE ST", "Acres": ".00",
    "Buildings": "1", "Lots": "1", "Real / MH (R,M)": "R",
    "Notice 01 Number": "000012253", "Comment": "3  $17482",
    "Notice 02 Number": "000006243", "Total Tax Due": "1,157.80",
}
ROW2_WITH_OWNER2 = {
    "Item Number": "00016", "Owner Name": "ADAMS EARLINE BETHEA ETAL",
    "Owner Name 2": "% EARLINE ADAMS", "District": "2", "Map Number": "069-03-12-039",
    "Description": "DILLON", "Total Tax Due": "156.89",
}


def test_parses_row_without_blank_fields():
    recs = parse_paper_xls(_build_file([ROW1]))
    assert len(recs) == 1
    assert recs[0]["Owner Name"] == "ABDULLAH BARBARA"
    assert recs[0]["Map Number"] == "104-16-12-018"
    assert recs[0]["Total Tax Due"] == "1,157.80"
    assert "Owner Name 2" not in recs[0]


def test_blank_fields_do_not_shift_later_columns():
    """The core correctness property: a row missing 'Owner Name 2' (and other
    fields) must not smear later real values into the wrong column — this is
    exactly the failure mode a positional (non-metadata-driven) parser has."""
    recs = parse_paper_xls(_build_file([ROW2_WITH_OWNER2]))
    assert len(recs) == 1
    r = recs[0]
    assert r["Owner Name"] == "ADAMS EARLINE BETHEA ETAL"
    assert r["Owner Name 2"] == "% EARLINE ADAMS"
    assert r["Map Number"] == "069-03-12-039"
    assert r["Total Tax Due"] == "156.89"


def test_multiple_rows_stay_independent():
    recs = parse_paper_xls(_build_file([ROW1, ROW2_WITH_OWNER2]))
    assert len(recs) == 2
    assert recs[0]["Owner Name"] == "ABDULLAH BARBARA"
    assert recs[1]["Owner Name"] == "ADAMS EARLINE BETHEA ETAL"


def test_refuses_to_guess_on_unexpected_header_layout():
    assert parse_paper_xls(b"not the right format at all") == []
    assert parse_paper_xls(_str_tok("Wrong Header")) == []


def test_finds_link_despite_stray_space_before_quote():
    """Regression: the live page's own markup is href= "..." (a space before
    the quote) rather than well-formed href="...", which a stricter regex
    silently missed on the very first live run."""
    import asyncio
    from unittest.mock import patch

    from foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax import DillonDelinquentTax

    html = ('<a href= "Documents/Departments/Treasurer/PAPER.XLS?t=1" '
            'target="_blank" >Delinquent Tax Sale List</a>')
    data = _build_file([ROW1])

    async def fake_get_text(*a, **k):
        return html

    async def fake_get_bytes(*a, **k):
        return data

    with patch("foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax.get_text", fake_get_text), \
         patch("foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax.get_bytes", fake_get_bytes):
        rows = list(asyncio.run(DillonDelinquentTax().fetch()))
    assert len(rows) == 1


def test_parse_xlsx_rows_matches_live_header_order():
    """AUDITED 2026-10-01: the live file's header row is the SAME 16 columns,
    in the SAME order, as the old binary format's _HEADERS -- the county only
    changed the container, not the schema."""
    data = make_xlsx([_HEADERS,
                      ["00001", "ABDULLAH BARBARA", "", "3", "104-16-12-018",
                       "117 LEGARE ST", ".00", "1", "1", "", "", "R",
                       "000012253", "3  $17482", "000006243", "1,157.80"]])
    recs = parse_xlsx_rows(data)
    assert len(recs) == 1
    assert recs[0]["Owner Name"] == "ABDULLAH BARBARA"
    assert recs[0]["Map Number"] == "104-16-12-018"
    assert recs[0]["Total Tax Due"] == "1,157.80"


def test_parse_xlsx_rows_skips_blank_rows():
    data = make_xlsx([_HEADERS, [], ["00001", "ABDULLAH BARBARA", "", "3",
                                     "104-16-12-018"]])
    recs = parse_xlsx_rows(data)
    assert len(recs) == 1


def test_parse_xlsx_rows_refuses_unexpected_header():
    data = make_xlsx([["Totally", "Different", "Columns"], ["a", "b", "c"]])
    assert parse_xlsx_rows(data) == []


def test_fetch_picks_xlsx_reader_when_the_county_serves_a_real_workbook():
    """AUDITED 2026-10-01 regression: the live link's filename/content changed
    from the proprietary binary PAPER.XLS to a real PAPER.xlsx. fetch() must
    detect this by the downloaded bytes' own magic number, not the filename,
    and route to parse_xlsx_rows() instead of silently returning 0 via the
    legacy binary scanner (which correctly refuses to guess at a real zip)."""
    import asyncio
    from unittest.mock import patch

    from foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax import DillonDelinquentTax

    html = '<a href="Documents/Departments/Treasurer/PAPER.xlsx">Delinquent Tax Sale List</a>'
    data = make_xlsx([_HEADERS,
                      ["00001", "ABDULLAH BARBARA", "", "3", "104-16-12-018",
                       "117 LEGARE ST", ".00", "1", "1", "", "", "R",
                       "000012253", "3  $17482", "000006243", "1,157.80"]])

    async def fake_get_text(*a, **k):
        return html

    async def fake_get_bytes(*a, **k):
        return data

    with patch("foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax.get_text", fake_get_text), \
         patch("foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax.get_bytes", fake_get_bytes):
        rows = list(asyncio.run(DillonDelinquentTax().fetch()))
    assert len(rows) == 1
    assert rows[0].owner_name == "ABDULLAH BARBARA"
    assert rows[0].parcel_id == "104-16-12-018"


def test_end_to_end_listing_shape():
    """Full scraper-level mapping: owner_name/defendant carry Owner Name (+
    Owner Name 2 when present), parcel_id = Map Number, amount parsed."""
    import asyncio
    from unittest.mock import patch, AsyncMock

    from foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax import DillonDelinquentTax

    html = '<a href="Documents/Departments/Treasurer/PAPER.XLS?t=1">Delinquent Tax Sale List</a>'
    data = _build_file([ROW1, ROW2_WITH_OWNER2])

    async def fake_get_text(*a, **k):
        return html

    async def fake_get_bytes(*a, **k):
        return data

    with patch("foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax.get_text", fake_get_text), \
         patch("foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax.get_bytes", fake_get_bytes):
        rows = asyncio.run(DillonDelinquentTax().fetch())

    rows = list(rows)
    assert len(rows) == 2
    r1 = next(r for r in rows if r.parcel_id == "104-16-12-018")
    assert r1.owner_name == "ABDULLAH BARBARA"
    assert r1.raw["dillon_delinquent_tax"]["total_due"] == 1157.80
    r2 = next(r for r in rows if r.parcel_id == "069-03-12-039")
    assert r2.owner_name == "ADAMS EARLINE BETHEA ETAL % EARLINE ADAMS"
    assert r2.sale_date is None


# AUDITED 2026-10-03: Acres/Buildings/Lots/New Owner Name(+2) were parsed
# off the live file into `rec` and then silently dropped before reaching the
# Listing/raw. These fixtures mirror real live rows (see batch-10 memory
# entry): a vacant-land row (Buildings="0"), a mobile-home row (Real/MH="M"),
# and a row where the parcel already changed hands (New Owner Name filled).
ROW_VACANT_LAND = {
    "Item Number": "01270", "Owner Name": "MCCLURE KIMBERLY", "District": "3",
    "Map Number": "076-00-00-229", "Description": "FRONTING 114 FT ON THE SW SIDE",
    "Acres": "1.00", "Buildings": "0", "Lots": "0", "Real / MH (R,M)": "R",
    "Notice 01 Number": "003398253", "Comment": "3 $3949",
    "Notice 02 Number": "014428243", "Total Tax Due": "528.93",
}
ROW_MOBILE_HOME = {
    "Item Number": "00006", "Owner Name": "ABUDAYYA AMJAD RABAH", "District": "2",
    "Map Number": "032-00-00-028", "Description": "S SIDE SC 9",
    "Acres": ".50", "Buildings": "1", "Lots": "1", "Real / MH (R,M)": "M",
    "Notice 01 Number": "000053253", "Comment": "2 $3096",
    "Notice 02 Number": "000048243", "Total Tax Due": "234.04",
}
ROW_OWNERSHIP_TRANSFERRED = {
    "Item Number": "00541", "Owner Name": "DAVIS WILLIE LEE ETALS", "District": "1",
    "Map Number": "111-06-00-077", "Description": "900 SHADY CIRCLE",
    "Acres": ".00", "Buildings": "1", "Lots": "1",
    "New Owner Name": "PAGE MARY KATE & TYRONE DAVIS",
    "Real / MH (R,M)": "R", "Notice 01 Number": "006015253",
    "Comment": "1 $81088", "Notice 02 Number": "005942243",
    "Total Tax Due": "3,067.34",
}


def _fetch_rows(rows: list[dict[str, str]]):
    import asyncio
    from unittest.mock import patch

    from foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax import DillonDelinquentTax

    html = '<a href="Documents/Departments/Treasurer/PAPER.XLS?t=1">Delinquent Tax Sale List</a>'
    data = _build_file(rows)

    async def fake_get_text(*a, **k):
        return html

    async def fake_get_bytes(*a, **k):
        return data

    with patch("foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax.get_text", fake_get_text), \
         patch("foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax.get_bytes", fake_get_bytes):
        return list(asyncio.run(DillonDelinquentTax().fetch()))


def test_acres_buildings_lots_captured_in_raw():
    rows = _fetch_rows([ROW1])
    r = rows[0]
    raw = r.raw["dillon_delinquent_tax"]
    assert raw["acres"] == 0.0
    assert raw["buildings"] == 1
    assert raw["lots"] == 1
    assert raw["comment_raw"] == "3  $17482"


def test_zero_buildings_real_property_maps_to_land():
    rows = _fetch_rows([ROW_VACANT_LAND])
    r = rows[0]
    assert r.property_kind == PropertyKind.LAND
    assert r.raw["dillon_delinquent_tax"]["buildings"] == 0
    assert r.raw["dillon_delinquent_tax"]["acres"] == 1.0


def test_mobile_home_flag_maps_to_mobile_property_kind():
    rows = _fetch_rows([ROW_MOBILE_HOME])
    r = rows[0]
    assert r.property_kind == PropertyKind.MOBILE


def test_improved_real_property_stays_unknown_kind():
    """A real-property row WITH a building isn't necessarily single-family
    (could be commercial) -- stays UNKNOWN rather than guessing."""
    rows = _fetch_rows([ROW_OWNERSHIP_TRANSFERRED])
    r = rows[0]
    assert r.property_kind == PropertyKind.UNKNOWN


def test_new_owner_name_surfaced_without_dropping_the_row():
    rows = _fetch_rows([ROW_OWNERSHIP_TRANSFERRED])
    r = rows[0]
    raw = r.raw["dillon_delinquent_tax"]
    assert raw["ownership_transferred"] is True
    assert raw["new_owner_name"] == "PAGE MARY KATE & TYRONE DAVIS"
    # Still a real lead -- not filtered out despite the ownership change.
    assert r.defendant == "DAVIS WILLIE LEE ETALS"


def test_no_new_owner_flag_false_when_blank():
    rows = _fetch_rows([ROW1])
    raw = rows[0].raw["dillon_delinquent_tax"]
    assert raw["ownership_transferred"] is False
    assert raw["new_owner_name"] is None


def test_scraper_timeout_covers_both_requests_and_a_fallback():
    """10/8 VM run: a ConnectTimeout on the treasurer page plus the curl fallback outlasted
    the old 60 s scraper timeout (shorter than the two requests' own 40 s + 60 s), so the
    run read nothing; the run an hour earlier read all 343 rows in 39 s."""
    from foreclosure_scraper.scrapers.counties_sc import dillon_delinquent_tax as mod
    assert mod.DillonDelinquentTax.timeout_s >= mod._PAGE_TIMEOUT_S + mod._FILE_TIMEOUT_S + 60
