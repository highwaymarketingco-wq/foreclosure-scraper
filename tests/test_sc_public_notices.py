"""SC public-notices parser (scpublicnotices.com grid rows -> typed leads)."""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc import sc_public_notices as M
from foreclosure_scraper.models import ListingType

# A realistic GridView results fragment (two rows: in-scope foreclosure + out-of-scope).
_GRID = """
<table id="ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1">
<tr><td>The Herald-Journal Sunday, June 21, 2026 City: Spartanburg County: Spartanburg</td>
<td>STATE OF SOUTH CAROLINA IN THE COURT OF COMMON PLEAS COUNTY OF SPARTANBURG SUMMONS AND NOTICE
OF FILING OF COMPLAINT (NON-JURY MORTGAGE FORECLOSURE). ACME BANK, Plaintiff, vs JOHN Q DOE, Defendant.
The property located at 123 OAK ST, Spartanburg SC is subject to foreclosure.</td>
<td><input name="x$GridView1$ctl03$btnView2" onclick="javascript:location.href='Details.aspx?SID=abc&amp;ID=626766';"/></td></tr>
<tr><td>The Sumter Item Sunday, June 21, 2026 City: Sumter County: Sumter</td>
<td>NOTICE OF SALE foreclosure in Sumter</td>
<td><input name="x$GridView1$ctl04$btnView2" onclick="javascript:location.href='Details.aspx?SID=abc&amp;ID=626700';"/></td></tr>
</table>
"""

_PROBATE = """
<table id="GridView1"><tr>
<td>The Item Friday, June 19, 2026 City: Union County: Union</td>
<td>NOTICE TO CREDITORS OF THE ESTATE OF MARY R SMITH, deceased. All persons having claims...</td>
<td><input name="x$GridView1$ctl03$btnView2" onclick="location.href='Details.aspx?SID=abc&amp;ID=999';"/></td></tr></table>
"""


def test_parse_results_extracts_rows():
    rows = M._parse_results(_GRID)
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["county"] == "Spartanburg" and r0["city"] == "Spartanburg"
    assert r0["notice_id"] == "626766"
    assert "COMMON PLEAS" in r0["text"]


def test_in_scope_foreclosure_becomes_listing():
    rows = M._parse_results(_GRID)
    li = M._to_listing(rows[0], "4", "counties_sc.sc_public_notices")
    assert li is not None
    assert li.listing_type is ListingType.LIS_PENDENS   # summons/complaint = pre-foreclosure
    assert li.county == "Spartanburg" and li.state == "SC"
    assert li.defendant and "DOE" in li.defendant.upper()
    assert li.street_address and "OAK ST" in li.street_address.upper()


def test_out_of_scope_county_dropped():
    rows = M._parse_results(_GRID)
    assert M._to_listing(rows[1], "4", "counties_sc.sc_public_notices") is None  # Sumter not in scope


def test_sale_notice_classified_as_sale():
    row = {"county": "Pickens", "city": "", "date_text": "", "publication": "",
           "notice_id": "1", "text": "MASTER'S SALE will be sold at public auction the property of X"}
    li = M._to_listing(row, "4", "s")
    assert li.listing_type is ListingType.FORECLOSURE_SALE


def test_probate_creditor_notice():
    rows = M._parse_results(_PROBATE)
    li = M._to_listing(rows[0], "30", "s")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.raw["relationship_signal"]["kind"] == "probate"
    assert li.defendant and "SMITH" in li.defendant.upper()
