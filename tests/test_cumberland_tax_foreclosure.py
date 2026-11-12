"""Cumberland County tax-foreclosure extraction-completeness audit (2026-10-01).

Two real bugs found live: (1) PAGE_URL was stale and silently served the
generic "Tax Administration" page (HTTP 200, no error) whose only <table>
elements are the office's own Phone/Fax/Address contact-info footer -- the
old "parse every <tr> on the page" scraper ingested THAT as if it were real
foreclosure rows (owner="Phone:", address="117 Dick Street..."). (2) sale_date
was never parsed, so every row -- garbage or real -- was silently dropped
downstream by main._active_only() (this slug was never in
DATELESS_OK_SOURCES). Fixed by targeting the data table by its header cells
and parsing all five real columns. HTML below is a trimmed, structurally
faithful copy of the live page (both the real data table and a contact-info
footer table), captured 2026-10-01."""
from foreclosure_scraper.scrapers.counties_nc.cumberland_tax_foreclosure import (
    _clean_owner,
    _find_data_table,
    _parse_sale_date,
    _split_location,
)

CONTACT_TABLE = """
<table class="table contact-us-table">
<tr><td>Phone:</td><td>910-555-0989</td></tr>
<tr><td>Address:</td><td>117 Dick Street, Room 530 Fayetteville, NC 28301</td></tr>
<tr><td>Fax:</td><td>910-555-0674</td></tr>
</table>
"""

DATA_TABLE = """
<table>
<tr style="background-color:#D6E8FF; text-align:center">
    <th><strong>Owners Name</strong></th>
    <th><strong>Property Location</strong></th>
    <th><strong>Parcel Number</strong></th>
    <th><strong>Bill Number</strong></th>
    <th><strong>Sale Date</strong></th>
</tr>
<tr class="table-item-row">
    <td><div>Weeks, John <span>(?)</span></div></td>
    <td><div>14.89 ACS Wade Elementary School</div></td>
    <td><div>0582604198000</div></td>
    <td><div>398277</div></td>
    <td><div>Jul 7, 2026</div></td>
</tr>
<tr class="table-alt-row">
    <td><div>Parker, Steven C <span>(?)</span></div></td>
    <td><div>RES 872 Southern Ave</div></td>
    <td><div>0436382619000</div></td>
    <td><div>358577</div></td>
    <td><div>Oct 8, 2026</div></td>
</tr>
</table>
"""

FULL_PAGE = f"<html><body>{CONTACT_TABLE}{DATA_TABLE}{CONTACT_TABLE}</body></html>"


def test_find_data_table_skips_contact_info_tables():
    """The real page carries the contact-info footer table BEFORE (and
    sometimes after) the real listing table -- must not treat it as data."""
    table = _find_data_table(FULL_PAGE)
    assert table is not None
    assert "Owners Name" in table
    assert "Phone:" not in table


def test_find_data_table_returns_none_when_absent():
    assert _find_data_table(f"<html><body>{CONTACT_TABLE}</body></html>") is None


def test_clean_owner_strips_tooltip_marker():
    assert _clean_owner("Weeks, John (?)") == "Weeks, John"
    assert _clean_owner("Starling, Wesley II  (?) ") == "Starling, Wesley II"


def test_split_location_promotes_real_street_address():
    addr, legal = _split_location("RES 872 Southern Ave")
    assert addr == "872 Southern Ave"
    assert legal is None


def test_split_location_keeps_legal_plat_description():
    addr, legal = _split_location("BLAWELL LO:10 PL:0035-0010")
    assert addr is None
    assert legal == "BLAWELL LO:10 PL:0035-0010"


def test_split_location_acreage_tract_is_not_a_street_address():
    """'14.89 ACS Wade Elementary School' starts with a digit+word like a
    street address but is an acreage legal description -- the ACS marker
    must keep it out of street_address."""
    addr, legal = _split_location("14.89 ACS Wade Elementary School")
    assert addr is None
    assert legal == "14.89 ACS Wade Elementary School"


def test_parse_sale_date():
    assert _parse_sale_date("Jul 7, 2026").isoformat()[:10] == "2026-07-07"
    assert _parse_sale_date("Oct 8, 2026").isoformat()[:10] == "2026-10-08"
    assert _parse_sale_date("") is None
    assert _parse_sale_date("To Be Announced") is None
