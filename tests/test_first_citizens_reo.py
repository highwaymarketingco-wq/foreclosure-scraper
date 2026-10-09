"""First Citizens Bank REO scraper.

Discovered 2026-06-16 (from the owner's regional-bank lead). First Citizens
is the rare bank that posts bank-direct REO publicly. The page's table puts
the Location in a row-header <th>, the rest in <td> — the parser must read
both. NC/SC rows only.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from foreclosure_scraper.scrapers.national.first_citizens_reo import (
    FirstCitizensREO,
    parse,
    parse_json,
    _LOC_RE,
)
from foreclosure_scraper.models import ListingType, PropertyKind

# Mirrors the live markup: Location is a <th>, others <td>.
_HTML = """
<table>
<tr><th>Location</th><th>Price</th><th>Type</th><th>Description</th><th>Broker</th></tr>
<tr><th>7120 Myrtle Grove Rd, Wilmington, NC 28409</th><td>Please Inquire</td>
    <td>Vacant Land</td><td>1.19-acre lot</td><td>Mat Clawtest 919-555-0721</td></tr>
<tr><th>805 Driftwood Ln, North, SC 29112</th><td>$95,000</td>
    <td>Residential</td><td>2 BR/1 BA cottage</td><td>Jane Doe 803-555-1212</td></tr>
<tr><th>22 Baltimore Rd, Rockville, MD 20850</th><td>Please Inquire</td>
    <td>Commercial</td><td>Office building</td><td>Jake Learytest 443-555-0963</td></tr>
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
    '<a href="mailto:contact15@sample-mail.test">Phil Mathtest</a><br>'
    '<a aria-label="9 1 9. 5 5 5. 0 6 9 1." href="tel:+19195550691">919-555-0691</a>'
    "</p></td></tr>"
    "</table>"
)


def test_parse_pulls_broker_email_and_phone_from_hrefs_not_flattened_text():
    out = parse(_HTML_REAL_BROKER_MARKUP)
    assert len(out) == 1
    raw = out[0].raw["first_citizens_reo"]
    assert raw["broker_email"] == "contact15@sample-mail.test"
    assert raw["broker_phone"] == "+19195550691"
    # The flattened display text (no separator between name and phone) is
    # still kept as-is for backward compatibility, just no longer the only
    # way to get the phone/email.
    assert raw["broker"] == "Phil Mathtest919-555-0691"


def test_parse_broker_cell_without_links_leaves_email_phone_none():
    """The original fixture's plain-text broker cell (no <a> tags) must not
    crash and must leave the new fields None rather than fabricate a match."""
    out = parse(_HTML)
    for li in out:
        raw = li.raw["first_citizens_reo"]
        assert raw["broker_email"] is None
        assert raw["broker_phone"] is None


# ---------------------------------------------------------------------------
# Two findings, 2026-10-04 (national.* extraction-completeness audit,
# batch 16):
# 1. No row from this scraper, on EITHER path, ever carried a county --
#    main._countyless_national() drops ANY national.* row with no county
#    outright, so every genuinely in-footprint listing would have been
#    silently dropped at the very last stage despite looking correct
#    everywhere else.
# 2. The page's own `data-real-estate-url` AEM attribute points at a free,
#    public, no-auth JSON feed with the SAME data the rendered HTML table
#    shows -- already split into clean city/state/propertyType/phone/email
#    fields, no headless-browser render needed at all.
# ---------------------------------------------------------------------------

# A trimmed but real shape, captured live 2026-10-04 against
# .../col1/realestate.default.json
_REAL_JSON = json.dumps({
    "realEstateData": [
        {
            "propertyAddress": "7120 Myrtle Grove Rd, Wilmington, NC 28409",
            "city": "Wilmington", "state": "NC", "propertyType": "Vacant Land",
            "description": "1.19-acre lot", "price": "Please Inquire",
            "broker": "Phil Mathtest", "phone": "919-555-0691",
            "email": "contact15@sample-mail.test",
        },
        {
            "propertyAddress": "118 Hard St, Graniteville, SC 29829",
            "city": "Graniteville", "state": "SC", "propertyType": "Commercial",
            "description": "Manufacturing/recycling building on 4.7031 acres",
            "price": "Please Inquire", "broker": "Mathis Clawtest",
            "phone": "919-555-0721", "email": "contact16@sample-mail.test",
        },
        {
            "propertyAddress": "22 Baltimore Rd, Rockville, MD 20850",
            "city": "Rockville", "state": "MD", "propertyType": "Commercial",
            "description": "Historic office building", "price": "Please Inquire",
            "broker": "Jake Learytest", "phone": "443-555-0963",
            "email": "contact17@sample-mail.test",
        },
    ],
})


def test_parse_json_keeps_only_nc_sc_with_clean_fields():
    out = parse_json(_REAL_JSON)
    assert len(out) == 2  # MD row dropped
    nc = next(li for li in out if li.state == "NC")
    assert nc.city == "Wilmington"
    assert nc.street_address == "7120 Myrtle Grove Rd"
    assert nc.zip_code == "28409"
    assert nc.property_kind == PropertyKind.LAND
    assert nc.raw["first_citizens_reo"]["broker_phone"] == "919-555-0691"
    assert nc.raw["first_citizens_reo"]["broker_email"] == "contact15@sample-mail.test"


def test_parse_json_malformed_input_returns_empty_not_a_crash():
    assert parse_json("not json at all") == []
    assert parse_json("{}") == []
    assert parse_json(json.dumps({"realEstateData": "not a list"})) == []


def test_county_resolution_on_both_paths():
    """THE bug: neither path ever set county, so a national.* row with no
    county is dropped by main._countyless_national() regardless of
    everything else being correct. Wilmington, NC is a real, resolvable
    (if currently out-of-footprint/coastal) city in the shared gazetteer."""
    json_out = parse_json(_REAL_JSON)
    nc_json = next(li for li in json_out if li.state == "NC")
    assert nc_json.county == "New Hanover"

    html_out = parse(_HTML)
    nc_html = next(li for li in html_out if li.state == "NC")
    assert nc_html.county == "New Hanover"


def test_unresolvable_city_leaves_county_none_not_a_crash():
    row = json.dumps({"realEstateData": [{
        "propertyAddress": "1 Nowhere Ln, Zzyzx, SC 29999",
        "city": "Zzyzx", "state": "SC", "propertyType": "Residential",
        "description": "x", "price": "", "broker": "x", "phone": "", "email": "",
    }]})
    out = parse_json(row)
    assert len(out) == 1
    assert out[0].county is None


@pytest.mark.asyncio
async def test_fetch_uses_the_json_feed_and_never_touches_the_renderer():
    """The JSON path answering (even with a recognizable-but-empty feed)
    must short-circuit before paying for a StealthyFetcher render."""
    render_called = {"n": 0}

    async def fake_render(url):
        render_called["n"] += 1
        return "<table></table>"

    with patch(
        "foreclosure_scraper.scrapers.national.first_citizens_reo._fetch_json_text",
        return_value=_REAL_JSON,
    ), patch(
        "foreclosure_scraper.scrapers.national.first_citizens_reo._render_html",
        side_effect=fake_render,
    ):
        out = await FirstCitizensREO().fetch()

    assert len(out) == 2
    assert render_called["n"] == 0


@pytest.mark.asyncio
async def test_fetch_falls_back_to_the_renderer_when_json_fails():
    async def fake_json(url):
        return ""

    async def fake_render(url):
        return _HTML

    with patch(
        "foreclosure_scraper.scrapers.national.first_citizens_reo._fetch_json_text",
        side_effect=fake_json,
    ), patch(
        "foreclosure_scraper.scrapers.national.first_citizens_reo._render_html",
        side_effect=fake_render,
    ):
        out = await FirstCitizensREO().fetch()

    assert len(out) == 2  # the HTML fallback's own NC+SC rows
