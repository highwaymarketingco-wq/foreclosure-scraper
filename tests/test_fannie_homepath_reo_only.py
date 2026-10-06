"""national.fannie_homepath asks the API for Fannie Mae's own REO inventory only.

Without listingTypes=5 the HomePath search also returns ListHub MLS retail listings from other
sellers (listingType LISTHUB), and every one of them was published as a REO flip. Measured live
2026-10-06 on one Upstate SC cell: 400 results, 392 LISTHUB and 8 REO; with listingTypes=5 exactly
those 8 (totalProperties 8). docs/source_reverification_2026-09-10.md D39 had documented it on 9/10
(71 true REO rows replacing 494 mislabeled ones). The board held 857 'REO' rows from this source,
most of them retail.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from foreclosure_scraper.scrapers.national import fannie_homepath as hp


class _Resp:
    status_code = 200

    def __init__(self, props, total=None):
        self._props = props
        self._total = len(props) if total is None else total

    def json(self):
        return {"properties": self._props, "totalProperties": self._total}


class _FakeClient:
    def __init__(self, calls, props):
        self.calls = calls
        self.props = props

    async def get(self, url, params=None, headers=None, follow_redirects=True):
        self.calls.append((url, dict(params or {})))
        return _Resp(self.props)


def _prop(uuid, addr="1 Test Rd", city="Greer", zipc="29651"):
    return {
        "propertyUuid": uuid,
        "reoId": "R" + uuid,
        "addressLine1": addr,
        "city": city,
        "state": "SC",
        "zipCode": zipc,
        "county": "Greenville",
        "price": 100000,
        "bedrooms": 3,
        "bathrooms": 2,
        "sqft": 1500,
        "geoPoint": {"lat": 34.9, "lon": -82.2},
    }


def _run_fetch(monkeypatch, props):
    calls: list = []

    @asynccontextmanager
    async def fake_client(**kwargs):
        yield _FakeClient(calls, props)

    monkeypatch.setattr(hp, "client", fake_client)
    out = asyncio.run(hp._fetch_bbox("SC", 34.4625, -82.075, 35.2625, -80.9375, "national.fannie_homepath"))
    return calls, out


def test_every_request_asks_for_reo_only(monkeypatch):
    calls, out = _run_fetch(monkeypatch, [_prop("u1"), _prop("u2", addr="2 Test Rd")])
    assert calls, "the scraper made no request"
    for url, params in calls:
        assert url == hp.API
        assert params.get("listingTypes") == "5"
        assert params.get("bounds") == "34.4625,-82.075,35.2625,-80.9375"
    assert len(out) == 2


def test_reo_only_cell_ends_at_page_one(monkeypatch):
    # with the filter a cell is far below the 400-row page cap, so paging stops after one request
    calls, _ = _run_fetch(monkeypatch, [_prop("u1")])
    assert len(calls) == 1
    assert calls[0][1]["page"] == "1"
