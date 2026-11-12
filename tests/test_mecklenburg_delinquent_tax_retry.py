"""mecklenburg_delinquent_tax.fetch: a transient transport error on the Widen
share-page fetch or the workbook download fetch gets retried, not treated as
"that list's rows are gone for this run."

Found 2026-10-17 (gap-sweep): both of fetch()'s two real network calls go through
the bare http_client.client() context manager, whose transport is built with
retries=0 -- callers must wrap their own AsyncRetrying (the same root cause
already fixed tonight for the Column legal-notice API scraper,
spartan_weekly_legals.py, and the shared arcgis_webmap.query_features()). LISTS
has only two entries ("individual", "business") and the two calls per kind are
sequential and dependent (the download link only exists after the share page is
fetched), so a single transient blip used to permanently zero roughly a third to
two-thirds of this scraper's total rows for the whole run, with no fallback date
window (main.DATELESS_OK_SOURCES) to self-heal later.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import mecklenburg_delinquent_tax as mod

from tests._xlsx_fixture import build_xlsx

ROWS = [{0: "TESTPERSON, ALEXANDRA Q", 1: "1511 EXAMPLE AV CHARLOTTE NC 28216", 2: "$", 3: "1250.75"}]

SHARE_HTML = (
    '<html><body><a id="download" href="/content/abc123xyz/original/'
    'IND_Taxbills_Advertisement.xlsx?u=zzz111&amp;download=true" '
    'class="toolbarButton download">Download</a></body></html>'
)
BUSINESS_SHARE_HTML = "<html>no business link today</html>"

SHARE_URL = mod.LISTS[0][1]  # individual list's Widen share page
DOWNLOAD_URL = mod.WIDEN_HOST + "/content/abc123xyz/original/IND_Taxbills_Advertisement.xlsx?u=zzz111&download=true"


class _Resp:
    def __init__(self, status_code=200, text="", content=b""):
        self.status_code, self.text, self.content = status_code, text, content


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


class _FlakyHttp:
    """Serves fixed fixture responses by URL fragment, except one fragment
    (`flaky_frag`) raises `exc` for the first `fail_times` calls to it before
    serving its real fixture response -- models a connection that blips and then
    clears (or never clears, for fail_times >= stop_after_attempt's budget)."""

    def __init__(self, routes, flaky_frag=None, fail_times=0, exc=None):
        self.routes = routes
        self.flaky_frag = flaky_frag
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls: list[str] = []
        self._flaky_calls = 0

    async def get(self, url, **kw):
        self.calls.append(url)
        if self.flaky_frag and self.flaky_frag in url:
            self._flaky_calls += 1
            if self._flaky_calls <= self.fail_times:
                raise self.exc
        for frag, resp in self.routes.items():
            if frag in url:
                return resp
        return _Resp(404)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Same trick as the arcgis_webmap retry test: swap in a near-zero backoff so
    the retried tests don't actually sleep for the real 1-8s exponential jitter."""
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _routes():
    return {
        "/s/vb8vhrwvtm/": _Resp(text=SHARE_HTML),
        "/content/abc123xyz/": _Resp(content=build_xlsx(ROWS)),
        "/s/slsnqr9prl/": _Resp(text=BUSINESS_SHARE_HTML),  # business list: no link -> no rows, unrelated
    }


def _run(monkeypatch, http):
    monkeypatch.setenv(mod.ENV_ON, "1")
    monkeypatch.setenv(mod.ENV_RESOLVED_ONLY, "0")  # skip parcel matching, not under test here
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    return asyncio.run(mod.MecklenburgDelinquentTax().fetch())


def test_transient_error_on_share_page_fetch_is_retried_and_then_succeeds(monkeypatch):
    http = _FlakyHttp(_routes(), flaky_frag="/s/vb8vhrwvtm/", fail_times=2)
    rows = _run(monkeypatch, http)
    assert http.calls.count(SHARE_URL) == 3  # 2 failures + 1 success, stop_after_attempt(3)
    assert len(rows) == 1
    assert rows[0].raw["mecklenburg_delinquent_tax"]["list"] == "individual"


def test_transient_error_on_download_fetch_is_retried_and_then_succeeds(monkeypatch):
    http = _FlakyHttp(_routes(), flaky_frag="/content/abc123xyz/", fail_times=2)
    rows = _run(monkeypatch, http)
    assert http.calls.count(DOWNLOAD_URL) == 3
    assert len(rows) == 1


def test_a_read_timeout_is_also_retried(monkeypatch):
    http = _FlakyHttp(_routes(), flaky_frag="/s/vb8vhrwvtm/", fail_times=1, exc=httpx.ReadTimeout("slow"))
    rows = _run(monkeypatch, http)
    assert http.calls.count(SHARE_URL) == 2
    assert len(rows) == 1


def test_transient_error_that_never_clears_still_gives_up_after_the_retry_budget_not_an_infinite_hang(monkeypatch):
    # fail_times is far larger than the retry budget: the AsyncRetrying block itself
    # raises once stop_after_attempt(3) is exhausted (reraise=True); the surrounding
    # try/except Exception then logs a warning and `continue`s past that kind. This
    # proves the retry loop is BOUNDED -- exactly 3 attempts, no hang -- even though
    # the individual list is still (correctly) lost for this run, same as it would be
    # for a genuinely dead host before or after this fix.
    http = _FlakyHttp(_routes(), flaky_frag="/s/vb8vhrwvtm/", fail_times=99)
    rows = _run(monkeypatch, http)
    assert http.calls.count(SHARE_URL) == 3  # stop_after_attempt(3), then gives up -- not more, not fewer
    assert rows == []  # individual list lost to the dead host; business had no download link either


def test_a_real_bad_http_status_on_share_fetch_is_not_retried(monkeypatch):
    routes = _routes()
    routes["/s/vb8vhrwvtm/"] = _Resp(status_code=503)
    http = _FlakyHttp(routes)
    rows = _run(monkeypatch, http)
    assert http.calls.count(SHARE_URL) == 1  # a real bad status is not a transport/timeout error
    assert rows == []


def test_a_real_bad_http_status_on_download_fetch_is_not_retried(monkeypatch):
    routes = _routes()
    routes["/content/abc123xyz/"] = _Resp(status_code=500)
    http = _FlakyHttp(routes)
    rows = _run(monkeypatch, http)
    assert http.calls.count(DOWNLOAD_URL) == 1
    assert rows == []


def test_a_200_with_a_non_xlsx_body_is_not_retried(monkeypatch):
    routes = _routes()
    routes["/content/abc123xyz/"] = _Resp(content=b"<html>error</html>")
    http = _FlakyHttp(routes)
    rows = _run(monkeypatch, http)
    assert http.calls.count(DOWNLOAD_URL) == 1  # the classic 200-with-wrong-body shape, unretried
    assert rows == []
