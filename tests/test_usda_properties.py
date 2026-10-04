"""national.usda_properties — HERMES extraction-completeness audit,
national batch 5 (2026-10-04).

Two real gaps found and fixed, both confirmed live against the real current
site:

1. RAW_KEEP silent-drop: usda_data_type/usda_eligible/facts were flat
   top-level raw keys, none registered -- silently dropped at every
   publish. Fixed by namespacing under a new registered "usda_properties"
   key.
2. Each card's own detail page is a richer syndicated MLS page: a full
   photo gallery (5 real ap.rdcpix.com photos on a live sample vs. the
   single list-card thumbnail), lot size (acres + sqft), year built, a
   new-construction flag, garage spaces, HOA association + fee, a
   property-condition string, and the listing brokerage/team name. Wired
   as a best-effort per-row fetch capped at DETAIL_FETCH_CAP per county.

Fixtures below mirror the REAL card/detail markup captured live 2026-10-04
(569 Bill Lattimore Rd, Chesnee SC -- a real current Spartanburg listing).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.national import usda_properties as mod
from foreclosure_scraper.web_artifact import RAW_KEEP, _slim_raw

_CARD_HTML = """
<div id="hgGrid">
<div class="card" data-price="309950" data-beds="3" data-baths="2.0" data-type="home" data-elig="1" data-zip="29323">
  <a class="lc-imgwrap" href="/property/sc/29323/9435895293/">
    <img src="https://ap.rdcpix.com/d0b2eb14876961604d898ac723d9fe0el-m454708408m.jpg" alt="569 Bill Lattimore Rd">
  </a>
  <a class="lc-body-link" href="/property/sc/29323/9435895293/"><div class="cbody">
    <div class="cprice">$309,950</div>
    <div class="caddr">569 Bill Lattimore Rd</div>
    <div class="cfacts">3 bd &middot; 2 ba &middot; 1,450 sqft</div>
  </div></a>
</div>
</div>
""" + "x" * 5000

_DETAIL_HTML = """
<html><body>
<img src="https://ap.rdcpix.com/d0b2eb14876961604d898ac723d9fe0el-m454708408x.jpg">
<img src="https://ap.rdcpix.com/d0b2eb14876961604d898ac723d9fe0el-m656483730x.jpg">
<div class="feat"><h3>Land Info</h3><ul><li>Lot Description: Level</li><li>Lot Size Acres: 0.72</li><li>Lot Size Square Feet: 31363</li></ul></div>
<div class="feat"><h3>Garage and Parking</h3><ul><li>Garage Spaces: 2</li></ul></div>
<div class="feat"><h3>Homeowners Association</h3><ul><li>Association: No</li><li>Calculated Total Monthly Association Fees: 0</li></ul></div>
<div class="feat"><h3>Building and Construction</h3><ul><li>Year Built: 2025</li><li>New Construction: Yes</li><li>Property Condition: Under construction</li></ul></div>
<div class="la-info"><div class="la-by">Listed by</div><div class="la-name"><a href="/x">The Shulikov Team</a></div><div class="la-office">SHULIKOV REALTY &amp; ASSOCIATES</div></div>
</body></html>
""" + "x" * 2000


def test_parse_card_namespaces_raw_fields():
    from selectolax.parser import HTMLParser

    tree = HTMLParser(_CARD_HTML)
    card = tree.css_first("div.card")
    li = mod._parse_card(card, "spartanburg", "national.usda_properties")
    assert li is not None
    assert li.street_address == "569 Bill Lattimore Rd"
    assert li.opening_bid == 309950.0
    ns = li.raw["usda_properties"]
    assert ns["eligible"] is True
    assert ns["data_type"] == "home"


def test_usda_properties_key_registered_in_raw_keep():
    assert RAW_KEEP.get("usda_properties") == "*"


def test_previously_dropped_fields_survive_slim_raw_round_trip():
    from selectolax.parser import HTMLParser

    tree = HTMLParser(_CARD_HTML)
    card = tree.css_first("div.card")
    li = mod._parse_card(card, "spartanburg", "national.usda_properties")
    slim = _slim_raw(li.raw)
    assert slim.get("usda_properties") == li.raw["usda_properties"]
    assert slim.get("usda_property_id") == li.raw["usda_property_id"]


def test_fetch_detail_extracts_gallery_specs_and_brokerage(monkeypatch):
    async def fake_get_text(url, impersonate=True, timeout=20.0):
        return _DETAIL_HTML

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    out = asyncio.run(mod._fetch_detail("https://usdaproperties.com/property/sc/29323/9435895293/"))
    assert len(out["photos"]) == 2
    assert out["lot_sqft"] == "31363"
    assert out["year_built"] == "2025"
    assert out["new_construction"] == "Yes"
    assert out["garage_spaces"] == "2"
    assert out["hoa"] == "No"
    assert out["condition"] == "Under construction"
    # Real HTML entity in the live page must be unescaped.
    assert out["brokerage"] == "SHULIKOV REALTY & ASSOCIATES"
    assert out["listed_by"] == "The Shulikov Team"


def test_apply_detail_promotes_lot_size_and_year_built_to_first_class_fields():
    from selectolax.parser import HTMLParser

    tree = HTMLParser(_CARD_HTML)
    card = tree.css_first("div.card")
    li = mod._parse_card(card, "spartanburg", "national.usda_properties")
    detail = {
        "photos": ["https://ap.rdcpix.com/a.jpg", "https://ap.rdcpix.com/b.jpg"],
        "lot_sqft": "31363",
        "year_built": "2025",
        "new_construction": "Yes",
        "garage_spaces": "2",
        "hoa": "No",
        "hoa_fee": "0",
        "condition": "Under construction",
        "listed_by": "The Shulikov Team",
        "brokerage": "SHULIKOV REALTY & ASSOCIATES",
    }
    mod._apply_detail(li, detail)
    assert li.lot_size_sqft == 31363.0
    assert li.year_built == 2025
    assert li.raw["images"]["real"] == detail["photos"]
    assert li.raw["usda_properties"]["new_construction"] == "Yes"
    assert li.raw["usda_properties"]["brokerage"] == "SHULIKOV REALTY & ASSOCIATES"


def test_apply_detail_is_a_noop_on_empty_dict():
    from selectolax.parser import HTMLParser

    tree = HTMLParser(_CARD_HTML)
    card = tree.css_first("div.card")
    li = mod._parse_card(card, "spartanburg", "national.usda_properties")
    before = dict(li.raw["usda_properties"])
    mod._apply_detail(li, {})
    assert li.raw["usda_properties"] == before
    assert li.lot_size_sqft is None


def test_detail_fetch_cap_bounds_requests_per_county(monkeypatch):
    """DETAIL_FETCH_CAP must bound how many per-row detail fetches happen in
    one county, even when the county has far more cards than the cap."""
    call_count = {"n": 0}

    async def fake_get_text(url, impersonate=True, timeout=30.0):
        if "county" in url:
            # Build a page with more cards than DETAIL_FETCH_CAP.
            cards = "".join(
                f'<div class="card" data-price="100000" data-beds="2" '
                f'data-baths="1.0" data-type="home" data-elig="1" data-zip="29323">'
                f'<a href="/property/sc/29323/{i}/"><div class="caddr">{i} Main St</div></a>'
                f"</div>"
                for i in range(DETAIL_FETCH_CAP_TEST_SIZE)
            )
            return f'<div id="hgGrid">{cards}</div>' + "x" * 5000
        call_count["n"] += 1
        return _DETAIL_HTML

    DETAIL_FETCH_CAP_TEST_SIZE = mod.DETAIL_FETCH_CAP + 10
    monkeypatch.setattr(mod, "get_text", fake_get_text)
    rows = asyncio.run(mod._fetch_county("national.usda_properties", "spartanburg"))
    assert len(rows) == DETAIL_FETCH_CAP_TEST_SIZE
    assert call_count["n"] == mod.DETAIL_FETCH_CAP


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    assert "national.usda_properties" in {s.slug for s in all_scrapers()}
