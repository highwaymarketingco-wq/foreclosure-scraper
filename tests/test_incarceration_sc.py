"""SC DOC (SCDC) incarceration matcher — gate logic.

SCDC was previously skipped (NC-only). The match is NAME-ONLY (no DOB) so it
must require EXACTLY ONE exact last+first hit, or a common name produces false
positives. Mocked so it doesn't depend on the live endpoint.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_incarceration import _scdc_match


class _FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        return self._d


class _FakeHTTP:
    def __init__(self, data, status=200):
        self._d, self._status = data, status

    async def post(self, url, params=None, timeout=None, headers=None):
        return _FakeResp(self._d, self._status)


@pytest.mark.asyncio
async def test_flags_unique_exact_match():
    # Fields are space-padded in the live feed — matcher must strip.
    http = _FakeHTTP([{"lname": "BROWN  ", "fname": "TAMMY ", "scdcId": "00376555"}])
    res = await _scdc_match(http, "BROWN", "TAMMY")
    assert res is not None
    assert res["state"] == "SC"
    assert res["scdc_id"] == "00376555"
    assert res["confidence"] == "name_only_low"


@pytest.mark.asyncio
async def test_rejects_common_name_with_multiple_exact():
    http = _FakeHTTP([
        {"lname": "SMITH", "fname": "JOHN", "scdcId": "1"},
        {"lname": "SMITH", "fname": "JOHN", "scdcId": "2"},
    ])
    assert await _scdc_match(http, "SMITH", "JOHN") is None  # too common -> noise


@pytest.mark.asyncio
async def test_ignores_non_exact_rows():
    # Search returns near-matches; only the exact last+first counts.
    http = _FakeHTTP([
        {"lname": "BROWNING", "fname": "TAMMY", "scdcId": "9"},
        {"lname": "BROWN", "fname": "TAMMYLYNN", "scdcId": "8"},
        {"lname": "BROWN", "fname": "TAMMY", "scdcId": "00376555"},
    ])
    res = await _scdc_match(http, "BROWN", "TAMMY")
    assert res is not None and res["scdc_id"] == "00376555"


@pytest.mark.asyncio
async def test_no_results_returns_none():
    assert await _scdc_match(_FakeHTTP([]), "ZZZQ", "NOBODY") is None


@pytest.mark.asyncio
async def test_non_200_returns_none():
    assert await _scdc_match(_FakeHTTP([], status=500), "BROWN", "TAMMY") is None
