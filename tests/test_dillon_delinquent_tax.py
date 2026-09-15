"""Tests for Dillon County SC's proprietary tagged-binary delinquent-tax parser."""
import struct

from foreclosure_scraper.scrapers.counties_sc.dillon_delinquent_tax import (
    _HEADERS, parse_paper_xls,
)


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
