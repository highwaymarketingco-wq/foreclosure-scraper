"""sc_probate_notices._json: the shared JSON-fetch helper used by ALL THREE network call
sites in this file (_geodir_docs, and _fetch_paper()'s "posts" and "search_html"
search-listing loops) gets retry cushioning on its own network call, not a silent,
permanent drop of that paper's whole scrape result.

NOTE ON FILE NAME: the task's naming convention (test_<module_basename>_retry.py) would
be test_sc_probate_notices_retry.py, but that name is already taken by a PRIOR, unrelated
fix in this same module (the search_html per-article loop, found+fixed 2026-10-17 -- see
test_sc_probate_notices_retry.py). This file is named test_sc_probate_notices_json_retry.py
instead, following the same disambiguation convention already used elsewhere in this test
suite for a module with more than one retry-fix test file (compare
test_horry_probate_retry.py vs. test_horry_probate_detail_page_retry.py): the module
basename stays, and a call-site hint ("_json", naming the helper under test) is inserted
before "_retry".

Found 2026-11-07 (gap-sweep continuation): _json()'s own `r = await c.get(url,
timeout=60.0)` had zero retry wrapper. Its three callers (_geodir_docs line 312,
_fetch_paper's "posts" mode line 356, _fetch_paper's "search_html" mode URL-listing loop
line 376) only catch `except RuntimeError:` -- the RuntimeError _json() itself raises for
a bad status or a non-JSON body -- so a genuine httpx.TransportError/httpx.TimeoutException
raised by c.get() itself was NEVER caught locally: it propagated straight out of
_geodir_docs()/_fetch_paper(), aborting that paper's ENTIRE scrape for the run (losing every
doc already fetched this run, not just the one page that blipped). Pickens is the
NOT-tolerated anchor paper in SCProbateNotices.fetch()'s LayerHarvest guard, so a transient
blip on this call path there turns into a PartialHarvest that zeros Pickens' rows for the
whole run. Since this module is registered in main.DATELESS_OK_SOURCES (no fallback date
window), a zeroed run cannot self-heal later -- it just silently reports an empty/healthy
result. Same root cause, same fix, already applied in this same file to the OTHER bare call
(the search_html per-article fetch, see test_sc_probate_notices_retry.py, fixed 2026-10-17)
and earlier the same night to the Column legal-notice API scrapers, spartan_weekly_legals.py,
and arcgis_webmap.query_features(): http_client.client()'s own docstring says every caller
must wrap its own retries, and _json() never did.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import sc_probate_notices as m

URL = "https://example.test/wp-json/wp/v2/posts?search=notice+to+creditors&page=1"


class _FakeResp:
    def __init__(self, status_code=200, json_payload=None, json_error=False):
        self.status_code = status_code
        self._json_payload = json_payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("not JSON")
        return self._json_payload


class _FlakyClient:
    """Raises on the first N calls, then serves a real (terminal) JSON response."""

    def __init__(self, fail_times: int, exc=None, payload=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.payload = payload if payload is not None else []
        self.calls = 0

    async def get(self, url, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(json_payload=self.payload)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Exactly the reference pattern (test_arcgis_webmap_query_features_retry.py,
    test_sc_probate_notices_retry.py): speed up the exponential-jitter backoff so the
    "exhausts the retry budget" test does not actually wait out real backoff delays."""
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# --- (a) transient transport/timeout error is retried and then succeeds -----------------

def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    c = _FlakyClient(fail_times=2, payload=[{"id": 1}])
    rows = asyncio.run(m._json(c, URL))
    assert c.calls == 3
    assert rows == [{"id": 1}]


def test_a_read_timeout_is_also_retried():
    c = _FlakyClient(fail_times=1, exc=httpx.ReadTimeout("slow"), payload=[])
    rows = asyncio.run(m._json(c, URL))
    assert c.calls == 2
    assert rows == []


def test_a_bare_asyncio_timeouterror_is_also_retried():
    """retry_if_exception_type() in the fix also covers bare TimeoutError (distinct
    from httpx.TimeoutException), matching the already-proven pattern in this file."""
    c = _FlakyClient(fail_times=1, exc=TimeoutError("deadline"), payload=[])
    rows = asyncio.run(m._json(c, URL))
    assert c.calls == 2
    assert rows == []


# --- (b) a transient error that never clears still raises -- not an infinite hang -------

def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    c = _FlakyClient(fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(m._json(c, URL))
    assert c.calls == 3   # stop_after_attempt(3), then gives up -- NOT swallowed as RuntimeError


# --- (c) a real non-transport HTTP error status is NOT retried (fails on attempt 1) ------

def test_a_real_http_error_status_is_not_retried():
    class _BadStatusClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, timeout=None):
            self.calls += 1
            return _FakeResp(status_code=503)

    c = _BadStatusClient()
    with pytest.raises(RuntimeError, match="HTTP 503"):
        asyncio.run(m._json(c, URL))
    assert c.calls == 1   # a real bad status is not a transport/timeout error


def test_a_non_json_body_is_also_not_retried():
    """_json()'s OTHER real failure mode (a 200 with an unparseable body) must likewise
    stay a one-shot RuntimeError, not get treated as transient."""
    class _BadJsonClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, timeout=None):
            self.calls += 1
            return _FakeResp(status_code=200, json_error=True)

    c = _BadJsonClient()
    with pytest.raises(RuntimeError, match="non-JSON"):
        asyncio.run(m._json(c, URL))
    assert c.calls == 1   # a real non-JSON body is not a transport/timeout error


def test_callers_except_runtimeerror_contract_still_holds():
    """_geodir_docs() and _fetch_paper() wrap every _json() call in `except RuntimeError:`
    only. Confirm that contract still catches a real bad status after the retry wrap."""
    class _BadStatusClient:
        async def get(self, url, timeout=None):
            return _FakeResp(status_code=404)

    async def _call():
        try:
            await m._json(_BadStatusClient(), URL)
        except RuntimeError:
            return "caught"
        return "escaped"

    assert asyncio.run(_call()) == "caught"


# --- integration: the actual blast-radius bug, through the anchor paper's real lane -----

PAPER_POSTS = m.Paper("Pickens", "www.yourpickenscounty.com", "posts")

# Mirrors the body shape already proven to parse in test_sc_probate_notices_retry.py's
# NOTICE_BODY, using the exact case number ("2026ES3900446" = Pickens, code 39) this
# module's own docstring gives as its worked example.
POSTS_PAGE = [{
    "link": "https://www.yourpickenscounty.com/notices/estate-1",
    "date": "2026-10-01T00:00:00",
    "content": {"rendered": (
        "<p>NOTICE TO CREDITORS OF ESTATES</p>"
        "<p>Estate: Dana Fowlerton Testcase</p>"
        "<p>Date of Death: 5/30/2026</p>"
        "<p>Case Number: 2026ES3900446</p>"
        "<p>Personal Representative: Jordan Placeholder</p>"
        "<p>115 Sampleriver Dr.</p>"
        "<p>Easley, SC 29640</p>"
    )},
}]


class _FlakyPostsClient:
    """The anchor paper's FIRST JSON listing call blips transiently; every call after
    that (any term, any page) serves cleanly."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        if "page=1" in url:
            return _FakeResp(json_payload=POSTS_PAGE)
        return _FakeResp(json_payload=[])


def test_a_transient_blip_on_the_anchor_papers_first_listing_call_no_longer_zeros_the_paper():
    """BEFORE the fix: this ConnectTimeout escaped _json() uncaught (callers only catch
    RuntimeError), propagated out of _fetch_paper() entirely with no local containment,
    and -- because Pickens is the untolerated anchor in SCProbateNotices.fetch()'s
    LayerHarvest guard -- would have turned into a PartialHarvest that zeroed Pickens'
    rows for the whole run. AFTER the fix: the retry absorbs the blip inside _json()
    and the paper's real rows come back intact."""
    c = _FlakyPostsClient(fail_times=2)
    rows = asyncio.run(m._fetch_paper(c, PAPER_POSTS))
    assert c.calls == 4   # 2 fails + 1 success for term 1's page 1, + 1 success for term 2
    assert len(rows) == 1
    assert rows[0].case_number == "2026ES3900446"
    assert rows[0].county == "Pickens"
