"""courtlistener_bankruptcy._fetch_chapter: a transient transport/timeout error on
the bankruptcy_information lookup gets retried, not treated as "give up on attempt 1."

Found during the 2026-11-07 unprotected-network-call audit of this file:
_fetch_court() (the dominant, paginated /search/ call, up to 200 pages x 4
courts) already wraps its own hand-rolled retry loop with sleep/backoff -- see
the comment at courtlistener_bankruptcy.py's _fetch_court() documenting a prior
live incident (ncwb bailed after page 1 on a bare ReadTimeout, 20 of 767 rows
returned). _fetch_chapter()'s single bankruptcy_information GET had no such
cushioning at all: it sat inside a bare `try: ... except Exception: pass` with
zero retry -- the same root-cause gap already fixed elsewhere tonight in this
repo for the Column legal-notice API scraper, spartan_weekly_legals.py and
arcgis_webmap.query_features(). http_client's client() sets retries=0 on the
transport and documents that every caller must wrap its own AsyncRetrying;
this call site never did.

Severity note: this is a mild, bounded gap, not the severe scrape-zeroing shape
_fetch_court() was already hardened against. _fetch_chapter() is only called
at most MAX_CHAPTER_LOOKUPS (default 50) times per run, out of a ~4,500+
docket corpus, and a failed lookup never drops the Listing row -- it only
leaves `chapter` at the same "?" (or text-mined) fallback value the caller
already had before calling this function. Added for consistency/robustness: a
transient blip now gets retried instead of giving up immediately.

Note on the "never clears" test below: _fetch_chapter() is documented
"best-effort, never raises" -- the retry block sits INSIDE the function's
pre-existing `try: ... except Exception: pass`, which the fix deliberately
preserves (see courtlistener_bankruptcy.py). So once AsyncRetrying's retry
budget (stop_after_attempt(3)) is exhausted, the exception it raises
(reraise=True) is caught by that pre-existing except, not propagated to our
test. What that test proves instead is that the retry mechanism honors the
3-attempt budget (not an infinite retry loop / hang) and that the
PRE-EXISTING text-mined fallback -- not a fetched chapter value -- is what
comes back once it gives up, exactly as the fix was scoped to preserve.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import courtlistener_bankruptcy as cb

BI_URL = "https://www.courtlistener.com/api/rest/v4/bankruptcy-information/999/"
TOKEN = "fake-token"


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FlakyHttp:
    """Raises on the first N-1 calls, then serves a real successful response."""

    def __init__(self, fail_times: int, exc=None, payload=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.payload = payload if payload is not None else {"chapter": "13"}
        self.calls = 0

    async def get(self, url, headers=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self.payload)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(cb, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _docket(**overrides) -> dict:
    d = {
        "bankruptcy_information": BI_URL,
        "cause": "",
        "nature_of_suit": "",
    }
    d.update(overrides)
    return d


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2, payload={"chapter": "13"})
    chapter = asyncio.run(cb._fetch_chapter(http, _docket(), TOKEN))
    assert http.calls == 3
    assert chapter == "13"


def test_a_connect_timeout_that_never_clears_still_exhausts_retries_not_hangs():
    # cause text-mines to "7" -- distinct from the "13"/"11" a successful fetch
    # would hand back below, so this assertion can only pass if the retry
    # truly exhausted (raised internally, reraise=True) and fell through to
    # the PRE-EXISTING text-mined fallback, never a fetched chapter value.
    http = _FlakyHttp(fail_times=99)
    docket = _docket(cause="voluntary chapter 7 petition")
    chapter = asyncio.run(cb._fetch_chapter(http, docket, TOKEN))
    assert http.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite retry/hang
    assert chapter == "7"    # pre-existing text-mined fallback; _fetch_chapter's
                              # documented "best-effort, never raises" contract holds


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"), payload={"chapter": "11"})
    chapter = asyncio.run(cb._fetch_chapter(http, _docket(), TOKEN))
    assert http.calls == 2
    assert chapter == "11"


def test_a_real_http_error_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, headers=None, timeout=None):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    http = _BadStatusHttp()
    docket = _docket(cause="chapter 13 plan")
    chapter = asyncio.run(cb._fetch_chapter(http, docket, TOKEN))
    assert http.calls == 1   # a real bad status is not a transport/timeout error
    assert chapter == "13"   # falls through to the text-mined fallback, unretried


def test_a_200_with_no_chapter_in_the_body_is_not_retried():
    class _EmptyBodyHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, headers=None, timeout=None):
            self.calls += 1
            return _FakeResp({"chapter": None})

    http = _EmptyBodyHttp()
    docket = _docket(cause="chapter 11 reorganization")
    chapter = asyncio.run(cb._fetch_chapter(http, docket, TOKEN))
    assert http.calls == 1   # a real HTTP-200 response is not a transport/timeout error
    assert chapter == "11"   # falls through to the text-mined fallback, unretried
