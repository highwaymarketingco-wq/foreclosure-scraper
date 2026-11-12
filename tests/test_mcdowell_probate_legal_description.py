"""counties_nc.mcdowell_probate — legal_description gap (audit 2026-10-01).

Per-source extraction audit (docs/SOURCE_EXTRACTION_AUDIT.md / HERMES.md sec 8):
live-queried the McDowell_Parcels ArcGIS FeatureServer layer this scraper hits and found
``legdecfull`` (Full Legal Description) populated on 268/414 (65%) of the deceased-owner
parcels sampled, but the scraper neither requested it in ``outFields`` nor stored it in
``raw``. Useful when ``siteadd`` is vague or missing (e.g. "HWY 221 OFF" with no number).

This test is offline (no network): it feeds the scraper a synthetic ArcGIS response shaped
like the live one and asserts the new field round-trips into
``raw['mcdowell_probate']['legal_description']``, and that a blank/missing value stays None
rather than an empty string.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from foreclosure_scraper.scrapers.counties_nc import mcdowell_probate as M


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeHttp:
    """Serves one page of features, then an empty page to end pagination."""

    def __init__(self, features):
        self._pages = [{"features": features}, {"features": []}]
        self.requested_out_fields = None

    async def get(self, url, params=None):
        self.requested_out_fields = (params or {}).get("outFields")
        page = self._pages.pop(0) if self._pages else {"features": []}
        return _FakeResp(page)


def _patch_client(monkeypatch, fake):
    @asynccontextmanager
    async def cm(**kw):
        yield fake
    monkeypatch.setattr(M, "client", cm)


def _feature(parno, legdecfull=None, siteadd="  007862 OLD LINVILLE ROAD  "):
    return {"attributes": {
        "parno": parno,
        "ownname": "GROSS JEFFREY ALLEN",
        "ownname2": "GROSS PENNY L (DECEASED)",
        "mailadd": "7862 OLD LINVILLE RD ",
        "mcity": "MARION", "mstate": "NC", "mzip": "28752-5526",
        "siteadd": siteadd, "scity": "", "sstate": "NC", "szip": "",
        "improvval": 26220, "landval": 47460, "parval": 73680,
        "parvaltype": "Assessed", "gisacres": 1.93, "struct": "Y",
        "parusedesc": "", "structyear": 0,
        "sourceref": "Deed Book/Page 00741/0882", "saledatetx": "2003-7-1",
        "legdecfull": legdecfull,
    }}


def test_outfields_requests_legdecfull(monkeypatch):
    fake = _FakeHttp([_feature("P1", legdecfull="10.00 AC COMBINE")])
    _patch_client(monkeypatch, fake)
    asyncio.run(M.McDowellProbate().fetch())
    assert "legdecfull" in fake.requested_out_fields


def test_populated_legal_description_is_captured(monkeypatch):
    fake = _FakeHttp([_feature("P1", legdecfull="LOT #60-B LINVILLE MTN. A1.49AC")])
    _patch_client(monkeypatch, fake)
    rows = asyncio.run(M.McDowellProbate().fetch())
    assert len(rows) == 1
    assert rows[0].raw["mcdowell_probate"]["legal_description"] == "LOT #60-B LINVILLE MTN. A1.49AC"


def test_blank_legal_description_stays_none_not_empty_string(monkeypatch):
    fake = _FakeHttp([_feature("P1", legdecfull=""), _feature("P2", legdecfull=None)])
    _patch_client(monkeypatch, fake)
    rows = asyncio.run(M.McDowellProbate().fetch())
    assert len(rows) == 2
    for r in rows:
        assert r.raw["mcdowell_probate"]["legal_description"] is None
