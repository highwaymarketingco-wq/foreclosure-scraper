"""rowan_delinquent_tax.RowanDelinquentTax.fetch: a transient transport error on the
Delinquent-Taxpayer-Lists page fetch OR the discovered .xlsx download gets retried,
not treated as "the whole scrape failed."

Found 2026-11-07 (gap-sweep): fetch() makes exactly TWO network calls, both through the
bare http_client.client() context manager (`async with client(timeout=90.0) as c:`) --
`r = await c.get(PAGE)` (finds the newest "Download <year> List (XLS)" link) and
`x = await c.get(url, timeout=120.0)` (downloads the XLSX itself) -- and neither had any
retry cushioning, the same root-cause shape already fixed this week for the Column
legal-notice API scraper, spartan_weekly_legals.py, and the shared
arcgis_webmap.query_features(). http_client.client()'s own docstring says its transport
is built with retries=0 because "callers already wrap their own AsyncRetrying"; this file
never did. The two calls are sequential and both required (the second URL is parsed out of
the first response's HTML), so a single transient connection reset/timeout on EITHER call
used to raise before a single one of the year's ~2,699 REAL rows was ever parsed, zeroing
this source's entire output for the run. Since this slug is in main.DATELESS_OK_SOURCES (no
fallback date window), a zeroed run couldn't self-heal later -- it just silently reported an
empty/healthy result.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import rowan_delinquent_tax as mod
from tests._xlsx_fixture import build_xlsx

PAGE_HTML = (
    '<html><body><ul>'
    '<li><a href="/DocumentCenter/View/55199?bidId=">Download 2024 List (XLS)</a></li>'
    '<li><a href="/DocumentCenter/View/55256?bidId=">Download 2025 List (XLS)</a></li>'
    '</ul></body></html>'
)
DOWNLOAD_FRAG = "/DocumentCenter/View/55256"
DOWNLOAD_URL = mod.BASE + DOWNLOAD_FRAG

# One REAL, late (tax_year 2025 is late since 2026-01-06) row -- enough for to_listing()
# to accept it and emit exactly one Listing.
_HEADER = {0: "parcel_number", 1: "asset_description", 2: "report_group_description",
           3: "tax_year", 4: "balance_due", 5: "taxpayer_name_1"}
_DATA_ROW = {0: "1234567890", 1: "123 MAIN ST", 2: "REAL",
             3: "2025", 4: "500.00", 5: "JOHN DOE"}
XLSX_BYTES = build_xlsx([_HEADER, _DATA_ROW])


class _Resp:
    def __init__(self, status_code=200, text="", content=b""):
        self.status_code, self.text, self.content = status_code, text, content


class _Ctx:
    """Stands in for `async with client(...) as c:` -- hands back a fake client whose
    .get() is `http.get`, no real httpx.AsyncClient involved."""

    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


class _FlakyHttp:
    """Serves fixed fixture responses by URL fragment, except one fragment (`flaky_frag`)
    raises `exc` for the first `fail_times` calls to it before serving its real fixture
    response -- models a connection that blips and then clears (or never clears, for
    fail_times >= stop_after_attempt's budget)."""

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
    """Same trick as the arcgis_webmap retry test: swap in a near-zero backoff so the
    retried tests don't actually sleep for the real 1-8s exponential jitter."""
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _routes():
    return {
        mod.PAGE: _Resp(text=PAGE_HTML),
        DOWNLOAD_FRAG: _Resp(content=XLSX_BYTES),
    }


def _run(monkeypatch, http):
    monkeypatch.delenv(mod.ENV_OFF, raising=False)  # make sure the scraper isn't gated off
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    return asyncio.run(mod.RowanDelinquentTax().fetch())


def test_a_transient_connect_timeout_on_page_fetch_is_retried_and_then_succeeds(monkeypatch):
    http = _FlakyHttp(_routes(), flaky_frag=mod.PAGE, fail_times=2)
    rows = _run(monkeypatch, http)
    assert http.calls.count(mod.PAGE) == 3  # 2 failures + 1 success, stop_after_attempt(3)
    assert len(rows) == 1
    assert rows[0].raw["rowan_delinquent_tax"]["tax_year"] == "2025"


def test_a_transient_connect_timeout_on_xlsx_download_is_retried_and_then_succeeds(monkeypatch):
    http = _FlakyHttp(_routes(), flaky_frag=DOWNLOAD_FRAG, fail_times=2)
    rows = _run(monkeypatch, http)
    assert http.calls.count(DOWNLOAD_URL) == 3
    assert len(rows) == 1


def test_a_read_timeout_is_also_retried(monkeypatch):
    http = _FlakyHttp(_routes(), flaky_frag=mod.PAGE, fail_times=1, exc=httpx.ReadTimeout("slow"))
    rows = _run(monkeypatch, http)
    assert http.calls.count(mod.PAGE) == 2
    assert len(rows) == 1


def test_a_transient_error_that_never_clears_on_page_fetch_still_raises_not_hangs(monkeypatch):
    # fail_times is far larger than the retry budget: the AsyncRetrying block itself raises
    # once stop_after_attempt(3) is exhausted (reraise=True), and -- unlike the mecklenburg
    # scraper -- fetch() has no surrounding try/except here, so the ConnectTimeout propagates
    # straight out of fetch(). This proves the retry loop is BOUNDED (exactly 3 attempts, no
    # hang) even though the run is (correctly) still lost, same as before this fix for a
    # genuinely dead host.
    http = _FlakyHttp(_routes(), flaky_frag=mod.PAGE, fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        _run(monkeypatch, http)
    assert http.calls.count(mod.PAGE) == 3  # stop_after_attempt(3), then gives up -- not more


def test_a_transient_error_that_never_clears_on_xlsx_download_still_raises_not_hangs(monkeypatch):
    http = _FlakyHttp(_routes(), flaky_frag=DOWNLOAD_FRAG, fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        _run(monkeypatch, http)
    assert http.calls.count(DOWNLOAD_URL) == 3


def test_a_real_bad_http_status_on_page_fetch_is_not_retried(monkeypatch):
    routes = _routes()
    routes[mod.PAGE] = _Resp(status_code=503)
    http = _FlakyHttp(routes)
    with pytest.raises(RuntimeError, match="rowan page HTTP 503"):
        _run(monkeypatch, http)
    assert http.calls.count(mod.PAGE) == 1  # a real bad status is not a transport/timeout error


def test_a_real_bad_http_status_on_xlsx_download_is_not_retried(monkeypatch):
    routes = _routes()
    routes[DOWNLOAD_FRAG] = _Resp(status_code=500)
    http = _FlakyHttp(routes)
    with pytest.raises(RuntimeError, match="rowan xlsx HTTP 500"):
        _run(monkeypatch, http)
    assert http.calls.count(DOWNLOAD_URL) == 1
