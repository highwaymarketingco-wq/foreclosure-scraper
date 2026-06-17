"""First Citizens Bank REO scraper.

Discovered 2026-06-16 (from the owner's regional-bank lead). First Citizens
is the rare bank that posts bank-direct REO publicly. The page's table puts
the Location in a row-header <th>, the rest in <td> — the parser must read
both. NC/SC rows only.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.first_citizens_reo import parse, _LOC_RE
from foreclosure_scraper.models import ListingType, PropertyKind

# Mirrors the live markup: Location is a <th>, others <td>.
_HTML = """
<table>
<tr><th>Location</th><th>Price</th><th>Type</th><th>Description</th><th>Broker</th></tr>
<tr><th>7120 Myrtle Grove Rd, Wilmington, NC 28409</th><td>Please Inquire</td>
    <td>Vacant Land</td><td>1.19-acre lot</td><td>Matt Clawson 919-716-4183</td></tr>
<tr><th>805 Driftwood Ln, North, SC 29112</th><td>$95,000</td>
    <td>Residential</td><td>2 BR/1 BA cottage</td><td>Jane Doe 803-555-1212</td></tr>
<tr><th>22 Baltimore Rd, Rockville, MD 20850</th><td>Please Inquire</td>
    <td>Commercial</td><td>Office building</td><td>Jack Leary 443-463-9088</td></tr>
</table>
"""


def test_loc_re_parses_nc_sc():
    m = _LOC_RE.match("7120 Myrtle Grove Rd, Wilmington, NC 28409")
    assert m and m.group("state") == "NC" and m.group("city") == "Wilmington"
    assert m.group("zip") == "28409"


def test_parse_keeps_only_nc_sc_and_reads_th_location():
    out = parse(_HTML)
    # MD row dropped; NC + SC kept
    assert len(out) == 2
    states = {li.state for li in out}
    assert states == {"NC", "SC"}
    nc = next(li for li in out if li.state == "NC")
    assert nc.street_address == "7120 Myrtle Grove Rd"
    assert nc.city == "Wilmington"
    assert nc.property_kind == PropertyKind.LAND
    assert nc.listing_type == ListingType.REO
    sc = next(li for li in out if li.state == "SC")
    assert sc.opening_bid == 95000.0
    assert sc.property_kind == PropertyKind.SINGLE_FAMILY


def test_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "national.first_citizens_reo" in {s.slug for s in all_scrapers()}
