"""New Hanover tax-foreclosure extraction-completeness audit (2026-10-01).

Each "View the <ADDRESS> property card" <li> carries an <a href> straight to
the county's own GIS/CAMA assessor record (etax.nhcgov.com Datalet, which
carries beds/baths/sqft/assessed value) -- a real external link HERMES
Section 8 calls out explicitly. ul.text()/li.text() strip all tags including
the href, so this link was being thrown away entirely. Fixed by reading the
anchor's href directly off each matching <li> and capturing it in raw.

HTML below is a trimmed, structurally faithful copy of the live page
(captured 2026-10-01, case 23CVS000524-640, 3 parcels)."""
from foreclosure_scraper.scrapers.counties_nc.new_hanover_foreclosures import parse

_PAGE_HTML = """
<html><body>
<ul>
<li>Parcel Numbers: R08818-001-002-000, R08818-001-004-000, &amp; R08818-001-005-000</li>
<li>Civil Number: <span>23CVS000524-640</span></li>
<li>Sale Date: May 22, 2026&nbsp;</li>
<li>Approximate Opening Bid: These properties are still available to bid on. Please contact Kania Law Firm, P.A.</li>
<li>View the <a href="https://etax.nhcgov.com/pt/Datalets/Datalet.aspx?UseSearch=no&amp;pin=R08818-001-002-000&amp;jur=NH&amp;taxyr=2023">600 Rocky Mount Avenue property card - R08818-001-002-000</a>.</li>
<li>View the <a href="https://etax.nhcgov.com/pt/Datalets/Datalet.aspx?UseSearch=no&amp;pin=R08818-001-004-000&amp;jur=NH&amp;taxyr=2023">604 Tarboro Avenue property card - R08818-001-004-000</a>.</li>
<li>View the <a href="https://etax.nhcgov.com/pt/Datalets/Datalet.aspx?UseSearch=no&amp;pin=R08818-001-005-000&amp;jur=NH&amp;taxyr=2023">600 Tarboro Avenue property card - R08818-001-005-000</a>.</li>
</ul>
</body></html>
"""


def test_property_card_urls_captured_per_parcel():
    rows = parse(_PAGE_HTML)
    assert len(rows) == 1
    li = rows[0]
    nh = li.raw["new_hanover_foreclosures"]
    assert nh["all_addresses"] == [
        "600 Rocky Mount Avenue", "604 Tarboro Avenue", "600 Tarboro Avenue",
    ]
    assert nh["property_card_urls"] == [
        "https://etax.nhcgov.com/pt/Datalets/Datalet.aspx?UseSearch=no&pin=R08818-001-002-000&jur=NH&taxyr=2023",
        "https://etax.nhcgov.com/pt/Datalets/Datalet.aspx?UseSearch=no&pin=R08818-001-004-000&jur=NH&taxyr=2023",
        "https://etax.nhcgov.com/pt/Datalets/Datalet.aspx?UseSearch=no&pin=R08818-001-005-000&jur=NH&taxyr=2023",
    ]
    # Unaffected: first-parcel / first-address promotion still anchors the row.
    assert li.street_address == "600 Rocky Mount Avenue"
    assert li.parcel_id == "R08818-001-002-000"
    assert li.case_number == "23CVS000524-640"


def test_property_card_url_missing_is_tolerated():
    """A <li> matching the address pattern but with no <a> (markup drift)
    must not crash -- the URL is simply omitted, not a parse failure."""
    html = """
    <ul>
    <li>Parcel Numbers: R08818-999-999-000</li>
    <li>Civil Number: 24CVS000001-640</li>
    <li>View the 123 Plain Street property card - R08818-999-999-000 .</li>
    </ul>
    """
    rows = parse(html)
    assert len(rows) == 1
    assert rows[0].raw["new_hanover_foreclosures"]["property_card_urls"] == []
