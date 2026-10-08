"""national.homepath_json asks the HomePath API for Fannie Mae's own REO inventory only.

The sibling fannie_homepath got listingTypes=5 on 2026-10-06 (c33369b5); this module, reading the
same endpoint, did not, so every ListHub MLS retail listing in the NC/SC bboxes was published as
ListingType.REO (2,098 rows on the 2026-10-08 run). Measured live 2026-10-08, page 1 of each state
bbox: NC 68,618 results without the filter vs 57 with it, SC 29,426 vs 22.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from foreclosure_scraper.scrapers.national import homepath_json as hj


class _Resp:
    status_code = 200

    def __init__(self, props):
        self._props = props

    def json(self):
        return {"properties": self._props, "totalProperties": len(self._props)}


def _prop(uuid, addr):
    return {
        "propertyUuid": uuid, "reoId": "R" + uuid, "addressLine1": addr, "city": "Greer",
        "state": "SC", "zipCode": "29651", "county": "Greenville", "price": 90000,
        "geoPoint": {"latitude": 34.9, "longitude": -82.2},
    }


def _sweep(monkeypatch, props):
    calls: list = []

    class _Client:
        async def get(self, url, params=None, headers=None, follow_redirects=True):
            calls.append((url, dict(params or {})))
            return _Resp(props)

    @asynccontextmanager
    async def fake_client(**kwargs):
        yield _Client()

    monkeypatch.setattr(hj, "client", fake_client)
    out = asyncio.run(hj._fetch_state("SC", hj.HomePathJSON.slug))
    return calls, out


def test_every_request_asks_for_reo_only(monkeypatch):
    calls, out = _sweep(monkeypatch, [_prop("u1", "1 Test Rd"), _prop("u2", "2 Test Rd")])
    assert calls, "the sweep made no request"
    for url, params in calls:
        assert url == hj.API
        assert params.get("listingTypes") == "5"
        assert params.get("bounds")
    assert len(out) == 2
    assert all(li.listing_type.value == "reo" for li in out)
