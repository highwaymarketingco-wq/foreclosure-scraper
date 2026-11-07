"""counties_nc.johnston_delinquent_tax_crosswalk: a transient transport error on either of its
two genuinely unprotected network call sites gets retried, not treated as "the whole scrape
failed."

Confirmed 2026-11-07 (bug-shape audit, following the pattern already fixed tonight in a Column
legal-notice API scraper, spartan_weekly_legals.py, and arcgis_webmap.query_features()):
`_file_url()` (the Files-for-Download page fetch, line ~379) and `fetch()`'s own CSV download
(line ~437) were both bare `http.get()` calls with zero retry cushioning. Both are true single
points of failure, not per-item: they run before `self.partial` has anything in it (this is the
FIRST and SECOND network action `fetch()` takes), so a transient blip on either one previously
zeroed the whole run's output -- caught only by an outer `try/except Exception` that logs and
bails with an empty result. `_crosswalk_one()`'s own existing manual 2-attempt retry loop (built
to compensate for `enrichment_owner_mailing._query`'s own exception-swallowing) is untouched by
this fix and is NOT exercised here.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import johnston_delinquent_tax_crosswalk as m

_FILE_LABEL = "DelinquentTaxPublicRecordsFile2026108.txt"
_FILE_URL = f"https://www.johnstonnc.gov/files/taxoffice/{_FILE_LABEL}"
_FILES_PAGE_HTML = f'<html><body><a href="{_FILE_URL}">Delinquent Taxes</a></body></html>'


def _dummy_request() -> httpx.Request:
    return httpx.Request("GET", "https://www.johnstonnc.gov/x")


class _FakeResp:
    def __init__(self, text: str = "", status_code: int = 200, content: bytes = b""):
        self.text = text
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            req = _dummy_request()
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=req,
                response=httpx.Response(self.status_code, request=req),
            )


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Same trick the reference test (test_arcgis_webmap_query_features_retry.py) uses: the
    module calls the bare name `wait_exponential_jitter(...)` at call time, so patching the
    module-level import makes every subsequent AsyncRetrying backoff effectively instant."""
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# --------------------------------------------------------------------- _file_url (Site A, L.379)

class _FlakyFilesPageHttp:
    """Raises on the first `fail_times` .get() calls, then serves a real Files-for-Download page."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, headers=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(text=_FILES_PAGE_HTML)


def test_file_url_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyFilesPageHttp(fail_times=2)
    scraper = m.JohnstonDelinquentTaxCrosswalk()
    url, label = asyncio.run(scraper._file_url(http))
    assert http.calls == 3
    assert url == _FILE_URL
    assert label == _FILE_LABEL


def test_file_url_read_timeout_is_also_retried():
    http = _FlakyFilesPageHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    scraper = m.JohnstonDelinquentTaxCrosswalk()
    url, _label = asyncio.run(scraper._file_url(http))
    assert http.calls == 2
    assert url == _FILE_URL


def test_file_url_timeout_that_never_clears_still_raises_not_hangs():
    http = _FlakyFilesPageHttp(fail_times=99)
    scraper = m.JohnstonDelinquentTaxCrosswalk()
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(scraper._file_url(http))
    assert http.calls == 3  # stop_after_attempt(3), then gives up


def test_file_url_real_http_error_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, headers=None, timeout=None):
            self.calls += 1
            return _FakeResp(status_code=503)

    http = _BadStatusHttp()
    scraper = m.JohnstonDelinquentTaxCrosswalk()
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(scraper._file_url(http))
    assert http.calls == 1  # a real bad status is not a transport/timeout error


# ------------------------------------------------------- fetch()'s CSV download (Site B, L.437)

def _empty_utf16_csv() -> bytes:
    header = ("Taxyear,ParcelNumber,LastName,FirstName,PropertyAddress,ZipCode,TotalDue,"
             "Bill,LandUnits,Type")
    return (header + "\r\n").encode("utf-16")


class _RoutingHttp:
    """The Files-for-Download page GET (Site A) always succeeds immediately so a `fetch()` run
    reaches the CSV download (Site B). Every GET for the CSV url is flaky per `fail_times`/`exc`,
    or returns a fixed bad status when `csv_status` is set -- exactly the shapes under test."""

    def __init__(self, fail_times: int = 0, exc=None, csv_status: int | None = None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.csv_status = csv_status
        self.csv_calls = 0

    async def get(self, url, headers=None, timeout=None):
        if url == m.FILES_PAGE_URL:
            return _FakeResp(text=_FILES_PAGE_HTML)
        assert url == _FILE_URL
        self.csv_calls += 1
        if self.csv_status is not None:
            return _FakeResp(status_code=self.csv_status)
        if self.csv_calls <= self.fail_times:
            raise self.exc
        return _FakeResp(content=_empty_utf16_csv())


class _FakeClientCtx:
    """Fakes the `async with client(timeout=...) as http:` context manager `fetch()` opens."""

    def __init__(self, routing_http: _RoutingHttp):
        self._http = routing_http

    async def __aenter__(self):
        return self._http

    async def __aexit__(self, *exc_info):
        return False


@pytest.fixture(autouse=True)
def _enable_scraper(monkeypatch):
    monkeypatch.delenv("FORECLOSURE_JOHNSTON_TAX_CROSSWALK", raising=False)


def test_csv_download_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    http = _RoutingHttp(fail_times=2)
    monkeypatch.setattr(m, "client", lambda *a, **kw: _FakeClientCtx(http))
    scraper = m.JohnstonDelinquentTaxCrosswalk()
    rows = asyncio.run(scraper.fetch())
    assert list(rows) == []  # empty CSV body -> zero listings, but a CLEAN run, not a bail-out
    assert http.csv_calls == 3


def test_csv_download_read_timeout_is_also_retried(monkeypatch):
    http = _RoutingHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    monkeypatch.setattr(m, "client", lambda *a, **kw: _FakeClientCtx(http))
    scraper = m.JohnstonDelinquentTaxCrosswalk()
    rows = asyncio.run(scraper.fetch())
    assert list(rows) == []
    assert http.csv_calls == 2


def test_csv_download_timeout_that_never_clears_still_bails_cleanly_not_hangs(monkeypatch):
    """The retry budget is bounded: an unrecovered transient error still surfaces as a clean,
    immediate empty-partial return (fetch()'s own outer try/except), never a hang."""
    http = _RoutingHttp(fail_times=99)
    monkeypatch.setattr(m, "client", lambda *a, **kw: _FakeClientCtx(http))
    scraper = m.JohnstonDelinquentTaxCrosswalk()
    rows = asyncio.run(scraper.fetch())
    assert list(rows) == []
    assert http.csv_calls == 3  # stop_after_attempt(3), then gives up (caught by outer except)


def test_csv_download_real_http_error_status_is_not_retried(monkeypatch):
    http = _RoutingHttp(csv_status=503)
    monkeypatch.setattr(m, "client", lambda *a, **kw: _FakeClientCtx(http))
    scraper = m.JohnstonDelinquentTaxCrosswalk()
    rows = asyncio.run(scraper.fetch())
    assert list(rows) == []
    assert http.csv_calls == 1  # a real bad status is not a transport/timeout error
