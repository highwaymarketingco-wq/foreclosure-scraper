"""NC eCourts Judgment Search (lis pendens + divorce lanes), 2026-10-08 audit.

* The divorce lane keeps judgmentType and caseCategoryKey (on every hit; the
  lis-pendens lane already kept them).
* Both lanes say so when the page cap ends the pass while the server reports
  more hits (live 2026-10-08: 80,061 hits / 90 days vs a 90,000 cap; 104,580 /
  120 days vs 120,000), instead of stopping silently.
Hits are invented, in the live shape.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
from structlog.testing import capture_logs

from foreclosure_scraper.scrapers.counties_nc import nc_ecourts_divorce as dv
from foreclosure_scraper.scrapers.counties_nc import nc_ecourts_lis_pendens as lp


def _hit(cause="FAM - Divorce", case="26CVD000001-100"):
    return {
        "caseNumber": case, "location": "Buncombe District Court", "causeOfActionDesc": cause,
        "civilJudgmentStatus": "Active", "judgmentType": "Granted in Whole or Part",
        "caseCategoryKey": "FAM", "caseID": 11, "judgmentId": 12,
        "orderedDate": "2026-09-28T23:00:00-05:00",
        "debtors": [{"name": "SAMPLE, PAT"}], "creditors": [{"name": "SAMPLE, ROBIN"}],
    }


def test_divorce_lane_keeps_judgment_type_and_category():
    li = dv.NCECourtsDivorce()._judgment_hit_to_listing(_hit())
    b = li.raw["nc_ecourts"]
    assert b["judgmentType"] == "Granted in Whole or Part"
    assert b["caseCategoryKey"] == "FAM"


class _Resp:
    status_code = 201

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _EndlessServer:
    """Every page is full and the server says there are many more."""

    def __init__(self):
        self.n = 0

    async def post(self, url, content=None, json=None, **kw):
        if content == b"":
            return _Resp({"searchObject": {}, "facets": []})
        self.n += 1
        return _Resp({"searchResult": {"totalHits": 999_999,
                                       "hits": [_hit(case=f"26CVD{self.n:06d}-100")]}})


def _fake_client(server):
    @asynccontextmanager
    async def _client(*a, **k):
        yield server
    return _client


def test_lis_pendens_lane_reports_a_binding_page_cap(monkeypatch):
    server = _EndlessServer()
    monkeypatch.setattr(lp, "client", _fake_client(server))
    monkeypatch.setattr(lp._fdh, "connect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db")))
    s = lp.NCECourtsLisPendens()
    s.MAX_PAGES = 3
    s.PAGE_SIZE = 1
    with capture_logs() as logs:
        asyncio.run(s.fetch())
    assert server.n == 3
    capped = [e for e in logs if e["event"] == "nc_ecourts.page_cap_reached"]
    assert capped and capped[0]["fetched"] == 3 and capped[0]["reported_total"] == 999_999


def test_divorce_lane_reports_a_binding_page_cap(monkeypatch):
    import foreclosure_scraper.http_client as hc
    server = _EndlessServer()
    monkeypatch.setattr(hc, "client", _fake_client(server))
    s = dv.NCECourtsDivorce()
    s.JUDGMENT_MAX_PAGES = 3
    s.JUDGMENT_PAGE_SIZE = 1
    with capture_logs() as logs:
        rows = asyncio.run(s.fetch())
    assert server.n == 3 and len(rows) == 3
    assert any(e["event"] == "nc_ecourts_divorce.page_cap_reached" for e in logs)
