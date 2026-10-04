"""Edgecombe County tax-foreclosure extraction-completeness audit (2026-10-01).

Live-pulled table (2026-10-01) has 18 real data rows but the scraper's
_PARCEL_RE only matched 17 of them: it assumed every parcel number is a
strict 4-2-4(-2) digit grouping ("4738-71-6101-00"), but one real row
(case 26CV002193-320, "1739 Thru St., Rocky Mt") carries a 4-4-4-2 grouping
("3759-7002-2140-00"). Because the per-row loop treats "no parcel match" as
"not a data row" (header / divider), that whole row -- including its
STATUS of "Sale 10/14/2026", the single highest-priority signal this source
carries -- was silently dropped. Widened _PARCEL_RE's group widths to fix."""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_nc import edgecombe_tax_foreclosure as edgecombe
from foreclosure_scraper.scrapers.counties_nc.edgecombe_tax_foreclosure import (
    _CASE_RE,
    _PARCEL_RE,
    _SALE_STATUS_RE,
    EdgecombeTaxForeclosure,
)

# Trimmed, structurally real fixture (2026-10-03 live pull): the page itself
# declares <base href="https://www.edgecombecountync.gov/" />, and the PARCEL
# cell of an in-progress row wraps its text in <a href="..."> linking the
# per-property foreclosure PDF. Both facts matter to the fix under test.
_LIST_PAGE_HTML = """
<html><head><base href="https://www.edgecombecountync.gov/" /></head><body>
<table>
<tr><td>PROPERTY DESCRIP.</td><td>TWN SHP</td><td>PARCEL</td><td>&nbsp;STATUS&nbsp;</td><td>FILE NO.</td><td>&nbsp;</td><td>&nbsp;</td></tr>
<tr>
<td>508 Mullins St., Princeville</td>
<td>&nbsp; &nbsp; 1</td>
<td>&nbsp; <a href="Departments/Tax Assessor/Foreclosure/508 Mullins St., Princeville.pdf?t=202609141147480" target="_blank">4737-89-6748-00</a></td>
<td>&nbsp; &nbsp; &nbsp; &nbsp;<em><strong>Sale 10/14/2026</strong></em></td>
<td>26CV002015-320</td>
<td>&nbsp;</td>
<td>&nbsp;</td>
</tr>
<tr>
<td>204 Neville St., Princeville</td>
<td>1</td>
<td>4738-71-6101-00</td>
<td>Complaint filed/Settlement pending</td>
<td>25CV003307-320</td>
<td>&nbsp;</td>
<td>&nbsp;</td>
</tr>
</table>
</body></html>
"""


def test_standard_4_2_4_2_parcel_still_matches():
    assert _PARCEL_RE.search("4738-71-6101-00").group(0) == "4738-71-6101-00"


def test_standard_4_2_4_parcel_without_trailing_group_matches():
    assert _PARCEL_RE.search("4724-21-1818").group(0) == "4724-21-1818"


def test_irregular_4_4_4_2_parcel_now_matches():
    """The real row this bug dropped: case 26CV002193-320, '1739 Thru St.'."""
    m = _PARCEL_RE.search("3759-7002-2140-00")
    assert m is not None
    assert m.group(0) == "3759-7002-2140-00"


def test_case_number_regex_ignores_trailing_ct_suffix():
    m = _CASE_RE.search("26CV001044-320 Ct 1")
    assert m.group(0) == "26CV001044-320"


def test_sale_status_regex_extracts_embedded_date():
    m = _SALE_STATUS_RE.search("Sale 10/14/2026")
    assert m is not None
    assert (m.group(1), m.group(2), m.group(3)) == ("10", "14", "2026")


def test_fetch_captures_per_property_pdf_resolved_against_site_root(monkeypatch):
    """The real gap: the PARCEL cell's <a href> (the per-property foreclosure
    PDF) must be captured and resolved against the page's <base href> (site
    root), NOT against PAGE_URL's own directory -- urljoin(PAGE_URL, href)
    would silently 404 (verified live 2026-10-03)."""
    async def fake_get_text(url, impersonate=True, timeout=40.0):
        assert url == edgecombe.PAGE_URL
        return _LIST_PAGE_HTML

    monkeypatch.setattr(edgecombe, "get_text", fake_get_text)
    rows = asyncio.run(EdgecombeTaxForeclosure().fetch())

    assert len(rows) == 2
    pdf_row = next(r for r in rows if r.parcel_id == "4737-89-6748-00")
    expected_url = (
        "https://www.edgecombecountync.gov/"
        "Departments/Tax Assessor/Foreclosure/508 Mullins St., Princeville.pdf"
        "?t=202609141147480"
    )
    assert pdf_row.raw["edgecombe_tax_foreclosure"]["document_url"] == expected_url
    assert pdf_row.raw["documents"] == [expected_url]
    assert pdf_row.raw["document_url"] == expected_url

    # The non-linked row must not gain a phantom document.
    plain_row = next(r for r in rows if r.parcel_id == "4738-71-6101-00")
    assert plain_row.raw["edgecombe_tax_foreclosure"]["document_url"] is None
    assert "documents" not in plain_row.raw
