"""counties_sc.greenville_probate: a transient transport error on either of this
scraper's two real network calls gets retried, not treated as "that surname/case
permanently lost."

Found 2026-11-07 (gap-sweep, same pattern already fixed tonight elsewhere in this
repo: a Column legal-notice API scraper, spartan_weekly_legals.py, and the shared
arcgis_webmap.query_features()). ``_search_surname()`` and ``_fetch_detail()`` each
make a single bare ``httpx.AsyncClient.get()`` call with zero retry cushioning --
no tenacity import, no manual backoff loop, no transport-level ``retries=`` on the
client. ``fetch()`` wraps each call in ``try/except httpx.HTTPError: ... continue``,
but ``httpx.TimeoutException``/``httpx.TransportError`` are BOTH subclasses of
``httpx.HTTPError``, so that existing handler was catching a transient connection
reset or timeout the same way it catches a genuine bad status -- log a warning and
drop that one surname's (or case's) contribution, never retrying. Lower severity
than a true single-point-of-failure (SURNAMES is a 10-item tuple and each surname
and each sampled case is independent -- one failure only drops that one item), but
the same unprotected-call bug shape, worth the same fix.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import greenville_probate as mod

_REQ = httpx.Request("GET", "https://www.greenvillecounty.org/appsas400/Probate/SearchResults.aspx")

# A results page with no case-number links -- a real, parseable, terminal response
# (same shape as this module's own test_parse_results_empty_when_no_case_links).
_EMPTY_RESULTS_HTML = "<table class='JobsTable'><tr><td>0 Matches Found</td></tr></table>"

# A detail page with no altDetailsTable at all -- _parse_detail() handles this fine
# (data_tables == [], decedent == {}, parties == []); it is a real, terminal response.
_EMPTY_DETAIL_HTML = ""


class _FlakyClient:
    """Raises on the first ``fail_times`` ``.get()`` calls, then serves a real
    (200, parseable) response."""

    def __init__(self, fail_times: int, exc: Exception | None = None, ok_text: str = ""):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.ok_text = ok_text
        self.calls = 0

    async def get(self, url, params=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return httpx.Response(200, request=_REQ, text=self.ok_text)


class _BadStatusClient:
    """Always returns a real, well-formed HTTP error response -- never raises a
    transport/timeout exception at all."""

    def __init__(self, status_code: int = 503):
        self.status_code = status_code
        self.calls = 0

    async def get(self, url, params=None):
        self.calls += 1
        return httpx.Response(self.status_code, request=_REQ, text="")


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# --- _search_surname --------------------------------------------------------------

def test_search_surname_transient_timeout_is_retried_and_then_succeeds():
    client = _FlakyClient(fail_times=2, exc=httpx.ConnectTimeout("boom"),
                          ok_text=_EMPTY_RESULTS_HTML)
    rows = asyncio.run(mod._search_surname(client, "Smith"))
    assert client.calls == 3
    assert rows == []


def test_search_surname_transient_timeout_that_never_clears_still_raises_not_hangs():
    client = _FlakyClient(fail_times=99, exc=httpx.ConnectTimeout("boom"))
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(mod._search_surname(client, "Smith"))
    assert client.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite hang


def test_search_surname_real_http_error_status_is_not_retried():
    client = _BadStatusClient(status_code=503)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(mod._search_surname(client, "Smith"))
    assert client.calls == 1   # a real bad status is not a transport/timeout error


# --- _fetch_detail -----------------------------------------------------------------

def test_fetch_detail_transient_read_timeout_is_retried_and_then_succeeds():
    client = _FlakyClient(fail_times=2, exc=httpx.ReadTimeout("slow"),
                          ok_text=_EMPTY_DETAIL_HTML)
    detail = asyncio.run(mod._fetch_detail(client, "APT29F27"))
    assert client.calls == 3
    assert detail == {"parties": []}


def test_fetch_detail_transient_timeout_that_never_clears_still_raises_not_hangs():
    client = _FlakyClient(fail_times=99, exc=httpx.ReadTimeout("slow"))
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(mod._fetch_detail(client, "APT29F27"))
    assert client.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite hang


def test_fetch_detail_real_http_error_status_is_not_retried():
    client = _BadStatusClient(status_code=500)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(mod._fetch_detail(client, "APT29F27"))
    assert client.calls == 1   # a real bad status is not a transport/timeout error
