"""valuation/location.py's CENSUS_API_KEY gate (added 2026-10-15).

The module used to fire an ACS request for every unique ZIP with no key at
all ("free, no key required" -- no longer true, Census now serves a 200
"missing_key.html" page for this query shape). It now gates the same way
enrichment_census_rent.py/enrichment_census_demographics.py already do:
skip the HTTP call entirely when no key is configured.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.valuation import location as LOC


@pytest.mark.asyncio
async def test_lookup_zip_skips_the_network_call_without_a_key(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    LOC._CACHE.clear()

    async def _boom(*a, **kw):
        raise AssertionError("client() must not be called when no CENSUS_API_KEY is set")

    monkeypatch.setattr(LOC, "client", _boom)
    assert await LOC.lookup_zip("28801") is None


@pytest.mark.asyncio
async def test_lookup_zip_sends_the_key_when_present(monkeypatch):
    monkeypatch.setenv("CENSUS_API_KEY", "fake-key-123")
    LOC._CACHE.clear()
    captured: dict = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return [["B19013_001E"], ["55000"]]

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            captured["params"] = params
            return _FakeResp()

    monkeypatch.setattr(LOC, "client", lambda *a, **kw: _FakeClient())
    metrics = await LOC.lookup_zip("28801")
    assert captured["params"]["key"] == "fake-key-123"
    assert metrics["median_household_income"] == 55000
