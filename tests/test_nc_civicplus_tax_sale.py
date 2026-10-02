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
    _parse_case_table_blocks,
    _parse_li_blocks,
    _parse_tax_sale_page,
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
