"""bankruptcy_rss_relief_from_stay.fetch(): a transient transport error on one court's
RSS GET gets retried, not treated as "that feed is gone for the day."

Found 2026-10-17 (gap-sweep continuation): the loop over the 3 CM/ECF feeds
(SC/MDNC/WDNC) wrapped `r = await http.get(url)` only in a bare
`try/except Exception: log.warning(...); continue` -- the same http_client-raw-call
gap already fixed tonight for the Column legal-notice API scraper,
spartan_weekly_legals.py and arcgis_webmap.query_features(). This source is a rolling
window with no fallback date window (module docstring; it is in
main.DATELESS_OK_SOURCES), so a single transient blip on one court's GET permanently
drops that court's relief-from-stay cases for the run -- not recoverable later, and not
visible as a failure (the scraper still returns a "healthy" result from the other two
feeds).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import bankruptcy_rss_relief_from_stay as mod

RSS_ONE_RFS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Recent Entries</title>
<item><title>26-01234-eg Pat Q. Sample </title>
<link>https://ecf.scb.uscourts.gov/cgi-bin/DktRpt.pl?100001</link>
<description>Type: bk Office: 2 Chapter: 13 Trustee: Example, Lee [Relief from Stay] ( 14 )</description>
<guid isPermaLink="true">https://ecf.scb.uscourts.gov/cgi-bin/DktRpt.pl?100001-9</guid>
<pubDate>Wed, 07 Oct 2026 15:00:00 GMT</pubDate></item>
</channel></rss>"""

ONE_FEED = (("scb", "SC", "District of South Carolina",
             "https://ecf.scb.uscourts.gov/cgi-bin/rss_outside.pl"),)


class _Resp:
    def __init__(self, text, status_code=200):
        self.text, self.status_code = text, status_code


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


class _FlakyHttp:
    """Raises on the first N-1 calls, then serves a real (terminal) RSS page."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, **kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _Resp(RSS_ONE_RFS)


class _AlwaysFailsHttp:
    def __init__(self, exc=None):
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, **kw):
        self.calls += 1
        raise self.exc


class _BadStatusHttp:
    def __init__(self, status_code=503):
        self.status_code = status_code
        self.calls = 0

    async def get(self, url, **kw):
        self.calls += 1
        return _Resp("", self.status_code)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


@pytest.fixture(autouse=True)
def _rss_rfs_enabled(monkeypatch):
    monkeypatch.delenv(mod.ENV_OFF, raising=False)


def _run_fetch(monkeypatch, http, feeds=ONE_FEED, timeout=5.0):
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    monkeypatch.setattr(mod, "FEEDS", feeds)
    return asyncio.run(asyncio.wait_for(mod.BankruptcyRssReliefFromStay().fetch(), timeout=timeout))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    http = _FlakyHttp(fail_times=2)
    rows = _run_fetch(monkeypatch, http)
    assert http.calls == 3
    assert [li.case_number for li in rows] == ["26-01234-eg"]


def test_a_read_timeout_is_also_retried(monkeypatch):
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    rows = _run_fetch(monkeypatch, http)
    assert http.calls == 2
    assert [li.case_number for li in rows] == ["26-01234-eg"]


def test_a_connect_timeout_that_never_clears_gives_up_after_3_not_an_infinite_hang(monkeypatch):
    http = _AlwaysFailsHttp()
    # fetch()'s own try/except Exception: continue absorbs the reraised exhausted-retry
    # error (by design -- one bad feed must not kill the other two courts' results), so
    # the budget being respected shows up as exactly 3 calls and an empty, non-hanging
    # result, not as fetch() itself raising.
    rows = _run_fetch(monkeypatch, http)
    assert http.calls == 3  # stop_after_attempt(3), then gives up -- never an infinite retry
    assert rows == []


def test_a_real_http_error_status_is_not_retried(monkeypatch):
    http = _BadStatusHttp(503)
    rows = _run_fetch(monkeypatch, http)
    assert http.calls == 1  # a real bad status is not a transport/timeout error
    assert rows == []


def test_a_non_rss_200_body_is_not_retried(monkeypatch):
    class _MaintenanceHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, **kw):
            self.calls += 1
            return _Resp("<html>maintenance</html>", 200)

    maint = _MaintenanceHttp()
    rows = _run_fetch(monkeypatch, maint)
    assert maint.calls == 1  # HTTP-200-but-not-RSS is a real body, not a transport failure
    assert rows == []


def test_the_other_two_feeds_still_populate_when_one_feed_exhausts_its_retries(monkeypatch):
    class _MixedHttp:
        def __init__(self):
            self.calls = []

        async def get(self, url, **kw):
            self.calls.append(url)
            if "ecf.scb" in url:
                raise httpx.ConnectTimeout("boom")
            if "ecf.ncmb" in url:
                return _Resp(RSS_ONE_RFS)
            return _Resp('<?xml version="1.0"?><rss><channel></channel></rss>')

    http = _MixedHttp()
    feeds = (
        ("scb", "SC", "District of South Carolina", "https://ecf.scb.uscourts.gov/cgi-bin/rss_outside.pl"),
        ("ncmb", "NC", "Middle District of North Carolina", "https://ecf.ncmb.uscourts.gov/cgi-bin/rss_outside.pl"),
        ("ncwb", "NC", "Western District of North Carolina", "https://ecf.ncwb.uscourts.gov/cgi-bin/rss_outside.pl"),
    )
    rows = _run_fetch(monkeypatch, http, feeds=feeds)
    # scb: 3 failed attempts then gave up; ncmb: 1 call, succeeds; ncwb: 1 call, succeeds.
    assert len(http.calls) == 5
    assert [li.case_number for li in rows] == ["26-01234-eg"]
