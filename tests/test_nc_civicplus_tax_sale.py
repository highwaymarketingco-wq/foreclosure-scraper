"""NC CivicPlus generic tax-sale fan-out scraper (~68 counties without a
dedicated scraper).

HERMES sec 8 audit, 2026-10-01. Live-confirmed two real bugs on this
scraper before the fix in this file's companion module:

1. ``ADDR_RE`` (and the sibling parcel/money regexes) had no word boundary
   before the street-suffix alternation. Combined with ``re.IGNORECASE``,
   the alternation matched a SUBSTRING inside an unrelated word -- "Addr" in
   "Address" satisfies "...Dr", "au[ct]ion" satisfies "...Ct" -- so ordinary
   page boilerplate was fabricated into a fake street address:
   Gaston's "103685 Physical Address:..." became street_address="103685
   Physical Addr", and Cherokee's buyer-beware prose ("...$750.00 will be
   due at the time of auction") became street_address="00 will be due at
   the time of auction" with NO real property backing it at all.
2. The free-text Pattern 2 fallback paired fields from a fixed character
   WINDOW around an address match rather than from the same list item, so
   on Alamance's prose <li> list (each item is its own property) the
   address of one property ("728 Rainbow Ave", parcel 132044) was emitted
   with the PARCEL of an unrelated adjacent property (172225, a vacant lot
   on a different street).

The fix adds two higher-priority, block-scoped parsers (``_parse_li_blocks``
for the Alamance-style prose <li> format, ``_parse_case_table_blocks`` for
the Cherokee-style flat &nbsp;-padded case/owner/PIN table) so every field
on one Listing comes from the SAME property's own block, and fixes the
regex boundary bug in the legacy fallback patterns.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc.nc_civicplus_tax_sale import (
    ADDR_RE,
    NcCivicplusTaxSaleScraper,
    _fetch_text,
    _parse_case_table_blocks,
    _parse_li_blocks,
    _parse_tax_sale_page,
    _pdf_to_text,
)

# Trimmed, field-faithful reproduction of the live Alamance County page
# (tax.alamancecountync.gov/home-1/tax-foreclosures/, read 2026-10-01).
ALAMANCE_HTML = """
<p><strong>PROPERTIES TO BE SOLD:</strong></p>
<ol>
<li><strong>Alamance County vs. Genron Corporation-</strong> a vacant lot located on Vaughn Road, Burlington, NC- <strong>Parcel ID#172225. </strong></li>
<li><strong>Alamance County vs. Marshall Yarbrough, Jr., Heirs- </strong>a house located at 728 Rainbow Ave., Burlington, NC-<strong> Parcel ID#132044.</strong></li>
<li><strong>Alamance County vs. Sarah Jane Hinton, (deceased) </strong>a vacant lot located at 117 E. Kime Street, Burlington, NC- <strong>Parcel ID#125958.</strong></li>
</ol>
"""

# Trimmed, field-faithful reproduction of the live Cherokee County page
# (cherokeecounty-nc.gov/227/Tax-Foreclosures, read 2026-10-01) -- a flat
# &nbsp;-padded table with no <table>/<tr> markup, followed by unrelated
# "buyer beware" prose that previously got mis-parsed as an address.
CHEROKEE_HTML = (
    "<p>The tax sale will take place on the steps of the Cherokee County "
    "Courthouse, located at 75 Peachtree St, Murphy, NC 28906.</p>"
    "<p>Case # &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Owner &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;PIN # &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;OPENING BID&nbsp;</p>"
    "<p>26CV000240-190 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;CORNWELL, WAYNE &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;4595-00-04-4495-000</p>"
    "<p>26CV000141-190 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;FLOYD, BETTY &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;4537-00-70-9110-000</p>"
    "<p>26CV000119-190 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;LEWIS, WILLIAM &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;4526-00-64-3493-000</p>"
    "<p>Note: a $750.00 deposit will be due at the time of auction. This is a "
    "buyer-beware sale -- all sales are final.</p>"
)


def test_li_blocks_attribute_address_and_parcel_to_the_same_property():
    """Regression for the cross-contamination bug: 728 Rainbow Ave must come
    back paired with ITS OWN parcel (132044), never the vacant-lot parcel
    (172225) from the preceding <li>."""
    out = _parse_li_blocks(ALAMANCE_HTML, "Alamance", "http://x")
    assert len(out) == 3
    by_parcel = {li.parcel_id: li for li in out}
    assert by_parcel["132044"].street_address == "728 Rainbow Ave"
    assert by_parcel["132044"].defendant == "Marshall Yarbrough"
    assert by_parcel["172225"].street_address is None  # vacant lot, no house number
    assert by_parcel["172225"].defendant == "Genron Corporation"
    assert "Vaughn Road" in (by_parcel["172225"].legal_description or "")
    assert by_parcel["125958"].street_address == "117 E. Kime Street"


def test_li_blocks_require_a_parcel_id_anchor():
    """A page with no 'Parcel ID#' tokens isn't this shape at all -- must not
    emit anything (falls through to the other tiers)."""
    assert _parse_li_blocks("<ol><li>No properties this quarter.</li></ol>", "Alamance", "http://x") == []


def test_case_table_blocks_extract_owner_and_hyphenated_pin():
    out = _parse_case_table_blocks(
        __import__("html").unescape(
            CHEROKEE_HTML.replace("<p>", " ").replace("</p>", " ")
        ),
        "Cherokee", "http://x",
    )
    assert len(out) == 3
    cases = {li.case_number: li for li in out}
    assert cases["26CV000240-190"].parcel_id == "4595-00-04-4495-000"
    assert cases["26CV000240-190"].owner_name == "CORNWELL, WAYNE"
    assert cases["26CV000141-190"].owner_name == "FLOYD, BETTY"


def test_full_page_parse_does_not_fabricate_address_from_boilerplate():
    """End-to-end regression for the live-confirmed fabrication: Cherokee's
    real output is the 3 case-table rows, NOT a fake 'street address' lifted
    from the buyer-beware / auction-deposit prose."""
    out = _parse_tax_sale_page(CHEROKEE_HTML, "Cherokee", "http://x")
    assert len(out) == 3
    for li in out:
        assert li.street_address is None
        # The courthouse's own address must never leak onto a property row.
        assert li.street_address != "75 Peachtree St"
    assert {li.case_number for li in out} == {
        "26CV000240-190", "26CV000141-190", "26CV000119-190",
    }


def test_full_page_parse_alamance_prose_wins_over_legacy_patterns():
    out = _parse_tax_sale_page(ALAMANCE_HTML, "Alamance", "http://x")
    assert len(out) == 3
    assert all(li.parcel_id for li in out)


def test_addr_re_does_not_match_inside_an_unrelated_word():
    """Direct regression for the IGNORECASE substring bug: 'Address' must not
    satisfy the '...Dr' alternative, and 'auction' must not satisfy '...Ct'."""
    assert ADDR_RE.search("103685 Physical Address: 401 Pryor St., Gastonia, NC") is None \
        or ADDR_RE.search("103685 Physical Address: 401 Pryor St., Gastonia, NC").group(1) != "103685 Physical Addr"
    assert ADDR_RE.search("00 will be due at the time of auction") is None


def test_addr_re_still_matches_a_real_address():
    m = ADDR_RE.search("a house located at 728 Rainbow Ave., Burlington, NC")
    assert m is not None
    assert "728 Rainbow Ave" in m.group(1)


def test_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "counties_nc.nc_civicplus_tax_sale" in {s.slug for s in all_scrapers()}
    assert NcCivicplusTaxSaleScraper.slug == "counties_nc.nc_civicplus_tax_sale"


# ===========================================================================
# PDF RESPONSES WERE BEING DECODED AS GARBAGE, NOT PARSED, 2026-10-03
#
# This module's own docstring has said since it was written that it "also
# checks those known [PDF/XLSX] URLs" -- but `_fetch_text` handed every PDF
# response straight to httpx's `.text`, a raw bytes-as-string decode of
# binary PDF content, which can never match any of this module's own regexes
# (they are all text-shaped: ADDR_RE, MONEY_RE, NC_CASE_RE, ...). Live-
# confirmed on Davidson County's own 2.8MB/35-page "Tax-Foreclosures-PDF"
# (updated by the county 2026-09-17): `.text` decoded it to a `%PDF-1.7
# ... /Type/Catalog ...` byte dump, 0 listings found. Extracting real text
# via `pypdf` first -- the SAME library already used for this exact purpose
# by the sibling nc_county_pdf_delinquent_tax.py -- let the EXISTING
# `_parse_tax_sale_page()` tiers correctly find 21 real pending-sale
# properties (real street addresses, parcel IDs, dollar amounts) sitting
# behind that one PDF with NO other code change: the parser could already
# handle this shape of text, it was just never given real text to parse.
# ===========================================================================

def _make_pdf(text: str) -> bytes:
    """Build a minimal, genuinely valid single-page PDF whose content stream
    is exactly `text`, drawn with the one built-in Helvetica font -- so
    `pypdf.PdfReader(...).extract_text()` recovers it character-for-character.
    No fixture file needed; this is the same pypdf.generic machinery pypdf's
    own PdfWriter uses internally, just assembled by hand for a test."""
    import io

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=200)

    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 10 100 Td ({escaped}) Tj ET".encode("latin-1"))
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


def test_pdf_to_text_extracts_real_text_not_binary_garbage():
    pdf_bytes = _make_pdf("405 Moore Dr Tax Id 11342A0000034 Tax Value $309,150.00")
    assert pdf_bytes[:4] == b"%PDF"
    text = _pdf_to_text(pdf_bytes)
    assert "405 Moore Dr" in text
    assert "$309,150.00" in text
    assert "11342A0000034" in text


def test_pdf_to_text_is_silent_on_garbage_bytes():
    """Must never raise -- a corrupt/moved/scanned-image-only PDF is reported
    as an empty fetch, same as any other failed fetch, not a crash."""
    assert _pdf_to_text(b"not a real pdf at all") == ""
    assert _pdf_to_text(b"") == ""


def test_pdf_extracted_text_flows_through_the_existing_parser():
    """The real, measured value of the fix: once given REAL text instead of
    binary, the free-text Pattern 2 tier this module already had finds the
    property with no new parsing code at all -- same shape as the live
    Davidson County PDF (address, Tax Id, dollar amount in prose, no HTML)."""
    pdf_bytes = _make_pdf(
        "405 Moore Dr Tax Id 1117800250006 Tax Value (2026) $309,150.00"
    )
    text = _pdf_to_text(pdf_bytes)
    listings = _parse_tax_sale_page(text, "Davidson", "http://x/Tax-Foreclosures-PDF")
    assert len(listings) == 1
    li = listings[0]
    assert "405 Moore Dr" in li.street_address
    assert li.parcel_id == "1117800250006"
    assert li.raw["nc_civicplus_tax_sale"]["current_bid"] == 309150.0


def test_fetch_text_dispatches_pdf_responses_through_pdf_to_text(monkeypatch):
    """Integration boundary: a 200 response whose body starts with the PDF
    magic bytes must be routed through `_pdf_to_text`, not `resp.text`."""
    import asyncio

    pdf_bytes = _make_pdf("110 Sink Inn Rd Tax Value $36,210.00")

    class _FakeResp:
        status_code = 200
        content = pdf_bytes

        @property
        def text(self):
            # If this is ever read for a PDF response, the bug has regressed.
            raise AssertionError("must not decode a PDF body via .text")

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return _FakeResp()

    monkeypatch.setattr(
        "foreclosure_scraper.http_client.client",
        lambda timeout=20.0: _FakeClient(),
    )

    out = asyncio.run(_fetch_text("http://example.gov/Tax-Foreclosures-PDF"))
    assert "110 Sink Inn Rd" in out
    assert "$36,210.00" in out


def test_fetch_text_still_returns_plain_html_unchanged(monkeypatch):
    """Non-PDF responses must take the old, unchanged `.text` path."""
    import asyncio

    class _FakeResp:
        status_code = 200
        content = b"<html>not a pdf</html>"
        text = "<html>not a pdf</html>"

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return _FakeResp()

    monkeypatch.setattr(
        "foreclosure_scraper.http_client.client",
        lambda timeout=20.0: _FakeClient(),
    )

    out = asyncio.run(_fetch_text("http://example.gov/page.html"))
    assert out == "<html>not a pdf</html>"
