"""spartan_weekly_legals._row_to_listing: the per-row detail-page fetch (enrich=True)
gets the same transport/timeout retry cushioning as the page-list fetch, not zero
retry protection with a bare try/except as its only net.

Found 2026-11-07 (gap-sweep): fetch()'s step-2 enrichment loop calls
`_row_to_listing(row, c, enrich=True)` once per row (fetch() lines ~411-436). Call
site 1 of this module -- the paginated list fetch inside fetch() itself -- already
got the AsyncRetrying treatment on 2026-10-16 (see test_spartan_weekly_page_retry.py).
Call site 2 -- `d = await c.get(source_url)` inside `_row_to_listing`, under
`if enrich:` -- had none: only a bare `try/except Exception: log.debug(...)` wrapping
the whole enrichment block, with a single attempt and no retry. A transient
transport blip on one row's detail page silently lost that row's enrichment
(defendant/sale-date/amount/probate fields), falling back to whatever the
network-free base pass had already banked -- the same root-cause shape already
fixed tonight for the Column legal-notice API scrapers, this module's own
page-list fetch, and arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import spartan_weekly_legals as M

ROW = {
    "type": "Master In Equity",
    "href": "/legal-notices/12-test-placeholder-rd",
    "addr": "12 Test Placeholder Rd",
    "meta": " Case #:2026CP4200001<br> October 1, 2026 ",
}

# A real foreclosure-caption body: "vs. NAME; et.al., Master in Equity..." is the
# exact closer shape test_spartan_weekly_legals.py's own
# test_defendant_stops_before_etal_on_semicolon_list already proves _VS_RE matches
# cleanly, so a successful detail fetch is provably PARSED (defendant extracted),
# not just "didn't raise".
BODY = (
    "STATE OF SOUTH CAROLINA COUNTY OF SPARTANBURG IN THE COURT OF COMMON "
    "PLEAS C/A No.: 2026-CP-42-00001 in the case of Acme Bank vs. Jane Q. "
    "Testwell; et.al., Master in Equity for Spartanburg County."
)


class _FakeResp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class _FlakyHttp:
    """Raises on the first N-1 .get() calls, then serves a real 200 detail page."""

    def __init__(self, fail_times: int, exc: Exception | None = None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, **kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(BODY)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(M, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_on_the_detail_fetch_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2)
    scraper = M.SpartanWeeklyLegals()
    result = asyncio.run(scraper._row_to_listing(dict(ROW), http, enrich=True))
    assert http.calls == 3
    assert result is not None and result is not M._JUNK
    # Proves the retried fetch's body was actually fetched and parsed, not
    # just that the call didn't raise.
    assert result.defendant == "Jane Q. Testwell"


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    scraper = M.SpartanWeeklyLegals()
    result = asyncio.run(scraper._row_to_listing(dict(ROW), http, enrich=True))
    assert http.calls == 2
    assert result.defendant == "Jane Q. Testwell"


def test_a_connect_timeout_that_never_clears_still_gives_up_not_hangs():
    http = _FlakyHttp(fail_times=99)
    scraper = M.SpartanWeeklyLegals()
    result = asyncio.run(scraper._row_to_listing(dict(ROW), http, enrich=True))
    assert http.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite retry loop
    # The row's own bare except (unrelated to this fix, pre-existing) swallows
    # the exhausted retry and keeps the pre-enrichment fallback -- same
    # non-fatal-per-row contract as every other enrichment failure in this
    # scraper (see the module's own fetch() docstring comment).
    assert result is not None and result is not M._JUNK
    assert result.defendant is None


def test_a_real_non_transport_error_on_the_detail_fetch_is_not_retried():
    class _BadHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, **kw):
            self.calls += 1
            req = httpx.Request("GET", url)
            raise httpx.HTTPStatusError(
                "500 error", request=req, response=httpx.Response(500, request=req)
            )

    http = _BadHttp()
    scraper = M.SpartanWeeklyLegals()
    result = asyncio.run(scraper._row_to_listing(dict(ROW), http, enrich=True))
    assert http.calls == 1   # a real HTTP error is not a transport/timeout blip
    assert result is not None and result is not M._JUNK
    assert result.defendant is None   # enrichment never ran; base listing kept
