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


# Mirrors the REAL live markup (captured 2026-10-01, national/reo per-source
# audit): the broker cell is two separate anchors, mailto: then tel:, joined
# by a bare <br> with no text separator -- .text() flattens this to
# "Rob Cuccinello239-537-5533", and the mailto: address (a free, direct
# contact channel) was dropped on the floor entirely.
_HTML_REAL_BROKER_MARKUP = (
    "<table>"
    "<tr><th>Location</th><th>Price</th><th>Type</th><th>Description</th><th>Broker</th></tr>"
    "<tr><th>7120 Myrtle Grove Rd, Wilmington, NC 28409</th><td>Please Inquire</td>"
    "<td>Vacant Land</td><td>1.19-acre lot</td>"
    '<td class="fcb-table__content-cell"><p>'
    '<a href="mailto:philipwmatthews@outlook.com">Philip Matthews</a><br>'
    '<a aria-label="9 1 9. 6 6 9. 5 3 6 1." href="tel:+19196695361">919-669-5361</a>'
    "</p></td></tr>"
    "</table>"
)


def test_parse_pulls_broker_email_and_phone_from_hrefs_not_flattened_text():
    out = parse(_HTML_REAL_BROKER_MARKUP)
    assert len(out) == 1
    raw = out[0].raw["first_citizens_reo"]
    assert raw["broker_email"] == "philipwmatthews@outlook.com"
    assert raw["broker_phone"] == "+19196695361"
    # The flattened display text (no separator between name and phone) is
    # still kept as-is for backward compatibility, just no longer the only
    # way to get the phone/email.
    assert raw["broker"] == "Philip Matthews919-669-5361"


def test_parse_broker_cell_without_links_leaves_email_phone_none():
    """The original fixture's plain-text broker cell (no <a> tags) must not
    crash and must leave the new fields None rather than fabricate a match."""
    out = parse(_HTML)
    for li in out:
        raw = li.raw["first_citizens_reo"]
        assert raw["broker_email"] is None
        assert raw["broker_phone"] is None
