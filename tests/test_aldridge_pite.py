"""Aldridge Pite (NC trustee) — WordPress Posts Table Pro listings table.

Live-verified 2026-10-01: the real header is 9 columns — File Number |
Address | City | State | Zip | County | Date Listed | Current Bid |
hf:tax:county — the last one a `data-visible="false"` taxonomy-filter column
Posts Table Pro still server-renders a <td> for on every row. The old parser
read the bid off `cells[-1]` (the last column), which that hidden trailing
column would turn into the taxonomy term instead of the dollar bid the next
time the table actually has rows (it is empty between sale cycles right now,
so this never tripped live, but is a real latent "silent success" bug). The
old parser also never read "Date Listed" into sale_date at all.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.law_firms.aldridge_pite import _parse_listings

_NINE_COL_TABLE = """
<table class="posts-data-table">
<thead><tr>
<th>File Number</th><th>Address</th><th>City</th><th>State</th><th>Zip</th>
<th>County</th><th>Date Listed</th><th>Current Bid</th><th>hf:tax:county</th>
</tr></thead>
<tbody>
<tr><td>24-12345</td><td>123 Main St</td><td>Shelby</td><td>NC</td><td>28150</td>
<td>Cleveland</td><td>2026-11-05</td><td>$150,000.00</td><td>cleveland</td></tr>
<tr><td>24-67890</td><td>456 Oak Ave</td><td>Rutherfordton</td><td>NC</td><td>28139</td>
<td>Rutherford County</td><td>2026-12-01</td><td></td><td>rutherford</td></tr>
</tbody>
</table>
"""


def test_bid_reads_named_column_not_hidden_trailing_one():
    """The regression case: with a 9-column row, cells[-1] would be the
    hidden hf:tax:county value ("cleveland"), not the bid."""
    out = _parse_listings(_NINE_COL_TABLE, "https://aldridgepite.com/x", "NC", "law_firms.aldridge_pite")
    assert len(out) == 2
    assert out[0].opening_bid == 150000.0
    assert out[1].opening_bid is None  # blank bid cell, not the "rutherford" tax term


def test_date_listed_now_captured_as_sale_date():
    out = _parse_listings(_NINE_COL_TABLE, "https://aldridgepite.com/x", "NC", "law_firms.aldridge_pite")
    assert out[0].sale_date is not None
    assert out[0].sale_date.year == 2026 and out[0].sale_date.month == 11 and out[0].sale_date.day == 5


def test_county_suffix_stripped_and_case_number_kept():
    out = _parse_listings(_NINE_COL_TABLE, "https://aldridgepite.com/x", "NC", "law_firms.aldridge_pite")
    assert out[1].county == "Rutherford"
    assert out[1].case_number == "24-67890"


def test_empty_table_returns_no_rows():
    html = """
    <table class="posts-data-table">
    <thead><tr><th>File Number</th><th>Address</th><th>City</th><th>State</th>
    <th>Zip</th><th>County</th><th>Date Listed</th><th>Current Bid</th>
    <th>hf:tax:county</th></tr></thead>
    <tbody></tbody></table>
    """
    out = _parse_listings(html, "https://aldridgepite.com/x", "NC", "law_firms.aldridge_pite")
    assert out == []


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "law_firms.aldridge_pite" in {s.slug for s in all_scrapers()}
