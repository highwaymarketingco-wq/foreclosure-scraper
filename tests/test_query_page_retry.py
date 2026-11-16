"""enrichment_owner_mailing._query_page: a transient transport/timeout error on
the ACTUAL feature query gets retried, not silently treated as "zero matching
parcels."

Found 2026-11-16 while auditing gap_matrix's NC heir_estate "sourced-not-built"
flags for Columbus/Alexander (see nc_heir_estate_parcels.py's own 2026-11-16
docstring note). This is exactly the fix test_nc_heir_estate_parcels_retry.py's
own "NOTE on scope" already called out and deliberately deferred: "`_query_page`
already catch[es] every exception internally (`except Exception: return [],
False`)... A real fix for that risk belongs inside enrichment_owner_mailing.py's
`_query_page` itself, which is a shared helper used by many other files." This
is that fix, landed where that note said it belonged.

Live-confirmed the bug before fixing it: the IDENTICAL unmodified call against
NC OneMap for Columbus returned 0 rows on one run and 400 real rows (including
a genuine decedent parcel) on an immediate re-run minutes later, no code change
in between -- a transient httpx timeout on the /query GET, not a real zero.

Hermetic -- no network; monkeypatches the backoff wait to keep the test fast,
exactly like test_nc_heir_estate_parcels_retry.py / test_arcgis_webmap_query_
features_retry.py.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper import enrichment_owner_mailing as m

URL = "https://gis.example.test/arcgis/rest/services/Parcels/FeatureServer/0"

_FEATURES_OK = {"features": [{"attributes": {"ownname": "SAMPLE HEIRS", "parno": "123"}}]}


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FlakyHttp:
    """Raises on the first N calls, then serves a real (terminal) /query response."""

    def __init__(self, fail_times: int, exc=None, payload=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.payload = payload if payload is not None else _FEATURES_OK
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _Resp(self.payload)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# --------------------------------------------------------------------------- (a)

def test_a_transient_connect_timeout_is_retried_and_then_returns_real_rows():
    http = _FlakyHttp(fail_times=2)
    rows, exceeded = asyncio.run(m._query_page(http, URL, "1=1"))
    assert http.calls == 3
    assert rows == [{"ownname": "SAMPLE HEIRS", "parno": "123"}]
    assert exceeded is False


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    rows, _ = asyncio.run(m._query_page(http, URL, "1=1"))
    assert http.calls == 2
    assert rows == [{"ownname": "SAMPLE HEIRS", "parno": "123"}]


def test_plain_query_helper_also_benefits_via_query_page():
    """_query() is a thin wrapper over _query_page() -- confirm the retry is
    visible through that entry point too, since most callers use _query()."""
    http = _FlakyHttp(fail_times=2)
    rows = asyncio.run(m._query(http, URL, "1=1"))
    assert http.calls == 3
    assert rows == [{"ownname": "SAMPLE HEIRS", "parno": "123"}]


# --------------------------------------------------------------------------- (b)

def test_a_connect_timeout_that_never_clears_still_stops_at_3_and_returns_empty():
    """stop_after_attempt(3) gives up; the exhausted AsyncRetrying's final
    exception is still caught by _query_page's own outer `except Exception:
    return [], False` -- the documented graceful-degradation contract (a
    county that never answers is still just an empty read, not a crashed run)
    is preserved. It just now retries first instead of giving up on the very
    first transient blip, which is the entire point of this fix."""
    http = _FlakyHttp(fail_times=99)
    rows, exceeded = asyncio.run(m._query_page(http, URL, "1=1"))
    assert http.calls == 3   # stop_after_attempt(3), then gives up -- not unbounded
    assert rows == []
    assert exceeded is False


# --------------------------------------------------------------------------- (c)

def test_a_genuine_zero_match_response_is_not_retried_and_costs_nothing_extra():
    """A real, terminal "no features" response (not an exception) must NOT be
    retried -- retrying a genuine zero-match county would waste the backoff
    budget on something that will never change. This is the behaviour the
    fix's own docstring promises: "never just because a query came back
    empty"."""
    http = _FlakyHttp(fail_times=0, payload={"features": []})
    rows, _ = asyncio.run(m._query_page(http, URL, "1=1"))
    assert http.calls == 1
    assert rows == []


def test_a_real_non_transport_error_is_not_retried():
    """A bug/parse error that is NOT a transport/timeout issue must fail fast
    (1 call) -- retrying it would never help, and _query_page's contract is to
    degrade to an empty read, not raise, so the caller is unaffected either way."""

    class _BuggyHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            raise ValueError("not a transport error")

    http = _BuggyHttp()
    rows, exceeded = asyncio.run(m._query_page(http, URL, "1=1"))
    assert http.calls == 1
    assert rows == []
    assert exceeded is False
