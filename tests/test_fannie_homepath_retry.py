"""national.fannie_homepath: a transient transport/timeout error on the
per-listing detail-gallery fetch gets retried, not treated as "this listing
never gets its gallery/agent enrichment."

Found 2026-10-17 (gap-sweep investigation of this file): two network call
sites exist in this module. `_fetch_bbox` (the search-phase bbox fetch) was
already wrapped in a manual 3-attempt retry loop with a fixed delay -- a
real, functioning retry mechanism, so it is NOT touched here. `_enrich_
galleries`'s per-listing detail fetch (line ~200) had zero retry cushioning
-- a bare `try/except Exception: ... continue` inside the `for n, li in
enumerate(listings)` loop -- the same gap already fixed tonight for the
Column legal-notice API scraper, spartan_weekly_legals.py, and
arcgis_webmap.query_features(). Its blast radius is low (a failed fetch here
only costs one listing's full photo gallery/agent-contact bonus, never the
row itself, since _enrich_galleries runs strictly after every row is already
in self.partial) but it is still a genuinely unretried network call worth
the same AsyncRetrying cushioning.
"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.models import Listing
from foreclosure_scraper.scrapers.national import fannie_homepath as m


def _listing(uuid: str) -> Listing:
    return Listing(
        source="national.fannie_homepath",
        source_url=f"https://homepath.fanniemae.com/property/{uuid}",
        raw={"fannie_homepath": {"property_uuid": uuid}},
    )


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FlakyHttp:
    """Raises on the first N-1 calls for a given uuid, then serves a real
    (terminal) detail response with one gallery photo."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, headers=None, follow_redirects=True):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp({
            "propertyPics": [{"imageUrl": "https://img.example.test/a.jpg"}],
            "brokerCompanies": [],
        })


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2)
    listings = [_listing("uuid-1")]
    asyncio.run(m._enrich_galleries(http, listings, time.monotonic() + 30))
    assert http.calls == 3
    assert listings[0].raw["images"]["real"] == ["https://img.example.test/a.jpg"]


def test_a_connect_timeout_that_never_clears_still_continues_not_hangs():
    """The per-listing loop must not hang or propagate -- a listing whose
    retry budget is exhausted simply keeps its single teaser photo and the
    loop moves on to the next listing."""
    http = _FlakyHttp(fail_times=99)
    listings = [_listing("uuid-1"), _listing("uuid-2")]
    asyncio.run(m._enrich_galleries(http, listings, time.monotonic() + 30))
    assert http.calls == 6   # stop_after_attempt(3) per listing, x2 listings, then gives up each time
    # neither listing got its gallery -- both keep whatever they already had (none, here)
    assert listings[0].raw.get("images", {}).get("real", []) == []
    assert listings[1].raw.get("images", {}).get("real", []) == []


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    listings = [_listing("uuid-1")]
    asyncio.run(m._enrich_galleries(http, listings, time.monotonic() + 30))
    assert http.calls == 2
    assert listings[0].raw["images"]["real"] == ["https://img.example.test/a.jpg"]


def test_a_real_bad_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, headers=None, follow_redirects=True):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    http = _BadStatusHttp()
    listings = [_listing("uuid-1")]
    asyncio.run(m._enrich_galleries(http, listings, time.monotonic() + 30))
    assert http.calls == 1   # a real bad status is not a transport/timeout error -- not retried
    assert listings[0].raw.get("images", {}).get("real", []) == []
