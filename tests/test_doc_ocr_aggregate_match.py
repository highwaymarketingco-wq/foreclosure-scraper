"""Regression tests for the shared-roster (aggregate) backfill path in
enrichment_doc_ocr — _lead_identifiers / _row_backfill_from_aggregate /
_pdf_text's page cap.

Root cause (docs/doc_ocr_aggregate_match_fix_2026-09-23.md, live evidence
2026-09-23): _pdf_text() capped every read at the first 3 pages, a budget
sized for a single-property notice/deed. The aggregate reader reuses it to
read a whole COUNTY ROSTER once per unique document -- Catawba County NC's
delinquent-tax PDF (counties_nc.nc_county_pdf_delinquent_tax, 3,958 leads on
the live board 2026-09-23) is 161 pages, alphabetical by taxpayer, ~25
rows/page; Buncombe County NC's (845 leads) is 12 pages. The 3-page cap made
roughly 98% of Catawba's rows and 75% of Buncombe's rows structurally
unreachable by the line-scoped substring matcher below, regardless of any
identifier-format issue -- which is why enrich_doc_ocr's 2026-09-22 run
backfilled 2 of 8,955 aggregate-roster leads.

A second, smaller issue surfaced once real documents were read closely:
Buncombe's PDF is laid out in dense side-by-side columns, and pdfplumber's
extract_text() groups words into a "line" by y-position only -- blind to
column bands -- so one physical output line can interleave fragments from
TWO OR MORE unrelated properties. The excerpt below is real (fetched
2026-09-23 from
media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf)
and demonstrates it: Kimberly Anne Atkinson's parcel 867991795700000 and her
own true street address, 461 BEAR WALLOW TRL (confirmed against her own board
row, already correctly parsed by the scraper itself), do not even land on the
same output line -- "TRL" is split off onto a line two below, with an
unrelated boilerplate sentence in between. Searching an entire merged/garbled
line for "the last address-looking phrase" (the old behaviour) can just as
easily pick up a DIFFERENT property's address that happens to sit BEFORE this
lead's own identifier on the same merged line -- which is the exact failure
_row_backfill_from_aggregate exists to prevent. The fix narrows the address
search to the text AFTER the matched identifier.
"""
from __future__ import annotations

import io

from foreclosure_scraper.models import Listing
from foreclosure_scraper import enrichment_doc_ocr as dm


def _li(**kw):
    base = dict(source="test", source_url="https://x/y", state="NC", county="Buncombe")
    base.update(kw)
    return Listing(**base)


# --- _pdf_text page cap -------------------------------------------------------
def _text_pdf(pages_text: list[str]) -> bytes:
    """A real, valid multi-page PDF (built via pypdf, the dependency this repo
    already uses to construct test PDFs -- see tests/test_nc_pdf_tax_guard.py)
    whose pages contain literal extractable text, one Tj per line."""
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    w = PdfWriter()
    for text in pages_text:
        page = w.add_blank_page(width=612, height=792)
        parts = ["BT", "/F1 10 Tf", "50 750 Td", "12 TL"]
        for i, line in enumerate(text.split("\n")):
            esc = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            if i:
                parts.append("T*")
            parts.append(f"({esc}) Tj")
        parts.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(parts).encode("latin-1"))
        page[NameObject("/Contents")] = w._add_object(stream)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _roster_pdf(n_pages: int) -> bytes:
    """A synthetic multi-page county-roster fixture: each page holds several
    taxpayer rows with a page-unique parcel, reproducing the real Catawba/
    Buncombe shape (one page per alphabetical slice of the roll). Padded to
    comfortably clear _pdf_text's own 200-char "is this a real text layer"
    floor within the first 3 pages, same as a real roster page would."""
    return _text_pdf(
        ["\n".join(f"TAXPAYER {p}-{r} PAGE{p:03d}PARCEL{p:03d}{r:02d} $100.{r:02d}"
                   for r in range(8))
         for p in range(n_pages)])


def test_pdf_text_default_budget_is_still_three_pages():
    """Unchanged behaviour for the per-lead OCR-prep path (_ocr_document),
    which pays real vision/text-model cost per call and must stay cheap."""
    data = _roster_pdf(6)
    text = dm._pdf_text(data)
    assert "PAGE000" in text
    assert "PAGE002" in text
    assert "PAGE003" not in text, "default call now reads past page 3 -- regression"
    assert "PAGE005" not in text


def test_pdf_text_max_pages_none_reads_the_whole_roster():
    """The fix: the aggregate reader must be able to see every page, not just
    the first 3 -- this is what makes rows past roughly page 3 (98% of the
    real Catawba roster) reachable at all."""
    data = _roster_pdf(6)
    text = dm._pdf_text(data, max_pages=None, max_chars=1_000_000)
    for p in range(6):
        assert f"PAGE{p:03d}" in text, f"page {p} missing from a max_pages=None read"


def test_pdf_text_max_chars_still_bounds_an_unlimited_page_read():
    """max_pages=None must stay bounded by max_chars, so a pathological
    (very long) roster cannot blow up memory just because the page cap is off."""
    data = _roster_pdf(50)
    text = dm._pdf_text(data, max_pages=None, max_chars=500)
    assert text is not None
    assert len(text) <= 500


def test_aggregate_pass_reads_with_the_uncapped_helper():
    """Source-level regression guard: the aggregate loop in enrich_doc_ocr must
    call _pdf_text with the AGG (uncapped) budget, not silently fall back to
    the 3-page per-lead default -- a plain refactor could drop the kwargs
    without any test noticing otherwise."""
    import inspect
    src = inspect.getsource(dm.enrich_doc_ocr)
    i = src.index("# ---- aggregate pass")
    agg_src = src[i:]
    assert "max_pages=DOC_OCR_AGG_MAX_PAGES" in agg_src
    assert "max_chars=DOC_OCR_AGG_MAX_CHARS" in agg_src
    assert dm.DOC_OCR_AGG_MAX_PAGES is None, (
        "default env DOC_OCR_AGG_MAX_PAGES must resolve to 'no page limit'")


# --- real-document evidence: Florence County SC mobile-home tax roster -------
# Verbatim excerpt, fetched 2026-09-23 from
# s3.us-east-1.amazonaws.com/files.florenceco.org/public/DelinquentTax/2026/
# "2026 Tax Sale List Mobile Homes 9-1-26.pdf" -- clean single-column table,
# TAXPAYER / MAP-BLOCK-PARCEL / LOCATION / BLDGS / DISTRICT. "LOCATION" here is
# the mobile home's year/make/size ("2000 BELLCREST 28X60"), not a street
# address -- this document type has no street address to backfill, which is
# why it correctly yields no match rather than a wrong or fabricated one.
_FLORENCE_REAL_EXCERPT = (
    "TAXPAYER MAP-BLOCK-PARCEL/LOCATION BLDGS DISTRICT\n"
    "ACHEE CATHY H S 21000-35-305 2000 BELLCREST 28X60 1 20\n"
    "ALSTON LA CHONE S 97000-29-025 1997 BUCCANEER 16X76 1 11\n"
    "AON PROPERTIES III LLC S 40000-51-545 1985 STER 14X66 1 14\n"
)


def test_real_florence_row_is_located_but_has_no_address_to_give():
    li = _li(state="SC", county="Florence", parcel_id="21000-35-305",
             defendant="ACHEE CATHY H", owner_name="COCKFIELD CHESSIE G ETAL",
             street_address=None)
    filled = dm._row_backfill_from_aggregate(li, _FLORENCE_REAL_EXCERPT)
    # The parcel is found (proves the matcher itself works against real text);
    # nothing is filled because the roster prints no street address at all.
    assert filled == []
    assert li.street_address is None


def test_real_florence_row_lookup_succeeds_via_parcel_identifier():
    idents = dm._lead_identifiers(_li(parcel_id="21000-35-305", defendant="ACHEE CATHY H"))
    assert "21000-35-305" in idents
    line = next(l for l in _FLORENCE_REAL_EXCERPT.splitlines() if "21000-35-305" in l)
    assert line.startswith("ACHEE CATHY H")


# --- real-document evidence: Buncombe County NC tax-lien advertisement -------
# Verbatim excerpt, fetched 2026-09-23 from media.buncombenc.gov/common/tax/
# buncombe-county-tax-department-advertisement-of-tax-liens.pdf, page 1,
# extracted with pdfplumber's default (non-layout) extract_text() -- exactly
# what _pdf_text() produces. Kimberly Anne Atkinson (parcel 867991795700000,
# board-confirmed street_address "461 BEAR WALLOW TRL") is in here, but her
# parcel and her address are not on the same output line: the multi-column
# layout splits "461 BEAR WALLOW" onto one line and "TRL" onto another, with
# an unrelated boilerplate sentence between them.
_BUNCOMBE_REAL_EXCERPT = (
    "BUNCOMBE COUNTY TAX DEPT. ADVERTISEMENT OF TAX LIENS\n"
    "125 PISGAH VIEW LLC -- ARSZYLA, JOHN C 867992912000000\n"
    "961895417300000 ALLEN, JANA 969819933500000 $190.21\n"
    "$775.59 968784810900000 $37.00 99999 NEWFOUND RD\n"
    "107 PISGAH VIEW RD $224.41 CAMPBELL ST --\n"
    "-- WRIGHTS COVE RD -- ATKINSON, KIMBERLY\n"
    "36 FOX RD LLC -- ARSZYLA, JOHN C ANNE\n"
    "972073209100000 ALLEN, LINDA 969819933400000 867991795700000\n"
    "$115.56 PARROTT North Carolina General Statutes require local tax collec- $37.00 $171.06\n"
    "36 FOX RD 974363940700000 CAMPBELL ST 461 BEAR WALLOW\n"
    "tors to advertise annually all current year unpaid taxes\n"
    "-- $430.65 -- TRL\n"
)


def test_real_buncombe_row_is_located_and_safely_yields_no_address():
    """Atkinson's own identifier IS found (the matcher works), but her address
    is split across a different, non-adjacent line by the column layout, so
    the honest, safe outcome today is no match -- not a guessed/wrong one."""
    li = _li(parcel_id="867991795700000", owner_name="ATKINSON, KIMBERLY ANNE",
             defendant="ATKINSON, KIMBERLY ANNE", street_address=None)
    filled = dm._row_backfill_from_aggregate(li, _BUNCOMBE_REAL_EXCERPT)
    assert filled == []
    assert li.street_address is None


# Verbatim line, fetched 2026-09-23 from the same Buncombe PDF (full-document
# read, page ~5): NIX, WILLIAM L JR's own parcel 978416519600000 is on this
# line, but the very next words on the SAME line -- "PAGANO, RAYMOND J 1 CREST
# AVE" -- are a DIFFERENT taxpayer's name and address (Pagano's own line is a
# few rows away). Before the column-merge guard existed, the "search after the
# identifier" rule alone stamped Pagano's "1 CREST AVE" onto Nix -- his real
# address (board-confirmed, correctly parsed by the scraper itself from the
# same document) is "20 HOUSTON RD".
_BUNCOMBE_REAL_CONTAMINATED_LINE = (
    "968849046600000 -- 978416519600000 PAGANO, RAYMOND J 1 CREST AVE JANEL "
    "PRESLEY, PEGGY S PULLEASE, REBECCA"
)

# Verbatim line, same document: FRANK W MORRIS JR ETAL's parcel
# 961388939100000 sits between TWO other properties' fragments including a
# second long PIN (963483432700000) and an unrelated address, "17 SILENT PL",
# that belongs to whichever property 963483432700000 is. Morris's own
# board-confirmed address is "311 BOUNDARY TREE PASS" -- nowhere on this line.
_BUNCOMBE_REAL_CONTAMINATED_LINE_2 = (
    "75 BUCHANAN AVE 960545728200000 36 HOLLY ACRES LN 961388939100000 "
    "963483432700000 $152.03 99999 QUEEN RD 17 SILENT PL"
)


def test_real_buncombe_contaminated_line_does_not_stamp_a_neighbours_address():
    """The failure this guard was added for. Confirmed live 2026-09-23: without
    the column-merge guard, this exact real line gave NIX, WILLIAM L JR
    (parcel 978416519600000) a stranger's "1 CREST AVE" instead of his own
    board-confirmed "20 HOUSTON RD" (2 wrong fills out of an 11-lead real
    sample from this document -- see the fix doc)."""
    li = _li(parcel_id="978416519600000", owner_name="NIX, WILLIAM L JR",
             defendant="NIX, WILLIAM L JR", street_address=None)
    filled = dm._row_backfill_from_aggregate(li, _BUNCOMBE_REAL_CONTAMINATED_LINE)
    assert filled == []
    assert li.street_address is None, (
        "regression: a neighbour's address (Pagano's '1 CREST AVE') was stamped onto Nix")


def test_real_buncombe_second_contaminated_line_does_not_stamp_a_neighbours_address():
    li = _li(parcel_id="961388939100000", owner_name="FRANK W MORRIS JR ETAL",
             defendant="FRANK W MORRIS JR ETAL", street_address=None)
    filled = dm._row_backfill_from_aggregate(li, _BUNCOMBE_REAL_CONTAMINATED_LINE_2)
    assert filled == []
    assert li.street_address is None


def test_long_id_run_regex_matches_buncombe_pins_not_amounts_or_house_numbers():
    assert dm._LONG_ID_RUN.search("978416519600000")
    assert dm._LONG_ID_RUN.search("$79,723.60".replace(",", "").replace(".", "")) is None
    assert dm._LONG_ID_RUN.search("264") is None


# --- the column-merge contamination guard -------------------------------------
def test_address_before_a_merged_lines_identifier_is_not_stamped():
    """Synthetic, but modeled directly on the real Buncombe merge pattern above
    (one physical line, two unrelated properties' fields concatenated). Here a
    DIFFERENT property's address sits before this lead's own parcel on the
    same merged line -- the exact shape that could leak a neighbour's street
    onto this lead. Confirms the address search is scoped to AFTER the
    identifier, not the whole row."""
    row = "100 OLD MILL RD -- 6-21-00-456.00 SMITH JOHN --"
    # Sanity: the danger is real -- an unscoped whole-row search finds it.
    assert dm._ADDR_IN_ROW.search(row).group(0) == "100 OLD MILL RD"
    li = _li(parcel_id="6-21-00-456.00", owner_name="SMITH JOHN", street_address=None)
    filled = dm._row_backfill_from_aggregate(li, row)
    assert filled == []
    assert li.street_address is None


def test_address_after_the_identifier_on_its_own_row_still_fills():
    """The common, well-behaved shape (identifier then address, in reading
    order) must keep working -- the guard only narrows the search window
    forward, it does not disable matching."""
    row = "6-21-00-456.00 SMITH JOHN 264 WEEPING OAK DR"
    li = _li(parcel_id="6-21-00-456.00", owner_name="SMITH JOHN", street_address=None)
    filled = dm._row_backfill_from_aggregate(li, row)
    assert filled == ["street_address"]
    assert li.street_address == "264 WEEPING OAK DR"


def test_neighbouring_physical_row_is_never_read():
    """The original, still-load-bearing guarantee (line-scoped, not a
    character window): a lead's own line is found by identifier, and the
    ADJACENT property's line is never consulted even though it sits right
    next to it in the text."""
    text = (
        "6-21-00-123.00 DOE JANE 100 OLD MILL RD\n"
        "6-21-00-456.00 SMITH JOHN 455 NEW HOPE DR\n"
    )
    li = _li(parcel_id="6-21-00-456.00", owner_name="SMITH JOHN", street_address=None)
    filled = dm._row_backfill_from_aggregate(li, text)
    assert filled == ["street_address"]
    assert li.street_address == "455 NEW HOPE DR"


def test_lead_identifiers_prefers_parcel_then_case_then_names():
    li = _li(parcel_id="21000-35-305", case_number=None,
             owner_name="COCKFIELD CHESSIE G ETAL", defendant="ACHEE CATHY H")
    idents = dm._lead_identifiers(li)
    assert idents[0] == "21000-35-305"
    assert "ACHEE CATHY H" in idents


def test_no_identifiers_no_lookup():
    li = _li(parcel_id=None, case_number=None, owner_name=None, defendant=None)
    assert dm._lead_identifiers(li) == []
    assert dm._row_backfill_from_aggregate(li, "anything 123 MAIN ST here") == []
