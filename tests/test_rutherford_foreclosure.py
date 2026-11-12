"""Rutherford County NC tax-foreclosure sale calendar scraper.

No test file existed for this scraper before 2026-10-03 — which is likely
why its biggest bug (only reading the FIRST of two `<table>` elements on
the in-office page) went unnoticed: `tree.css_first("table")` silently
discarded the "UPCOMING PROPERTIES FOR SALE" table, which live-verified
2026-10-03 carried 20 real scheduled properties, while the one table it
did read held a single "tbd" placeholder row that got published as a junk
lead (street_address="tbd").
"""
from __future__ import annotations

import datetime

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_nc.rutherford_foreclosure import (
    _clean_tbd, _parse_in_office, _parse_kania, IN_OFFICE_URL,
)

NOW = datetime.datetime(2026, 10, 3)

# Mirrors the real live page structure 2026-10-03: an upset-bid-period table
# (currently an all-"tbd" placeholder row) followed by a separate "UPCOMING
# PROPERTIES FOR SALE" table with real rows.
_TWO_TABLE_HTML = """
<html><body>
<table>
<tr><td>Address</td><td>Parcel</td><td>File #</td><td>Tax Value</td>
<td>Current Bid</td><td>Last day to bid</td><td>Minimum bid amount</td>
<td>Property Record Card</td></tr>
<tr><td>tbd</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td>
<td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td><br/></td></tr>
</table>
<span>UPCOMING PROPERTIES FOR SALE</span>
<table>
<tr><td>Address</td><td>Parcel</td><td>File #</td><td>Tax Value</td>
<td>Sale Date and Time</td><td>Opening Bid</td><td>Property Record Card</td>
<td>Additional Info</td></tr>
<tr>
<td>262 Canine Dr, Bostic</td><td>1647549</td><td>tbd</td><td>$16,400</td>
<td>tbd</td><td>tbd</td>
<td><a href="https://lrcpwa.ncptscloud.com/Rutherford/parcel-detail/53813">Property Info</a></td>
<td>&nbsp;</td>
</tr>
<tr>
<td>0 Calhoun Trl, Rutherfordton</td><td>1614173</td><td>24M251</td><td>$6,200</td>
<td>10/30/2026</td><td>$2,396.40</td>
<td><a href="https://lrcpwa.ncptscloud.com/Rutherford/parcel-detail/30330">Property Info</a></td>
<td>&nbsp;</td>
</tr>
</table>
</body></html>
"""


def test_reads_both_tables_not_just_the_first():
    """The core regression: both the upset table and the upcoming table
    must contribute listings, not just whichever css_first("table") picks."""
    out = _parse_in_office(_TWO_TABLE_HTML, NOW)
    parcels = {l.parcel_id for l in out}
    assert "1647549" in parcels and "1614173" in parcels


def test_tbd_placeholder_row_is_skipped_not_published_as_a_junk_lead():
    """The upset table's only row is a full "tbd" placeholder — must not
    become a listing with street_address='tbd' / parcel_id=None."""
    out = _parse_in_office(_TWO_TABLE_HTML, NOW)
    assert not any(l.street_address == "tbd" for l in out)
    assert not any(l.parcel_id is None for l in out)


def test_upcoming_row_with_soft_tbd_date_has_no_sale_date_but_real_fields():
    out = _parse_in_office(_TWO_TABLE_HTML, NOW)
    li = next(l for l in out if l.parcel_id == "1647549")
    assert li.street_address == "262 Canine Dr"
    assert li.city == "Bostic"
    assert li.tax_value == 16400.0
    assert li.sale_date is None            # "tbd" sale date -> no concrete day
    assert li.opening_bid is None          # "tbd" opening bid -> no amount
    assert li.case_number is None          # "tbd" file # -> cleaned to None
    assert li.auction_status == "upcoming"
    assert li.listing_type is ListingType.TAX_SALE
    assert li.raw["rutherford_foreclosure"]["docket"] == "in_office"
    assert li.raw["rutherford_foreclosure"]["property_record_cards"] == [
        "https://lrcpwa.ncptscloud.com/Rutherford/parcel-detail/53813"
    ]


def test_upcoming_row_with_concrete_date_and_bid_parses_both():
    out = _parse_in_office(_TWO_TABLE_HTML, NOW)
    li = next(l for l in out if l.parcel_id == "1614173")
    assert li.city == "Rutherfordton"
    assert li.sale_date == datetime.datetime(2026, 10, 30)
    assert li.opening_bid == 2396.40
    assert li.case_number == "24M251"


def test_populated_upset_table_row_is_parsed_with_upset_fields():
    """When the CURRENT/upset table actually carries a real row (not the
    placeholder), it must be captured with upset-bid semantics, not read as
    an 'opening bid' / 'sale date' row."""
    html = """
    <table>
    <tr><td>Address</td><td>Parcel</td><td>File #</td><td>Tax Value</td>
    <td>Current Bid</td><td>Last day to bid</td><td>Minimum bid amount</td>
    <td>Property Record Card</td></tr>
    <tr><td>100 Main St, Spindale</td><td>999000</td><td>24M999</td>
    <td>$50,000</td><td>$40,000</td><td>8/31/2026</td><td>$42,000</td>
    <td><a href="https://lrcpwa.ncptscloud.com/Rutherford/parcel-detail/1">Property Info</a></td></tr>
    </table>
    """
    out = _parse_in_office(html, NOW)
    assert len(out) == 1
    li = out[0]
    assert li.parcel_id == "999000"
    assert li.street_address == "100 Main St"
    assert li.auction_status == "upset_period"
    assert li.opening_bid == 40000.0           # "current bid" -> opening_bid
    assert li.upset_bid_deadline == datetime.datetime(2026, 8, 31)
    assert li.raw["rutherford_foreclosure"]["docket"] == "in_office_upset"
    assert li.raw["rutherford_foreclosure"]["upset_amount_needed"] == 42000.0


def test_clean_tbd_treats_placeholder_values_as_blank():
    assert _clean_tbd("tbd") is None
    assert _clean_tbd("TBD") is None
    assert _clean_tbd("  tbd  ") is None
    assert _clean_tbd("N/A") is None
    assert _clean_tbd(None) is None
    assert _clean_tbd("") is None
    assert _clean_tbd("262 Canine Dr") == "262 Canine Dr"


def test_single_table_page_still_works_backward_compatibly():
    """A page with only the upcoming-schema table (no upset table at all)
    must still parse correctly — the fix must not assume exactly 2 tables."""
    html = """
    <table>
    <tr><td>Address</td><td>Parcel</td><td>File #</td><td>Tax Value</td>
    <td>Sale Date and Time</td><td>Opening Bid</td><td>Property Record Card</td></tr>
    <tr><td>5 Oak Ln, Ellenboro</td><td>555111</td><td>24M555</td><td>$9,000</td>
    <td>11/5/2026</td><td>$3,000</td><td></td></tr>
    </table>
    """
    out = _parse_in_office(html, NOW)
    assert len(out) == 1
    assert out[0].parcel_id == "555111"
    assert out[0].source_url == IN_OFFICE_URL


# --------------------------------------------------------------------------- Kania track

_KANIA_HTML = """
<div class="post">
<p>Current Foreclosures</p>
<p>Abrams, Christeen Logan – (1206540) - 141 Duncan St – File #23516</p>
<p>House with 0.51 acres</p>
<p>25CVD000199-800</p>
<p>Current Bid: $70,350.00, Amount needed to upset the bid: $73,867.50</p>
<p>Last day for upset bid: 8/31/2026</p>
</div>
"""


def test_kania_block_parses_owner_parcel_bid_and_deadline():
    out = _parse_kania(_KANIA_HTML, NOW)
    assert len(out) == 1
    li = out[0]
    assert li.owner_name == "Abrams, Christeen Logan"
    assert li.defendant == "Abrams, Christeen Logan"
    assert li.parcel_id == "1206540"
    assert li.street_address == "141 Duncan St"
    assert li.case_number == "25CVD000199-800"
    assert li.opening_bid == 70350.0
    assert li.upset_bid_deadline == datetime.datetime(2026, 8, 31)
    assert li.auction_status == "upset_period"
    assert li.raw["rutherford_foreclosure"]["docket"] == "outside_kania"
    assert li.raw["rutherford_foreclosure"]["upset_amount_needed"] == 73867.50
