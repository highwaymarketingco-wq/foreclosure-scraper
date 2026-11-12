"""sc_tax_delinquent._scrape_pdf: a transient transport/timeout error fetching one linked
delinquent-tax PDF gets retried, not treated as "that PDF's rows are gone for good."

Found 2026-10-17 (gap-sweep audit): this call site goes through the shared
http_client.client(), whose transport is deliberately retries=0 -- per its own docstring,
"callers already wrap their own AsyncRetrying." The county landing-page fetch in
_scrape_html() already escalates to get_text_impersonate() (which has its own internal
retry) on any exception, but _scrape_pdf()'s PDF fetch had no such protection: the whole
function body is one ``try/except Exception: return []`` block, so a transient connection
reset or timeout on a single linked PDF was swallowed at debug level with zero retry,
dropping that PDF's rows. Same bug shape already fixed tonight for the Column legal-notice
API scraper, spartan_weekly_legals.py, and arcgis_webmap.query_features().

Note on behavior after the retry budget is exhausted: unlike query_features() (which lets
the final exception propagate to its caller), _scrape_pdf()'s pre-existing outer
try/except Exception is unchanged by this fix and still converts an exhausted-retry
failure into a graceful ``return []`` rather than raising past the function. What this
fix guarantees is that the retries are *bounded* (stop_after_attempt(3), not an infinite
hang) before that pre-existing swallow happens -- test (b) below asserts exactly that:
the client is called exactly 3 times, never more.
"""
from __future__ import annotations

import asyncio

import httpx
import pdfplumber
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import sc_tax_delinquent as mod

URL = "https://example-county.sc.gov/files/delinquent-tax-2026.pdf"


class _FakeResp:
    def __init__(self, status_code=200, content=b""):
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8", "ignore") if isinstance(content, bytes) else content


class _FlakyClient:
    """Raises on the first N calls, then serves a real (terminal) response."""

    def __init__(self, fail_times: int, exc=None, final_status=200, final_content=b""):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0
        self.final_status = final_status
        self.final_content = final_content

    async def get(self, url, follow_redirects=True, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self.final_status, self.final_content)


class _FakePage:
    """A pdfplumber page with no text and no tables -- enough for _scrape_pdf to run
    through to completion without needing a real PDF body."""

    def extract_text(self):
        return ""

    def extract_tables(self):
        return []


class _FakePdf:
    def __init__(self, pages=None):
        self.pages = pages or []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _fake_open(*args, **kwargs):
    return _FakePdf([])


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    # Same technique as the reference arcgis_webmap test: swap in a near-zero backoff
    # so the retry-exhaustion test doesn't actually sleep ~1s/2s/4s.
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


@pytest.fixture(autouse=True)
def _fake_pdfplumber(monkeypatch):
    monkeypatch.setattr(pdfplumber, "open", _fake_open)


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    c = _FlakyClient(fail_times=2)
    result = asyncio.run(mod._scrape_pdf(c, URL, "TestCounty"))
    assert c.calls == 3
    assert result == []


def test_a_read_timeout_is_also_retried():
    c = _FlakyClient(fail_times=1, exc=httpx.ReadTimeout("slow"))
    result = asyncio.run(mod._scrape_pdf(c, URL, "TestCounty"))
    assert c.calls == 2
    assert result == []


def test_a_connect_timeout_that_never_clears_does_not_hang_and_still_gives_up():
    c = _FlakyClient(fail_times=99)
    result = asyncio.run(mod._scrape_pdf(c, URL, "TestCounty"))
    # stop_after_attempt(3): bounded, never an infinite retry loop.
    assert c.calls == 3
    # _scrape_pdf's own pre-existing outer except (unchanged by this fix) converts the
    # exhausted-retry failure into a graceful empty return rather than raising.
    assert result == []


def test_a_real_bad_http_status_is_not_retried():
    c = _FlakyClient(fail_times=0, final_status=503)
    result = asyncio.run(mod._scrape_pdf(c, URL, "TestCounty"))
    # A real status-code response is not a transport/timeout exception, so
    # retry_if_exception_type never triggers a retry for it.
    assert c.calls == 1
    assert result == []
