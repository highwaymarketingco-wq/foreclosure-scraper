"""counties_nc.nc_heir_estate_parcels._value_field: a transient transport/timeout
error on the layer-schema probe gets retried, not treated as "this layer has no
numeric value column."

Found 2026-10-16/17 (gap-sweep). `_value_field()` makes one direct, unprotected
`http.get()` (the layer-schema GET used to pick a value column to rank by) with
zero retry cushioning -- a bare `try/except Exception: vf = None`. A single
transient blip here permanently disables value-ranking for that layer for the
rest of the run (the caller, `_ranked_rows()`, falls back to the pre-existing
unordered `_query()` read, so no county is ever zeroed by this one -- just
silently worse ordering). Still worth the same AsyncRetrying treatment as every
other bare network call fixed this cycle (arcgis_webmap.query_features,
spartan_weekly_legals.py, the Column legal-notice API scraper).

NOTE on scope: this file's OTHER two call sites flagged by the investigation
(`_ranked_rows()`'s calls to `_query_page`/`_query`, imported from
enrichment_owner_mailing.py) are deliberately NOT wrapped here. Both helpers
already catch every exception internally (`except Exception: return [], False`
in `_query_page`, enrichment_owner_mailing.py ~line 383) and always return
normally -- a transport/timeout error raised by the `http.get()` inside them
NEVER propagates out to a caller in this file. An AsyncRetrying wrapper placed
around `_query_page(...)`/`_query(...)` here would therefore never observe an
exception to retry on: it would be inert, no-op code that cannot be proven to
do anything (which is also why no such test is attempted below -- there is no
way to make `_query_page`'s swallow surface a retriable exception to a wrapper
living outside it). A real fix for that risk belongs inside
enrichment_owner_mailing.py's `_query_page` itself, which is a shared helper
used by many other files and out of scope for this change.

Hermetic -- no network; monkeypatches the backoff wait to keep the test fast,
exactly like test_arcgis_webmap_query_features_retry.py.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import nc_heir_estate_parcels as m

URL = "https://gis.example.test/arcgis/rest/services/Parcels/FeatureServer/0"


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


_SCHEMA_OK = {"fields": [{"name": "parval", "type": "esriFieldTypeDouble"}]}


class _FlakyHttp:
    """Raises on the first N calls, then serves a real (terminal) schema response."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _Resp(_SCHEMA_OK)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _scraper():
    return m.NCHeirEstateParcels()


# --------------------------------------------------------------------------- (a)

def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2)
    vf = asyncio.run(_scraper()._value_field(http, URL))
    assert http.calls == 3
    assert vf == "parval"


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    vf = asyncio.run(_scraper()._value_field(http, URL))
    assert http.calls == 2
    assert vf == "parval"


# --------------------------------------------------------------------------- (b)

def test_a_connect_timeout_that_never_clears_still_stops_at_3_not_an_infinite_hang():
    """stop_after_attempt(3) gives up; the exhausted AsyncRetrying's final exception
    is still caught by _value_field's own outer `except Exception: vf = None` --
    its documented graceful-degradation contract ("unranked is the old behaviour,
    not a failure") is preserved, it just now retries first instead of giving up
    on the very first transient blip."""
    http = _FlakyHttp(fail_times=99)
    vf = asyncio.run(_scraper()._value_field(http, URL))
    assert http.calls == 3   # stop_after_attempt(3), then gives up -- not unbounded
    assert vf is None        # falls back to unranked, exactly as before this fix


# --------------------------------------------------------------------------- (c)

def test_a_real_non_transport_error_is_not_retried():
    """A bug/parse error that is NOT a transport/timeout issue must fail on
    attempt 1 -- retrying it would just waste the backoff budget on something
    that will never clear on its own."""

    class _BuggyHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            raise ValueError("not a transport error")

    http = _BuggyHttp()
    vf = asyncio.run(_scraper()._value_field(http, URL))
    assert http.calls == 1   # unretried
    assert vf is None        # same graceful fallback as any other failure


def test_a_real_bad_http_status_is_not_an_exception_and_is_not_retried():
    """A real bad status (no exception raised at all, since this call never
    calls raise_for_status) must not trigger any retry loop either -- it is
    handled the same way it always was, in a single call."""

    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _Resp({}, status_code=503)

    http = _BadStatusHttp()
    vf = asyncio.run(_scraper()._value_field(http, URL))
    assert http.calls == 1
    assert vf is None


# --------------------------------------------------------------------------- caching

def test_the_schema_get_is_still_cached_per_layer_url_after_a_successful_retry():
    """`_value_field` caches by url in `self._value_fields` -- a second call for
    the SAME url must not re-hit the network at all, retried or not."""
    http = _FlakyHttp(fail_times=1)
    s = _scraper()
    vf1 = asyncio.run(s._value_field(http, URL))
    calls_after_first = http.calls
    vf2 = asyncio.run(s._value_field(http, URL))
    assert vf1 == vf2 == "parval"
    assert http.calls == calls_after_first   # no new GET on the cached second call
