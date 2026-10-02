"""Wake County tax-foreclosure extraction-completeness audit (2026-10-01).

The accordion list links each Tax ID# to its own Account.asp detail page
(already used as source_url) but the scraper never fetched it. That page
carries the owner name(s) -- often multiple heirs, a motivated-seller signal
the accordion never shows -- the owner's mailing address (separate from the
property address when absentee/out-of-area), heated square footage, acreage,
zoning, and the county's assessed value. Fixed by best-effort fetching that
page and promoting these fields, including a raw['owner_mailing'] blob in the
exact shape enrichment_owner_mailing.py itself writes.

HTML fixtures below are trimmed, structurally faithful copies of two real
live Account.asp pages (ids 0047895 and 0047741, captured 2026-10-01): one
owner-occupied, multi-heir; one absentee via a third-party mailing address."""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_nc import wake_tax_foreclosure as wake
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

_OWNER_OCCUPIED_ACCOUNT_HTML = """
<TD WIDTH="100%">Property Owner</FONT></TD></TR>
<TR VALIGN=top><TD WIDTH=100%><B><FONT SIZE=2 FACE=Arial> MITCHELL, GEORGE JR HEIRS</FONT></B></TD>
<TR VALIGN=top><TD WIDTH=100%><B><FONT SIZE=2 FACE=Arial> SMITH, MILDRED L HEIRS </FONT></B></TD></TR>
<TR VALIGN=top><TD WIDTH=100% NOWRAP = "True"><FONT SIZE=2 FACE=Arial COLOR=blue>
(Use the Deeds link to view any additional owners)
</FONT></TD></TR></TABLE></TD>
<TD WIDTH="33%"><TD WIDTH="100%">Owner's Mailing Address</FONT></TD></TR>
<TR VALIGN=top><TD WIDTH="100%"><B><FONT SIZE=2 FACE="Arial">610 CUMBERLAND ST</FONT></B></TD></TR>
<TR VALIGN=top><TD WIDTH="100%"><B><FONT SIZE=2 FACE="Arial">RALEIGH NC 27610-3871</FONT></B></TD></TR>
<TD WIDTH="33%"><TD WIDTH="100%">Property Location Address</FONT></TD></TR>
<TR VALIGN=top><TD WIDTH="100%"><B><FONT SIZE=2 FACE="Arial">610  CUMBERLAND ST  </FONT></B></TD></TR>
<TR VALIGN=top><TD WIDTH="100%"><B><FONT SIZE=2 FACE="Arial">RALEIGH&nbsp;NC&nbsp;27610-3871</FONT></B></TD></TR>
<TD WIDTH="97%" COLSPAN=2 VALIGN=bottom><B><FONT SIZE=2 FACE="Arial">Administrative Data</B></FONT></TD>
<TD WIDTH="36%"><FONT SIZE=2 FACE="Arial">Zoning</FONT></TD>
<TD WIDTH="47%"><DIV ALIGN=right><B><FONT SIZE=2 FACE="Arial">NX-3</FONT></B></DIV></TD></TR>
<TD WIDTH="36%"><FONT SIZE=2 FACE="Arial">Land Class</FONT></TD>
<TD WIDTH="47%"><DIV ALIGN=right><B><FONT SIZE=2 FACE="Arial">R-<10-HS</FONT></B></DIV></TD></TR>
<TD WIDTH="36%"><FONT SIZE=2 FACE="Arial">Acreage</FONT></TD>
<TD WIDTH="47%"><DIV ALIGN=right><B><FONT SIZE=2 FACE="Arial">.19</FONT></B></DIV></TD></TR>
<TD WIDTH="46%"><FONT SIZE=2 FACE="Arial">Deed Date</FONT></TD>
<TD WIDTH="37%"><DIV ALIGN=right><B><FONT SIZE=2 FACE="Arial">5/13/2016</FONT></B></DIV></TD></TR>
<TD WIDTH="46%"><FONT SIZE=2 FACE="Arial">Heated Area</FONT></TD>
<TD WIDTH="37%"><DIV ALIGN=right><B><FONT SIZE=2 FACE="Arial">952</FONT></B></DIV></TD></TR>
<TD WIDTH="36%"><FONT SIZE=2 FACE="Arial">Land Value Assessed</FONT></TD>
<TD WIDTH="47%"><DIV ALIGN=right><B><FONT SIZE=2 FACE="Arial">$173,796</FONT></B></DIV></TD></TR>
<TD WIDTH="36%"><FONT SIZE=2 FACE="Arial">Bldg. Value Assessed</FONT></TD>
<TD WIDTH="47%"><DIV ALIGN=right><B><FONT SIZE=2 FACE="Arial">$3,776</FONT></B></DIV></TD></TR>
<TD WIDTH="34%">Total Value Assessed*</FONT></TD>
<TD WIDTH="34%"><DIV ALIGN=right><FONT SIZE=2 Color=red FACE="Arial"></FONT><B><FONT SIZE=2 FACE="Arial">$177,572</FONT></B></DIV></TD></TR>
"""

_ABSENTEE_ACCOUNT_HTML = """
<TD WIDTH="100%">Property Owner</FONT></TD></TR>
<TR VALIGN=top><TD WIDTH=100%><B><FONT SIZE=2 FACE=Arial> GIBBS, DOROTHY MITCHELL</FONT></B></TD>
<TR VALIGN=top><TD WIDTH=100%><B><FONT SIZE=2 FACE=Arial> OVERTON, MARY M HEIRS </FONT></B></TD></TR>
<TR VALIGN=top><TD WIDTH=100% NOWRAP = "True"><FONT SIZE=2 FACE=Arial COLOR=blue>
(Use the Deeds link to view any additional owners)
</FONT></TD></TR></TABLE></TD>
<TD WIDTH="33%"><TD WIDTH="100%">Owner's Mailing Address</FONT></TD></TR>
<TR VALIGN=top><TD WIDTH="100%"><B><FONT SIZE=2 FACE="Arial">CLAUDETTE C KELLY</FONT></B></TD></TR>
<TR VALIGN=top><TD WIDTH="100%"><B><FONT SIZE=2 FACE="Arial">250 VILLAGE CREEK CIR APT A</FONT></B></TD></TR>
<TR VALIGN=top><TD WIDTH="100%"><B><FONT SIZE=2 FACE="Arial">WINSTON SALEM NC 27104-4742</FONT></B></TD></TR>
<TD WIDTH="33%"><TD WIDTH="100%">Property Location Address</FONT></TD></TR>
<TR VALIGN=top><TD WIDTH="100%"><B><FONT SIZE=2 FACE="Arial">619  CUMBERLAND ST  </FONT></B></TD></TR>
<TR VALIGN=top><TD WIDTH="100%"><B><FONT SIZE=2 FACE="Arial">RALEIGH&nbsp;NC&nbsp;27610-3801</FONT></B></TD></TR>
<TD WIDTH="97%" COLSPAN=2 VALIGN=bottom><B><FONT SIZE=2 FACE="Arial">Administrative Data</B></FONT></TD>
<TD WIDTH="46%"><FONT SIZE=2 FACE="Arial">Heated Area</FONT></TD>
<TD WIDTH="37%"><DIV ALIGN=right><B><FONT SIZE=2 FACE="Arial"></FONT></B></DIV></TD></TR>
"""


def _bare_listing(source_url: str) -> Listing:
    return Listing(
        source=wake.WakeTaxForeclosure.slug,
        source_url=source_url,
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Wake", parcel_id="0047895",
        street_address="610 Cumberland St., Raleigh",
        raw={"wake_tax_foreclosure": {}},
    )


def test_account_field_handles_embedded_unescaped_angle_bracket():
    """Land Class ('R-<10-HS') has a literal unescaped '<' in the source
    HTML -- a naive [^<]* capture would truncate at it."""
    assert wake._account_field(_OWNER_OCCUPIED_ACCOUNT_HTML, "Land Class") == "R-<10-HS"


def test_enrich_from_account_page_owner_occupied(monkeypatch):
    li = _bare_listing("https://services.wake.gov/realestate/Account.asp?id=0047895")

    async def fake_get_text(url, impersonate=True, timeout=30.0):
        return _OWNER_OCCUPIED_ACCOUNT_HTML

    monkeypatch.setattr(wake, "get_text", fake_get_text)
    asyncio.run(wake._enrich_from_account_page(li))

    assert li.owner_name == "MITCHELL, GEORGE JR HEIRS; SMITH, MILDRED L HEIRS"
    assert li.zoning == "NX-3"
    assert li.acreage == 0.19
    assert li.living_sqft == 952.0
    assert li.assessed_value == 177572.0
    assert li.market_value == 177572.0

    om = li.raw["owner_mailing"]
    assert om["mailing"] == "610 CUMBERLAND ST, RALEIGH NC 27610-3871"
    assert om["absentee"] is False
    assert om["out_of_state"] is False
    assert om["mail_state"] == "NC"


def test_enrich_from_account_page_detects_absentee_third_party_mailing(monkeypatch):
    li = _bare_listing("https://services.wake.gov/realestate/Account.asp?id=0047741")
    li.street_address = "619 Cumberland St., Raleigh"

    async def fake_get_text(url, impersonate=True, timeout=30.0):
        return _ABSENTEE_ACCOUNT_HTML

    monkeypatch.setattr(wake, "get_text", fake_get_text)
    asyncio.run(wake._enrich_from_account_page(li))

    assert li.owner_name == "GIBBS, DOROTHY MITCHELL; OVERTON, MARY M HEIRS"
    om = li.raw["owner_mailing"]
    assert om["mailing"] == "CLAUDETTE C KELLY, 250 VILLAGE CREEK CIR APT A, WINSTON SALEM NC 27104-4742"
    assert om["situs"] == "619 CUMBERLAND ST, RALEIGH NC 27610-3801"
    assert om["absentee"] is True
    assert om["out_of_state"] is False
    # Blank Heated Area on this property must not crash or set a 0 sqft.
    assert li.living_sqft is None


def test_enrich_from_account_page_tolerates_fetch_failure(monkeypatch):
    li = _bare_listing("https://services.wake.gov/realestate/Account.asp?id=0047895")

    async def failing_get_text(*a, **kw):
        raise TimeoutError("boom")

    monkeypatch.setattr(wake, "get_text", failing_get_text)
    asyncio.run(wake._enrich_from_account_page(li))  # must not raise
    assert li.owner_name is None
    assert "owner_mailing" not in li.raw
