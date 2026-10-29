"""SEVERE_ENDPOINTS (the standing-order-to-demolish layer) was defined in
enrichment_code_enforcement.py but enrich_with_code_enforcement() only ever looped
over CITY_ENDPOINTS -- demolition-order severity has never fired for any row, for
any city, since the dict was added. Fixed 2026-10-29: a second pass checks
SEVERE_ENDPOINTS and merges a `severity` marker into whatever code_enforcement
block already exists, rather than overwriting it -- a miss on the demolish layer
means "no demolish order", not "no violations".
"""
from __future__ import annotations

import pytest

import foreclosure_scraper.enrichment_code_enforcement as M
from foreclosure_scraper.models import Listing


def _li(city="Charlotte", raw=None, lat=None, lon=None):
    return Listing(source="test", source_url="https://example.test/x", state="NC",
                   county="Mecklenburg", city=city, street_address="100 Main St",
                   latitude=lat, longitude=lon, raw=raw or {})


_DEMOLISH_FEAT = [{"attributes": {"CaseType": "Demolition", "CaseStatus": "Active",
                                  "DateCreated": "2026-01-01", "FullAddress": "100 Main St",
                                  "ParcelId": "123"}, "geometry": {}}]


@pytest.mark.asyncio
async def test_a_demolish_order_tags_severity_on_a_fresh_row(monkeypatch):
    async def fake_fetch(c, li, cfg):
        if cfg.get("severity") == "order_to_demolish":
            return _DEMOLISH_FEAT
        return []  # the ordinary CITY_ENDPOINTS layer answers, finds nothing

    monkeypatch.setattr(M, "_fetch_violations_for_listing", fake_fetch)
    li = _li()
    await M.enrich_with_code_enforcement([li])
    ce = li.raw["code_enforcement"]
    assert ce["severity"] == "order_to_demolish"
    assert ce["has_open"] is True


@pytest.mark.asyncio
async def test_a_demolish_order_merges_into_an_existing_open_violation_not_overwrite_it(monkeypatch):
    async def fake_fetch(c, li, cfg):
        if cfg.get("severity") == "order_to_demolish":
            return _DEMOLISH_FEAT
        return None  # city pass can't be asked this run -- existing block stands

    monkeypatch.setattr(M, "_fetch_violations_for_listing", fake_fetch)
    li = _li(raw={"code_enforcement": {"city": "Charlotte", "open_violations": 2,
                                        "total_violations": 2, "violations": [{"violation": "junk"}],
                                        "has_open": True, "source": M._SOURCE_TAG}})
    await M.enrich_with_code_enforcement([li])
    ce = li.raw["code_enforcement"]
    assert ce["severity"] == "order_to_demolish"
    assert ce["total_violations"] == 2        # the existing violation data was preserved
    assert ce["violations"] == [{"violation": "junk"}]


@pytest.mark.asyncio
async def test_no_demolish_order_never_clears_an_existing_block(monkeypatch):
    async def fake_fetch(c, li, cfg):
        return []  # both layers answer, neither finds anything for THIS property

    monkeypatch.setattr(M, "_fetch_violations_for_listing", fake_fetch)
    li = _li(raw={"code_enforcement": {"city": "Charlotte", "open_violations": 1,
                                        "total_violations": 1, "violations": [],
                                        "has_open": True, "source": "some_other_producer"}})
    await M.enrich_with_code_enforcement([li])
    # the regular pass clears its OWN prior writes only -- a different-producer block
    # is untouched by _clear_stale_block, and the severe pass (empty feats) never writes.
    assert li.raw["code_enforcement"]["source"] == "some_other_producer"
    assert "severity" not in li.raw["code_enforcement"]


@pytest.mark.asyncio
async def test_a_non_severe_city_is_unaffected():
    li = _li(city="Raleigh")
    # Real network call would be made for Raleigh's own CITY_ENDPOINTS entry here in
    # production; this test only needs to confirm Raleigh never enters the severe pass.
    severe_cities = set()
    for city_norm_candidate in ("Raleigh",):
        if city_norm_candidate in M.SEVERE_ENDPOINTS:
            severe_cities.add(city_norm_candidate)
    assert not severe_cities
