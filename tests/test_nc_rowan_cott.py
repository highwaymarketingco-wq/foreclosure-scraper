"""counties_nc.nc_rowan_cott -- Rowan County NC Cott eSearch.

2026-10-13 source-completeness audit (Pattern C, Register-of-Deeds family):
the previous version of this scraper never actually reached the real site.
rod.rowancountync.gov/external redirects straight to a login page
(``Login.aspx``), which the old code's WAF-sniff (looking for "challenge"/
"turnstile"/"aws-waf" text) never matched, so it fell through to generic
date-input selectors against a page with no search form at all -- a silent,
permanent zero.

Live-verified 2026-10-13: the login page's "Sign in as a Guest" button grants
full, free, anonymous access (no CAPTCHA, no credentials) to the Date Range
search, a real results grid (ASP.NET GridView, NOT the generic ``table tr``
the old code guessed at), and a per-document "Document Details" page with the
richer grantor/grantee/returned-to/property-description fields the audit's
Cherokee finding was named for. These tests pin the new HTML parsing against
real, structurally-accurate fragments captured live from the real site
(trimmed for fixture size; field values/IDs are real).
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc import nc_rowan_cott as mod

# Trimmed but structurally real fragment of a Date Range search result grid
# (live-captured 2026-10-13, table id
# "ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments").
# Real column order: #, Date Filed, Index, Kind, Grantor, Grantee,
# Description, License Number (link), Book/Page (link), Ref, Amount, Images.
_RESULTS_HTML = """
<html><body>
<table id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments">
<tbody>
<tr class="cottPagedGridViewHeaderStyle">
<th>&nbsp;</th><th>Date Filed</th><th>Index</th><th>Kind</th><th>Grantor</th>
<th>Grantee</th><th>Description</th><th>License Number</th><th>Book/Page</th>
<th>Ref</th><th>Amount</th><th>Images</th><th></th>
</tr>
<tr tabindex="-1" class="cottPagedGridViewRowStyle">
<td>1</td><td align="center">09/14/2026</td><td>CRP</td><td>D/T</td>
<td><div><table width="100%"><tbody>
<tr><td colspan="2">ROWELL, SCOTT E.</td></tr>
<tr><td colspan="2">ROWELL, CAROLYN H</td></tr>
</tbody></table></div></td>
<td><div><table width="100%"><tbody>
<tr><td colspan="2">TRUIST BANK</td></tr>
</tbody></table></div></td>
<td><div><table width="100%"><tbody>
<tr><td colspan="2">EAST ALEXANDER HGTS CH GR Blk:C Lot:6</td></tr>
<tr><td colspan="2">PART IV</td></tr>
</tbody></table></div></td>
<td align="center"><a id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments_ctl02_lbDocument_FileNumberWithSuffix" href="javascript:void(0)"></a></td>
<td align="center"><a id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments_ctl02_lbDocument_BookPageSuffix" href="javascript:void(0)"> 1490 / 741</a></td>
<td align="center"><div><table width="100%"><tbody><tr><td colspan="2">&nbsp;</td></tr></tbody></table></div></td>
<td align="center">&nbsp;</td>
<td align="center">6</td>
</tr>
<tr tabindex="-1" class="cottPagedGridViewAltRowStyle">
<td>18</td><td align="center">09/14/2026</td><td>CRP</td><td>DEED</td>
<td><div><table width="100%"><tbody>
<tr><td colspan="2">NVR, INC.</td></tr>
</tbody></table></div></td>
<td><div><table width="100%"><tbody>
<tr><td colspan="2">DEADWILEY, JAYLAN D.</td></tr>
</tbody></table></div></td>
<td><div><table width="100%"><tbody>
<tr><td colspan="2">Parcel ID: 124-B-187-</td></tr>
<tr><td colspan="2">LIBERTY GROVE Lot:187</td></tr>
</tbody></table></div></td>
<td align="center"><a id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments_ctl19_lbDocument_FileNumberWithSuffix" href="javascript:void(0)"></a></td>
<td align="center"><a id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments_ctl19_lbDocument_BookPageSuffix" href="javascript:void(0)"> 1490 / 758</a></td>
<td align="center"><div><table width="100%"><tbody><tr><td colspan="2">&nbsp;</td></tr></tbody></table></div></td>
<td align="center">&nbsp;</td>
<td align="center">2</td>
</tr>
</tbody>
</table>
</body></html>
"""

# A page with NO results table at all (e.g. the login page the old code got
# stuck on, or an empty search) -- must parse to [], not raise.
_LOGIN_PAGE_HTML = """
<html><head><title>eSearch | Account Sign In</title></head><body>
<form><input type="text" name="UserID" /><input type="password" name="Password" />
<button type="submit">Sign in as a Guest</button></form>
</body></html>
"""

# Trimmed but structurally real fragment of a Document Details page
# (live-captured 2026-10-13 for book/page 1490/758, the NVR -> Deadwiley DEED
# above): Returned To filer address, Grantors/Grantees party tables, Property
# Information (parcel + legal description).
_DETAIL_HTML = """
<html><body>
<div id="ctl00_cphMain_divReturnToInformation">
<table id="ctl00_cphMain_gvReturnToInformation">
<tr class="GridView_Header"><th>Returned To</th><th>Address</th><th>Address (2)</th><th>City</th><th>State</th><th>ZIP</th></tr>
<tr class="GridView_Row"><td>NELSON &amp; GALBREATH LLC</td><td>131 FALLS STREET</td><td>SUITE 101</td><td>GREENVILLE</td><td>SC</td><td>29601</td></tr>
</table>
</div>
<div>
<table id="ctl00_cphMain_gvParties1" class="detailsGrid">
<tr class="GridView_Header"><th>GRANTORS</th></tr>
<tr class="GridView_Row"><td>NVR, INC.</td></tr>
</table>
</div>
<div>
<table id="ctl00_cphMain_gvParties2" class="detailsGrid">
<tr class="GridView_Header"><th>GRANTEES</th></tr>
<tr class="GridView_Row"><td>DEADWILEY, JAYLAN D.</td></tr>
</table>
</div>
<div id="ctl00_cphMain_divPropertyInformation">
<table id="ctl00_cphMain_gvProperty" class="detailsGrid">
<tr class="GridView_Header"><th>Property Information</th></tr>
<tr class="GridView_Row"><td><b>Parcel ID:</b> 124-B-187-<br />LIBERTY GROVE Lot:187 <br />PH1A MAP1<br /></td></tr>
</table>
</div>
</body></html>
"""


def test_parse_results_reads_real_grid_rows():
    rows = mod._parse_results(_RESULTS_HTML)
    assert len(rows) == 2

    r0 = rows[0]
    assert r0["date_filed"] == "09/14/2026"
    assert r0["index_type"] == "CRP"
    assert r0["kind"] == "D/T"
    assert r0["grantors"] == ["ROWELL, SCOTT E.", "ROWELL, CAROLYN H"]
    assert r0["grantees"] == ["TRUIST BANK"]
    assert "EAST ALEXANDER HGTS CH GR Blk:C Lot:6" in r0["description"]
    assert r0["book_page"] == "1490 / 741"
    assert r0["images_count"] == 6
    assert r0["detail_link_id"] == (
        "ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments_ctl02_lbDocument_BookPageSuffix"
    )

    r1 = rows[1]
    assert r1["kind"] == "DEED"
    assert r1["book_page"] == "1490 / 758"
    assert r1["images_count"] == 2


def test_parse_results_on_login_page_returns_empty():
    """Regression pin: the old scraper got stuck on exactly this page (a
    login screen, not a WAF challenge) and silently "succeeded" with 0 rows
    forever. The new parser must recognize there's no results grid here."""
    assert mod._parse_results(_LOGIN_PAGE_HTML) == []


def test_parse_detail_reads_returned_to_parties_and_property():
    detail = mod._parse_detail(_DETAIL_HTML)
    assert detail["returned_to"]["returned_to"] == "NELSON & GALBREATH LLC"
    assert detail["returned_to"]["city"] == "GREENVILLE"
    assert detail["returned_to"]["state"] == "SC"
    assert detail["grantors"] == ["NVR, INC."]
    assert detail["grantees"] == ["DEADWILEY, JAYLAN D."]
    assert "124-B-187" in detail["property_info"]
    assert "LIBERTY GROVE" in detail["property_info"]


def test_to_listing_without_detail_falls_back_to_grid_values():
    rows = mod._parse_results(_RESULTS_HTML)
    li = mod._to_listing("counties_nc.nc_rowan_cott", rows[0])
    assert li.county == "Rowan"
    assert li.state == "NC"
    assert li.case_number == "1490 / 741"
    assert li.owner_name == "TRUIST BANK"
    assert li.plaintiff == "ROWELL, SCOTT E.; ROWELL, CAROLYN H"
    assert li.raw["doc_type"] == "D/T"
    assert li.raw["book_page"] == "1490 / 741"
    assert li.raw["rowan_detail"]["images_count"] == 6
    # No detail fetched for this row -- detail-only sub-keys stay None, not crashed.
    assert li.raw["rowan_detail"]["returned_to"] is None


def test_to_listing_with_detail_prefers_document_details_fields():
    rows = mod._parse_results(_RESULTS_HTML)
    row = rows[1]
    row["detail"] = mod._parse_detail(_DETAIL_HTML)
    row["detail_url"] = (
        "https://rod.rowancountync.gov/external/LandRecords/protected/"
        "DocumentDetails.aspx?BaseFileNumb=qCmKiJCTK2Y%3d&ImageID=NNczUE5tLNg%3d"
    )
    li = mod._to_listing("counties_nc.nc_rowan_cott", row)
    assert li.owner_name == "DEADWILEY, JAYLAN D."
    assert li.plaintiff == "NVR, INC."
    assert li.legal_description is not None and "124-B-187" in li.legal_description
    assert li.raw["rowan_detail"]["returned_to"]["returned_to"] == "NELSON & GALBREATH LLC"
    assert li.raw["rowan_detail"]["detail_url"] == row["detail_url"]
    assert li.source_url == row["detail_url"]
