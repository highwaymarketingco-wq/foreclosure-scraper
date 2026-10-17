"""nc_ecourts_lis_pendens.NCECourtsLisPendens.fetch: a transient transport/timeout error on
either of this file's two network calls gets retried, not treated as "zero this run."

Found 2026-10-16 (gap-sweep, pre-run gate's additions audit): the Tyler Judgment Search
template fetch (`c.post(SERVICE_URL, content=b"")`, line ~595) and the per-page search POST
inside the `for _ in range(self.MAX_PAGES)` pagination loop (`c.post(SERVICE_URL, json=so)`,
line ~634) both go through the shared `http_client.client()` async context manager, which
builds its transport with `retries=0` and expects every caller to wrap its own AsyncRetrying
-- this file never did. On `except Exception`, the template fetch does `return []` (zeroes
the whole file's output) and the per-page search does `break` (discards every remaining
page). This source is listed in `main.DATELESS_OK_SOURCES` -- no fallback date window means
a run zeroed by a single transient blip silently reports empty/"healthy" forever, the same
failure mode already fixed tonight for the Column legal-notice API scraper,
spartan_weekly_legals.py, and arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import nc_ecourts_lis_pendens as lp

TEMPLATE_PAYLOAD = {"searchObject": {}, "facets": []}


def _hit(case="26CV000001-100"):
    return {
        "caseNumber": case, "location": "Buncombe District Court",
        "causeOfActionDesc": "CV - Lis Pendens", "civilJudgmentStatus": "Active",
        "judgmentType": "Filed", "caseCategoryKey": "CV", "caseID": 1, "judgmentId": 2,
        "orderedDate": "2026-09-28T23:00:00-05:00",
        "debtors": [{"name": "SAMPLE, PAT"}], "creditors": [{"name": "LENDER, SAMPLE"}],
    }


class _Resp:
    def __init__(self, payload, status_code=201):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)[:300]

    def json(self):
        return self._payload


def _fake_client(server):
    @asynccontextmanager
    async def _client(*a, **kw):
        yield server
    return _client


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(lp, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


@pytest.fixture(autouse=True)
def _no_real_db(monkeypatch):
    # The docket-history sidecar is best-effort and never fatal to fetch(); keep it from
    # touching a real sqlite file during these tests.
    monkeypatch.setattr(lp._fdh, "connect",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db in test")))


# ---------------------------------------------------------------------------
# Call site 1: the one-shot template fetch (`c.post(SERVICE_URL, content=b"")`)
# ---------------------------------------------------------------------------

class _TemplateFlaky:
    """Template fetch fails `fail_times` times, then succeeds; the page search
    that follows immediately reports zero hits, so fetch() returns quickly."""

    def __init__(self, fail_times: int, exc=None, template_status=201):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.template_status = template_status
        self.template_calls = 0
        self.search_calls = 0

    async def post(self, url, content=None, json=None, **kw):
        if content == b"":
            self.template_calls += 1
            if self.template_calls <= self.fail_times:
                raise self.exc
            return _Resp(TEMPLATE_PAYLOAD, status_code=self.template_status)
        self.search_calls += 1
        return _Resp({"searchResult": {"totalHits": 0, "hits": []}})


def test_template_fetch_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    server = _TemplateFlaky(fail_times=2)
    monkeypatch.setattr(lp, "client", _fake_client(server))
    rows = asyncio.run(lp.NCECourtsLisPendens().fetch())
    assert server.template_calls == 3
    assert rows == []


def test_template_fetch_timeout_that_never_clears_gives_up_after_budget_not_hang(monkeypatch):
    server = _TemplateFlaky(fail_times=99)
    monkeypatch.setattr(lp, "client", _fake_client(server))
    rows = asyncio.run(lp.NCECourtsLisPendens().fetch())
    assert server.template_calls == 3     # stop_after_attempt(3), then gives up -- no hang
    assert rows == []                     # outer except still catches it -> graceful []


def test_template_fetch_real_bad_status_is_not_retried(monkeypatch):
    class _BadStatus:
        def __init__(self):
            self.calls = 0

        async def post(self, url, content=None, json=None, **kw):
            self.calls += 1
            return _Resp({}, status_code=500)

    server = _BadStatus()
    monkeypatch.setattr(lp, "client", _fake_client(server))
    rows = asyncio.run(lp.NCECourtsLisPendens().fetch())
    assert server.calls == 1   # a real bad status is not a transport/timeout error
    assert rows == []


# ---------------------------------------------------------------------------
# Call site 2: the per-page search POST inside the pagination loop
# (`c.post(SERVICE_URL, json=so)`)
# ---------------------------------------------------------------------------

class _PageFlaky:
    """Template fetch always succeeds immediately; the first page search fails
    `fail_times` times, then returns one real hit and a terminal totalHits."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.search_calls = 0

    async def post(self, url, content=None, json=None, **kw):
        if content == b"":
            return _Resp(TEMPLATE_PAYLOAD)
        self.search_calls += 1
        if self.search_calls <= self.fail_times:
            raise self.exc
        return _Resp({"searchResult": {"totalHits": 1, "hits": [_hit()]}})


def test_page_search_transient_read_timeout_is_retried_and_then_succeeds(monkeypatch):
    server = _PageFlaky(fail_times=2, exc=httpx.ReadTimeout("slow"))
    monkeypatch.setattr(lp, "client", _fake_client(server))
    rows = asyncio.run(lp.NCECourtsLisPendens().fetch())
    assert server.search_calls == 3
    assert len(rows) == 1
    assert rows[0].case_number == "26CV000001-100"


def test_page_search_timeout_that_never_clears_salvages_whatever_was_fetched(monkeypatch):
    server = _PageFlaky(fail_times=99)
    monkeypatch.setattr(lp, "client", _fake_client(server))
    rows = asyncio.run(lp.NCECourtsLisPendens().fetch())
    assert server.search_calls == 3   # stop_after_attempt(3), then the loop breaks -- no hang
    assert rows == []                 # nothing had been fetched yet (failed on page 0)


def test_page_search_real_bad_status_is_not_retried(monkeypatch):
    class _PageBadStatus:
        def __init__(self):
            self.search_calls = 0

        async def post(self, url, content=None, json=None, **kw):
            if content == b"":
                return _Resp(TEMPLATE_PAYLOAD)
            self.search_calls += 1
            return _Resp({}, status_code=503)

    server = _PageBadStatus()
    monkeypatch.setattr(lp, "client", _fake_client(server))
    rows = asyncio.run(lp.NCECourtsLisPendens().fetch())
    assert server.search_calls == 1   # a real bad status is not a transport/timeout error
    assert rows == []
