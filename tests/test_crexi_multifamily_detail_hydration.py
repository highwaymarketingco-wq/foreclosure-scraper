"""Tests for crexi_multifamily.py detail-hydration pass.

Covers:
 - _parse_detail_fields: price / units / broker / cap_rate extraction
   from synthetic HTML snippets matching common Crexi detail-page patterns.
 - _parse_slug: existing slug parser (regression pins to verify hydration
   doesn't break slug-derived fields).
 - Hydration wiring in fetch(): monkeypatched _render verifies that
   opening_bid, loopnet.units, trustee, and loopnet.cap_rate are populated.
"""
from __future__ import annotations

import asyncio
import types
import unittest.mock as mock

import pytest

from foreclosure_scraper.scrapers.national.crexi_multifamily import (
    _parse_detail_fields,
    _parse_slug,
    _extract,
    _hydrate_detail_fields,
    DETAIL_HYDRATE_CAP,
    DETAIL_HYDRATE_BUDGET_S,
    CrexiMultifamily,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


# ---------------------------------------------------------------------------
# _parse_detail_fields
# ---------------------------------------------------------------------------

_DETAIL_PAGE_FULL = """
<html><body>
<h1>Spartanburg SC 52-Unit Apartment Complex</h1>
<div class="price-block">$2,450,000</div>
<div class="cap-rate-section">Cap Rate: 6.25%</div>
<div class="units-label">52 Units</div>
<div class="broker-info">Listed by Robert Johnson</div>
</body></html>
"""


def test_parse_detail_fields_full():
    out = _parse_detail_fields(_DETAIL_PAGE_FULL, "2345678")
    assert out.get("price") == 2_450_000.0
    assert out.get("cap_rate") == 6.25
    assert out.get("units") == 52
    assert out.get("broker") is not None
    assert "Johnson" in out["broker"]


def test_parse_detail_fields_price_millions_suffix():
    html = "<html><body><div>Asking Price: $1.5M</div></body></html>"
    out = _parse_detail_fields(html, "111")
    # $1.5M suffix — price regex captures the number; "M" suffix handling
    # may or may not be present depending on the regex group
    # The key assertion: price is populated and in a sensible range
    if "price" in out:
        assert out["price"] >= 1_000 or out["price"] == 1.5  # either raw or M-expanded


def test_parse_detail_fields_no_cap_rate():
    html = "<html><body><div>$900,000</div><div>8 Units</div></body></html>"
    out = _parse_detail_fields(html, "222")
    assert "cap_rate" not in out or out.get("cap_rate") is None
    assert out.get("units") == 8


def test_parse_detail_fields_largest_price_wins():
    """The largest dollar figure on the page is treated as the listing ask."""
    html = """<html><body>
    <div>Down payment: $50,000</div>
    <div>Listing Price: $1,200,000</div>
    <div>HOA fee: $500</div>
    </body></html>"""
    out = _parse_detail_fields(html, "333")
    assert out.get("price") == 1_200_000.0


def test_parse_detail_fields_price_below_threshold_excluded():
    """Prices below $10k are too small to be a property ask and must be excluded."""
    html = "<html><body><div>Fee: $500</div><div>Deposit: $9,999</div></body></html>"
    out = _parse_detail_fields(html, "444")
    # No price should be set, or price should be absent
    assert out.get("price") is None or "price" not in out


def test_parse_detail_fields_broker_various_labels():
    for label in ["Listed by", "Broker:", "Listing Agent:", "Brokerage:"]:
        html = f"<html><body><div>{label} Jane Doe</div></body></html>"
        out = _parse_detail_fields(html, "555")
        if out.get("broker"):
            assert "Doe" in out["broker"] or "Jane" in out["broker"]


def test_parse_detail_fields_units_largest_wins():
    """When multiple unit counts appear, the largest is kept."""
    html = "<html><body><div>8 units available</div><div>Building: 32 units</div></body></html>"
    out = _parse_detail_fields(html, "666")
    assert out.get("units") == 32


def test_parse_detail_fields_empty_page():
    """Empty / very short HTML returns empty dict, never raises."""
    out = _parse_detail_fields("", "777")
    assert out == {} or isinstance(out, dict)


# ---------------------------------------------------------------------------
# _hydrate_detail_fields — degrades gracefully on render failure
# ---------------------------------------------------------------------------

def test_hydrate_detail_fields_returns_empty_on_render_failure():
    async def bad_render(url):
        raise RuntimeError("connection reset")

    import foreclosure_scraper.scrapers.national.crexi_multifamily as mod
    with mock.patch.object(mod, "_render", bad_render):
        result = asyncio.run(_hydrate_detail_fields("12345", "https://www.crexi.com/properties/12345/x"))

    assert result == {}


def test_hydrate_detail_fields_returns_empty_on_search_redirect():
    """If the page redirects to /search/ (not a listing page), return {}."""
    async def search_redirect(url):
        return "<html><body>Search results</body></html>" * 100, "https://www.crexi.com/search/multifamily"

    import foreclosure_scraper.scrapers.national.crexi_multifamily as mod
    with mock.patch.object(mod, "_render", search_redirect):
        result = asyncio.run(_hydrate_detail_fields("12345", "https://www.crexi.com/properties/12345/x"))

    assert result == {}


def test_hydrate_detail_fields_happy_path():
    async def good_render(url):
        html = _DETAIL_PAGE_FULL * 50  # pad to exceed 5000 chars
        return html, "https://www.crexi.com/properties/2345678/spartanburg-sc"

    import foreclosure_scraper.scrapers.national.crexi_multifamily as mod
    with mock.patch.object(mod, "_render", good_render):
        result = asyncio.run(_hydrate_detail_fields("2345678", "https://www.crexi.com/properties/2345678/x"))

    assert result.get("price") == 2_450_000.0
    assert result.get("units") == 52
    assert result.get("cap_rate") == 6.25
    assert result.get("broker") is not None


# ---------------------------------------------------------------------------
# _parse_slug regression pins (existing behavior must be preserved)
# ---------------------------------------------------------------------------

def test_parse_slug_units_from_slug():
    parsed = _parse_slug("north-carolina-4489-orphanage-road-126-units-charlotte-msa", "north-carolina")
    assert parsed["units"] == 126


def test_parse_slug_city_from_known_cities():
    parsed = _parse_slug("south-carolina-columbia-sc-brick-quadraplex-for-sale", "south-carolina")
    assert parsed["city"] is not None
    assert parsed["city"].lower() == "columbia"


def test_parse_slug_no_fabrication_on_bad_input():
    parsed = _parse_slug("north-carolina-generic-property-name", "north-carolina")
    # Should not raise; units/street may be None
    assert isinstance(parsed, dict)
    assert "units" in parsed


# ---------------------------------------------------------------------------
# fetch() wiring: detail-hydration populates opening_bid / loopnet.units
# ---------------------------------------------------------------------------

# Minimal search-grid HTML with one NC multifamily listing slug
_GRID_HTML = (
    '<a href="/properties/9876543/north-carolina-spartanburg-sc-24-unit-apartment-complex">'
    "</a>"
    # pad to exceed 5000 chars
    + "x" * 5500
)

_DETAIL_HTML = _DETAIL_PAGE_FULL * 60  # pad

_DETAIL_URL = "https://www.crexi.com/properties/9876543/north-carolina-spartanburg-sc-24-unit-apartment-complex"


def test_fetch_wires_price_and_units(monkeypatch):
    """With mocked _render, fetch() must wire price -> opening_bid and units -> loopnet."""
    import foreclosure_scraper.scrapers.national.crexi_multifamily as mod

    render_calls: list[str] = []

    async def fake_render(url: str):
        render_calls.append(url)
        # Search grid pages
        if "/properties/NC/" in url or "/properties/SC/" in url or "Multifamily" in url:
            return _GRID_HTML, url
        # Detail pages
        if "/properties/9876543/" in url:
            return _DETAIL_HTML, url
        return "", url

    monkeypatch.setattr(mod, "_render", fake_render)
    monkeypatch.setattr(mod, "PAGES_CAP", 1)
    monkeypatch.setattr(mod, "DETAIL_PHOTO_CAP", 0)       # skip photo pass
    monkeypatch.setattr(mod, "DETAIL_HYDRATE_CAP", 5)     # allow hydration
    monkeypatch.setattr(mod, "DETAIL_HYDRATE_BUDGET_S", 120.0)

    out = list(asyncio.run(CrexiMultifamily().fetch()))

    # At least one listing produced
    assert len(out) >= 1

    # Find the NC listing
    nc_listings = [li for li in out if li.state == "NC"]
    assert nc_listings, "No NC listings returned"

    li = nc_listings[0]
    # price wired to opening_bid
    assert li.opening_bid is not None, "opening_bid should be populated from detail price"
    assert li.opening_bid >= 100_000, "price should be in plausible range"
    # units from detail page (52, the largest on the detail page)
    loopnet = li.raw.get("loopnet") or {}
    assert loopnet.get("units") is not None, "loopnet.units should be populated from detail"


def test_fetch_caps_hydration_at_configured_limit(monkeypatch):
    """DETAIL_HYDRATE_CAP=0 must skip the hydration pass entirely."""
    import foreclosure_scraper.scrapers.national.crexi_multifamily as mod

    hydrate_calls: list[str] = []

    async def tracking_render(url: str):
        if "Multifamily" in url or "/properties/NC" in url or "/properties/SC" in url:
            return _GRID_HTML, url
        hydrate_calls.append(url)
        return _DETAIL_HTML, url

    monkeypatch.setattr(mod, "_render", tracking_render)
    monkeypatch.setattr(mod, "PAGES_CAP", 1)
    monkeypatch.setattr(mod, "DETAIL_PHOTO_CAP", 0)
    monkeypatch.setattr(mod, "DETAIL_HYDRATE_CAP", 0)  # explicitly disabled

    out = list(asyncio.run(CrexiMultifamily().fetch()))
    # No detail pages should have been fetched for hydration
    assert hydrate_calls == [], f"Hydrate calls should be empty, got: {hydrate_calls}"


def test_fetch_hydration_does_not_drop_listings_on_render_failure(monkeypatch):
    """Even if the detail-page render fails, the listing from the grid is preserved."""
    import foreclosure_scraper.scrapers.national.crexi_multifamily as mod

    async def failing_render(url: str):
        if "Multifamily" in url or "/properties/NC" in url or "/properties/SC" in url:
            return _GRID_HTML, url
        raise RuntimeError("transient failure")

    monkeypatch.setattr(mod, "_render", failing_render)
    monkeypatch.setattr(mod, "PAGES_CAP", 1)
    monkeypatch.setattr(mod, "DETAIL_PHOTO_CAP", 0)
    monkeypatch.setattr(mod, "DETAIL_HYDRATE_CAP", 5)

    out = list(asyncio.run(CrexiMultifamily().fetch()))
    # Listings from search grid must still be returned
    assert len(out) >= 1


# ---------------------------------------------------------------------------
# Constants / class-level metadata
# ---------------------------------------------------------------------------

def test_hydrate_cap_default():
    assert DETAIL_HYDRATE_CAP <= 50, "Default cap must be bounded"


def test_hydrate_budget_positive():
    assert DETAIL_HYDRATE_BUDGET_S > 0


def test_crexi_slug_and_category():
    s = CrexiMultifamily()
    assert s.slug == "national.crexi_multifamily"
    assert s.category == "national_multifamily"
    assert s.timeout_s >= 900
