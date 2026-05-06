"""Pin the paragraph-fallback parser for NC county tax-foreclosure pages.

The original helper assumed every NC county tax-admin page used a 5-column
HTML table. Smoke testing pre-Run-#15 found that Wake / Forsyth / Guilford /
Durham / New Hanover / Cleveland / Buncombe etc. all use Drupal accordions
or label-value tables instead. The fallback paragraph parser handles those.

These tests construct synthetic HTML matching each county's real layout and
verify the parser extracts the right parcel + address + sale date.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_nc._nc_tax_helper import (
    _parse_paragraph_blocks,
)


def _parse(html: str, county: str = "Wake"):
    return _parse_paragraph_blocks(
        slug=f"counties_nc.{county.lower()}_tax",
        county=county,
        url="https://example.com/foreclosure",
        html=html,
        fallback_sale_date=None,
        fallback_sale_location=None,
    )


# ------------------- Wake County (accordion paragraphs) ----------------------

WAKE_SAMPLE = """
<p>Tax ID#: <a href="/parcel/0047741">0047741</a> Amount due: $16,988.90*<br>
Property Address: 619 Cumberland St., Raleigh<br>
Date of First Action: July 18, 2024<br>
Date Judgment Filed with Courts: March 24, 2025<br>
Date of Sale: To Be Announced</p>

<p>Tax ID#: <a href="/parcel/0338065">0338065</a>&nbsp;Amount due: $13,474.98*<br>
Property Address: 5304 Sinesis Ct., Raleigh<br>
Date of Sale: To Be Announced</p>
"""


def test_wake_paragraph_parser_extracts_two_listings():
    out = _parse(WAKE_SAMPLE, county="Wake")
    assert len(out) == 2
    assert out[0].parcel_id == "0047741"
    assert "Cumberland" in (out[0].street_address or "")
    assert out[0].opening_bid == 16988.90
    assert out[1].parcel_id == "0338065"


# ------------------- New Hanover (multi-parcel under one case) ---------------

# Live New Hanover renders the parcel list, civil number, and sale date all
# in a single <li> when stripped — there's no <br> between fields, so the
# parser sees one logical line with all parcels grouped before the next
# field label.
NEW_HANOVER_SAMPLE = (
    "<ul>"
    "<li>Parcel Numbers: R08818-001-002-000, R08818-001-004-000, "
    "&amp; R08818-001-005-000</li>"
    "<li>Civil Number: 23CVS000524-640</li>"
    "<li>Sale Date: May 22, 2026&nbsp;</li>"
    "<li>Approximate Opening Bid: TBD</li>"
    "</ul>"
)


def test_new_hanover_multi_parcel_split():
    """Three physical parcels under one civil case → three listings, each
    inheriting the same sale_date and case_number."""
    out = _parse(NEW_HANOVER_SAMPLE, county="New Hanover")
    parcels = sorted(li.parcel_id for li in out)
    assert "R08818-001-002-000" in parcels
    assert "R08818-001-004-000" in parcels
    assert "R08818-001-005-000" in parcels
    assert len(out) == 3
    for li in out:
        assert li.case_number == "23CVS000524-640"
        # "May 22, 2026" should parse, not stay as fallback None
        assert li.sale_date is not None


# ------------------- Forsyth (label-value table) ------------------------------

FORSYTH_SAMPLE = """
<tr><td>PIN:</td><td><a>6835-89-0459.00</a></td></tr>
<tr><td>Block\\Lot:</td><td>0439 471</td></tr>
<tr><td>Tax Value:</td><td>$21,700</td></tr>
<tr><td>Min Bid:</td><td>$ 5,000</td></tr>
<tr><td>Owner:</td><td>ALBERTA S MORRISON ET AL</td></tr>
<tr><td>Description:</td><td>845 N JACKSON AVE WINSTON SALEM 27101</td></tr>
<tr><td>Sale Date &amp; Time:</td><td>Mar 06 2026 : 12 00 PM</td></tr>
"""


def test_forsyth_label_value_table_parses():
    """Forsyth uses a 2-column key:value table — parser should pick up the
    PIN, the description-as-address, the min-bid, and the sale date."""
    out = _parse(FORSYTH_SAMPLE, county="Forsyth")
    assert len(out) == 1
    li = out[0]
    assert li.parcel_id == "6835-89-0459.00"
    assert "JACKSON" in (li.street_address or "").upper()
    assert li.opening_bid == 5000.0
    assert li.sale_date is not None  # "Mar 06 2026" parses


# ------------------- Don't fire on prose ('PIN you may obtain...') -----------

PROSE_NOISE = """
<p>For your PIN you may obtain parcel data on our county website.
The PIN number on the deed is what you need.</p>
"""


def test_does_not_match_prose_noise():
    """The regex captures alphanumerics after a parcel preamble. Prose like
    'PIN you may obtain' must NOT be picked up as a listing."""
    out = _parse(PROSE_NOISE, county="Wake")
    assert out == []


# ------------------- Empty page ---------------------------------------------

def test_empty_html_returns_empty_list():
    assert _parse("<html><body><p>None at this time</p></body></html>") == []


# ------------------- Sale date 'TBD'/'TBA' falls back to None -----------------

TBD_SAMPLE = """
<p>Tax ID#: 0049102 Amount due: $13,453.29
Property Address: 1213 Savannah Dr., Raleigh
Date of Sale: TBD</p>
"""


def test_sale_date_tbd_does_not_misparse():
    """'TBD' / 'To Be Announced' should NOT be parsed as a real date — leave
    sale_date as None so downstream filters don't pin a wrong date."""
    out = _parse(TBD_SAMPLE)
    assert len(out) == 1
    assert out[0].sale_date is None
