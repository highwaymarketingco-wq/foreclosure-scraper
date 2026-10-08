"""Florence County SC delinquent-tax-sale PDF parser.

HERMES sec 8 audit, 2026-10-03 (batch 10). No test file existed for this
scraper before this fix -- likely why the bug went unnoticed.

Covers both halves: the existing owner/TMS/location row parser
(`_parse_pdf_text`, unchanged) and the NEW tail-column extractor
(`_extract_tail_columns`), which recovers the LOTS/ACRES/BLDGS/DISTRICT
columns the old code stripped off and discarded via `_TAIL_NUMS_RE` without
ever writing them anywhere. See the module docstring's "AUDITED
2026-10-03" note for why position (not whitespace-run counting) is the
only reliable way to tell a lone trailing number apart as LOTS vs ACRES vs
BLDGS -- the live file has rows where a single trailing number before
DISTRICT is LOTS (e.g. "...1             10") and other rows where the
single trailing number is ACRES (e.g. "...9            20"), with no
textual difference between the two shapes.
"""
import io

from foreclosure_scraper.models import PropertyKind
from foreclosure_scraper.scrapers.counties_sc.florence_delinquent_tax import (
    _extract_tail_columns,
    _parse_pdf_text,
)

# Real rows copied verbatim (same character spacing) from the live 2026-09-01
# "Real" tax-sale PDF, as already quoted in the module's own docstring --
# this preserves the exact column character-offsets the live file uses.
_HEADER = ("TAXPAYER                         MAP-BLOCK-PARCEL/LOCATION                "
           "LOTS  ACRES  BLDGS  DISTRICT")
_ROW_LOTS_ONLY = ("ALEXANDER ASHLEY F             S   101-01-194  HEPBURN TERR LT 4"
                   "             1                   10")
_ROW_LOTS_AND_BLDGS = ("ALLEN LINDA H HEIRS            S 10013-01-031  WALDEN PLACE LOT 3"
                       "            1             1     11")
_ROW_ACRES_ONLY = ("ANDREWS GAIL KATHY             S   395-02-003  TRK 4 OFF HWY 57"
                    "                     9            20")
_ROW_ACRES_AND_BLDGS = ("ANTWINE CHARLES E JR           S   326-31-008  STILLWATER RD"
                        "                        8      2     31")
# Mobile-Homes list header/row, copied verbatim (same pypdf-reconstructed
# multi-space gaps `_ROW_RE`'s "\s{2,}" needs) from the live file's own
# pypdf.extract_text() output.
_MOBILE_HEADER = ("TAXPAYER                         MAP-BLOCK-PARCEL/LOCATION"
                   "                             BLDGS  DISTRICT")
_MOBILE_ROW = ("ACHEE CATHY H                  S 21000-35-305  2000 BELLCREST"
               "    28X60                     1     20")


def _make_word_positioned_pdf(rows: list[list[tuple[float, str]]]) -> bytes:
    """Build a minimal, genuinely valid single-page PDF where EACH word is
    placed by its own absolute text-matrix move (`Tm`) to a given (x, y) --
    i.e. real per-cell positioning, not one concatenated string. This is
    what actually makes `_extract_tail_columns`' bug real: pypdf's
    extract_text() reconstructs a single string per line using its OWN
    gap-width heuristic (confirmed live to NOT preserve a stable character
    offset for the same column row-to-row -- see the module docstring), so
    only each word's genuine rendered x0 (which `pdfplumber.extract_words()`
    reads straight from these `Tm` operators) can be trusted. Each row is a
    list of (x, text) pairs sharing one y; rows are stacked top to bottom."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=700, height=50 + 16 * len(rows))

    def esc(s: str) -> str:
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    parts = ["BT", "/F1 10 Tf"]
    y = 40 + 16 * len(rows)
    for row in rows:
        for x, text in row:
            parts.append(f"1 0 0 1 {x} {y} Tm ({esc(text)}) Tj")
        y -= 16
    parts.append("ET")
    content = " ".join(parts)

    stream = DecodedStreamObject()
    stream.set_data(content.encode("latin-1"))
    stream_ref = writer._add_object(stream)

    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/Helvetica")
    font_ref = writer._add_object(font)

    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = font_ref
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts

    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = stream_ref

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# Shared column X positions (arbitrary but fixed, mirroring the live file's
# own header word x0/x1 gaps -- see the real pdfplumber word dump quoted in
# the module docstring: LOTS~391, ACRES~420, BLDGS~454, DISTRICT~487).
_X_TAXPAYER = 36
_X_TMS = 230
_X_LOTS = 391
_X_ACRES = 450
_X_BLDGS = 510
_X_DISTRICT = 570

_POS_HEADER = [(_X_TAXPAYER, "TAXPAYER"), (_X_LOTS, "LOTS"), (_X_ACRES, "ACRES"),
               (_X_BLDGS, "BLDGS"), (_X_DISTRICT, "DISTRICT")]
_POS_ROW_LOTS_ONLY = [(_X_TAXPAYER, "ALEXANDER"), (_X_TMS, "101-01-194"),
                      (_X_LOTS, "1"), (_X_DISTRICT, "10")]
_POS_ROW_ACRES_ONLY = [(_X_TAXPAYER, "ANDREWS"), (_X_TMS, "395-02-003"),
                       (_X_ACRES, "9"), (_X_DISTRICT, "20")]
_POS_ROW_ACRES_AND_BLDGS = [(_X_TAXPAYER, "ANTWINE"), (_X_TMS, "326-31-008"),
                            (_X_ACRES, "8"), (_X_BLDGS, "2"), (_X_DISTRICT, "31")]
_POS_ROW_LOTS_AND_BLDGS = [(_X_TAXPAYER, "ALLEN"), (_X_TMS, "10013-01-031"),
                           (_X_LOTS, "1"), (_X_BLDGS, "1"), (_X_DISTRICT, "11")]

_POS_MOBILE_HEADER = [(_X_TAXPAYER, "TAXPAYER"), (_X_BLDGS, "BLDGS"), (_X_DISTRICT, "DISTRICT")]
_POS_MOBILE_ROW = [(_X_TAXPAYER, "ACHEE"), (_X_TMS, "21000-35-305"),
                   (_X_BLDGS, "1"), (_X_DISTRICT, "20")]


def _make_courier_pdf(lines: list[str]) -> bytes:
    """A minimal, genuinely valid single-page PDF rendered in Courier (a
    fixed-width font), one `Tj` per line at a decreasing Y -- so each
    character's rendered X position is a simple linear function of its
    character INDEX in the string. Since the fixture lines above preserve
    the live file's own character offsets, this reproduces the real file's
    column alignment well enough for pdfplumber's word x0/x1 extraction to
    bucket numbers into the same header-derived bins the live code path
    uses -- same `pypdf.PdfWriter` low-level assembly as the sibling
    `tests/test_nc_civicplus_tax_sale.py::_make_pdf` helper, extended to
    multiple positioned lines instead of one."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=700, height=50 + 14 * len(lines))

    def esc(s: str) -> str:
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    parts = ["BT", "/F1 10 Tf"]
    y = 40 + 14 * len(lines)
    for ln in lines:
        parts.append(f"36 {y} Td ({esc(ln)}) Tj")
        parts.append(f"-36 {-y} Td")  # reset to origin so next Td is absolute-ish
        y -= 14
    parts.append("ET")
    content = " ".join(parts)

    stream = DecodedStreamObject()
    stream.set_data(content.encode("latin-1"))
    stream_ref = writer._add_object(stream)

    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/Courier")
    font_ref = writer._add_object(font)

    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = font_ref
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts

    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = stream_ref

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Existing owner/TMS/location parser -- unchanged, just establishing a
# baseline this file never had before.
# ---------------------------------------------------------------------------

def test_parse_pdf_text_extracts_owner_tms_location():
    text = "\n".join([_HEADER, _ROW_LOTS_ONLY, _ROW_ACRES_AND_BLDGS])
    rows = _parse_pdf_text(text)
    assert len(rows) == 2
    r = next(r for r in rows if r["tms"] == "101-01-194")
    assert r["taxpayer"] == "ALEXANDER ASHLEY F"
    assert r["location"] == "HEPBURN TERR LT 4"


def test_current_owner_line_attaches_to_its_row():
    text = "\n".join([
        _HEADER,
        "    **CURRENT OWNER:    MILLENNIAL PROPERTIES LLC                   101-01-194         OTHER",
        _ROW_LOTS_ONLY,
    ])
    rows = _parse_pdf_text(text)
    assert len(rows) == 1
    assert rows[0]["current_owner"] == "MILLENNIAL PROPERTIES LLC"
    assert rows[0]["taxpayer"] == "ALEXANDER ASHLEY F"


# ---------------------------------------------------------------------------
# NEW: tail-column (LOTS/ACRES/BLDGS/DISTRICT) position-based extraction.
# ---------------------------------------------------------------------------

def test_tail_columns_distinguish_lots_from_acres_by_position_not_count():
    """The core correctness property this fix exists for: a lone trailing
    number before DISTRICT is LOTS on one row and ACRES on another, with
    the SAME shape (one number + district) in the whitespace-delimited
    text -- only X position tells them apart."""
    pdf = _make_word_positioned_pdf([_POS_HEADER, _POS_ROW_LOTS_ONLY, _POS_ROW_ACRES_ONLY])
    cols = _extract_tail_columns(pdf)
    assert cols["101-01-194"] == {"lots": "1", "district": "10"}
    assert cols["395-02-003"] == {"acres": "9", "district": "20"}
    assert "acres" not in cols["101-01-194"]
    assert "lots" not in cols["395-02-003"]


def test_tail_columns_recover_two_numbers_plus_district():
    pdf = _make_word_positioned_pdf([_POS_HEADER, _POS_ROW_LOTS_AND_BLDGS,
                                     _POS_ROW_ACRES_AND_BLDGS])
    cols = _extract_tail_columns(pdf)
    assert cols["10013-01-031"] == {"lots": "1", "bldgs": "1", "district": "11"}
    assert cols["326-31-008"] == {"acres": "8", "bldgs": "2", "district": "31"}


def test_tail_columns_mobile_home_header_has_only_bldgs_and_district():
    pdf = _make_word_positioned_pdf([_POS_MOBILE_HEADER, _POS_MOBILE_ROW])
    cols = _extract_tail_columns(pdf)
    assert cols["21000-35-305"] == {"bldgs": "1", "district": "20"}


def test_tail_columns_empty_without_a_header_to_bin_against():
    """Refuses to guess at column meaning with no header row to anchor on --
    same defensive posture as the sibling xlsx/binary parsers in this repo
    that return [] rather than assume a layout."""
    pdf = _make_word_positioned_pdf([_POS_ROW_LOTS_ONLY])
    assert _extract_tail_columns(pdf) == {}


# ---------------------------------------------------------------------------
# Scraper-level: property_kind wiring (missing BLDGS -> LAND on the Real
# list; Mobile list stays force-tagged MOBILE regardless).
# ---------------------------------------------------------------------------

def test_fetch_sets_land_when_bldgs_missing_on_real_list():
    import asyncio
    from unittest.mock import patch

    from foreclosure_scraper.scrapers.counties_sc.florence_delinquent_tax import (
        FlorenceDelinquentTax,
    )

    # fetch() refuses pages under 200 chars (guards against an empty/error
    # response) -- pad with an HTML comment, same convention real pages
    # satisfy just by having a real nav/layout around the link.
    html = ('<!-- padding so this page clears fetch()\'s len(html) < 200 guard, '
            'same as a real page\'s surrounding nav/layout would -->'
            '<a href="DelinquentTax/2026/2026 Tax Sale List Real 9-01-26.pdf">'
            'Tax Sale List</a>')
    pdf_bytes = _make_courier_pdf([_HEADER, _ROW_LOTS_ONLY, _ROW_ACRES_AND_BLDGS])

    async def fake_get_text(*a, **k):
        return html

    async def fake_get_bytes(*a, **k):
        return pdf_bytes

    with patch("foreclosure_scraper.scrapers.counties_sc.florence_delinquent_tax.get_text",
               fake_get_text), \
         patch("foreclosure_scraper.scrapers.counties_sc.florence_delinquent_tax.get_bytes",
               fake_get_bytes):
        rows = list(asyncio.run(FlorenceDelinquentTax().fetch()))

    assert len(rows) == 2
    land_row = next(r for r in rows if r.parcel_id == "101-01-194")
    improved_row = next(r for r in rows if r.parcel_id == "326-31-008")
    assert land_row.property_kind == PropertyKind.LAND
    assert land_row.raw["florence_delinquent_tax"]["lots"] == 1.0
    assert land_row.raw["florence_delinquent_tax"]["buildings"] is None
    assert improved_row.property_kind == PropertyKind.UNKNOWN
    assert improved_row.raw["florence_delinquent_tax"]["buildings"] == 2.0
    assert improved_row.raw["florence_delinquent_tax"]["acres"] == 8.0
    assert improved_row.raw["florence_delinquent_tax"]["tax_district"] == "31"


def test_fetch_mobile_list_stays_mobile_regardless_of_bldgs():
    import asyncio
    from unittest.mock import patch

    from foreclosure_scraper.scrapers.counties_sc.florence_delinquent_tax import (
        FlorenceDelinquentTax,
    )

    html = ('<!-- padding so this page clears fetch()\'s len(html) < 200 guard, '
            'same as a real page\'s surrounding nav/layout would -->'
            '<a href="DelinquentTax/2026/2026 Tax Sale List Mobile Homes 9-1-26.pdf">'
            'Tax Sale List</a>')
    pdf_bytes = _make_courier_pdf([_MOBILE_HEADER, _MOBILE_ROW])

    async def fake_get_text(*a, **k):
        return html

    async def fake_get_bytes(*a, **k):
        return pdf_bytes

    with patch("foreclosure_scraper.scrapers.counties_sc.florence_delinquent_tax.get_text",
               fake_get_text), \
         patch("foreclosure_scraper.scrapers.counties_sc.florence_delinquent_tax.get_bytes",
               fake_get_bytes):
        rows = list(asyncio.run(FlorenceDelinquentTax().fetch()))

    assert len(rows) == 1
    assert rows[0].property_kind == PropertyKind.MOBILE
    assert rows[0].raw["florence_delinquent_tax"]["buildings"] == 1.0


def test_fetch_sets_owner_name_not_just_defendant():
    """10/7 extraction audit section 3: owner_name was None on every Florence row."""
    import asyncio
    from unittest.mock import patch

    from foreclosure_scraper.scrapers.counties_sc.florence_delinquent_tax import (
        FlorenceDelinquentTax,
    )

    html = ('<!-- padding so this page clears fetch()\'s len(html) < 200 guard, '
            'same as a real page\'s surrounding nav/layout would -->'
            '<a href="DelinquentTax/2026/2026 Tax Sale List Real 9-01-26.pdf">'
            'Tax Sale List</a>')
    pdf_bytes = _make_courier_pdf([_HEADER, _ROW_LOTS_ONLY, _ROW_ACRES_AND_BLDGS])

    async def fake_get_text(*a, **k):
        return html

    async def fake_get_bytes(*a, **k):
        return pdf_bytes

    with patch("foreclosure_scraper.scrapers.counties_sc.florence_delinquent_tax.get_text",
               fake_get_text), \
         patch("foreclosure_scraper.scrapers.counties_sc.florence_delinquent_tax.get_bytes",
               fake_get_bytes):
        rows = list(asyncio.run(FlorenceDelinquentTax().fetch()))

    assert rows and all(r.owner_name and r.owner_name == r.defendant for r in rows)
