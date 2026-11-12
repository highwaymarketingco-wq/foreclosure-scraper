"""national.freddie_homesteps._fetch_state: transient transport/timeout errors on either
network call get retried, not treated as "this state/listing has no data."

Found 2026-10-17 (gap-sweep): two unprotected network call sites in _fetch_state(), both
going through the shared http_client.client() helper directly (zero retry wrapper --
client()'s own transport is built with retries=0, because callers are expected to wrap
their own AsyncRetrying). (1) The per-state listing-search page fetch (called once per
state) was guarded only by a bare try/except Exception that returns [] on ANY failure --
a single transient connection reset/timeout used to zero that entire state's scrape
output for the run, and this file is in main.DATELESS_OK_SOURCES (no date-window
fallback, so a zeroed run can't self-heal). (2) The per-listing detail-page fetch inside
the for-loop over parsed rows was guarded the same way, blast radius limited to that one
listing's enrichment (county/photos/lat-lng/agent), though a lost county can still get
that listing dropped downstream (see the module docstring, main._countyless_national()).
Same root cause, same fix, as the Column legal-notice API scrapers, spartan_weekly_legals.py,
arcgis_webmap.query_features(), and horry_probate.py, all fixed the same night.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import freddie_homesteps as M

STATE, URL = M.URLS[0]  # ("NC", "https://www.homesteps.com/listing/search?search=NC")

_CARD = """
<a href="/listingdetails/2005-ada-williams-ln-lenoir-nc-28645">
<div class="property-teaser grid-x grid-padding-x background-white">
  <div class="property-image cell small-12 medium-4">
    <img src="https://rbimages.blob.core.windows.net/rb-images/US/real-estate/mls-homes/single-family-property/for-sale/NC/Lenoir/28645/1774-CAR4425402-20260916-2005-Ada-Williams-Lane-1.jpg" alt="">
  </div>
  <div class="cell small-12 medium-8">
    <div class="property-price weight-medium">$189,900</div>
    <div class="property-details">2 beds, 2 baths, 1,296 sq. ft.</div>
    <div class="property-address">
      2005 Ada Williams Ln,
      Lenoir,
      NC
      28645
    </div>
  </div>
</div>
</a>
"""
# _fetch_state short-circuits any page under 5000 chars (len(r.text) < 5000) as if it
# were empty -- pad the real card out past that floor, same as a real rendered page.
LIST_PAGE_HTML = _CARD + ("<!-- padding -->" * 300)

DETAIL_URL = "https://www.homesteps.com/listingdetails/2005-ada-williams-ln-lenoir-nc-28645"
_DETAIL_BODY = """
<html><body>
<ul class="detail-list">
  <li><span>County:</span><strong>CALDWELL</strong></li>
</ul>
</body></html>
"""
# Same floor as the list page, but at 1000 chars (len(dr.text) < 1000).
DETAIL_PAGE_HTML = _DETAIL_BODY + ("<!-- padding -->" * 60)


def _fake_client(get_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        yield stub
    return _cm


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        M, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


# --- call site 1: the per-state listing-search page fetch (line 345-ish) --------------

def test_list_page_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"list": 0, "detail": 0}

    async def get(url, headers=None, follow_redirects=None):
        if url == URL:
            calls["list"] += 1
            if calls["list"] < 3:
                raise httpx.ConnectTimeout("boom")
            return MagicMock(status_code=200, text=LIST_PAGE_HTML)
        calls["detail"] += 1
        return MagicMock(status_code=200, text=DETAIL_PAGE_HTML)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M._fetch_state(STATE, URL))
    assert calls["list"] == 3          # 2 failures + the succeeding 3rd attempt
    assert len(rows) == 1
    assert calls["detail"] == 1, "must have proceeded past the list-page fetch into detail enrichment"


def test_list_page_timeout_that_never_clears_ends_cleanly_not_hangs(monkeypatch):
    calls = {"list": 0}

    async def get(url, headers=None, follow_redirects=None):
        calls["list"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M._fetch_state(STATE, URL))
    assert calls["list"] == 3          # stop_after_attempt(3), then gives up -- not a hang
    assert rows == []


def test_list_page_non_200_status_is_not_retried(monkeypatch):
    calls = {"list": 0}

    async def get(url, headers=None, follow_redirects=None):
        calls["list"] += 1
        return MagicMock(status_code=503, text="")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M._fetch_state(STATE, URL))
    assert calls["list"] == 1          # a real bad status is not a transport/timeout error
    assert rows == []


# --- call site 2: the per-listing detail-page fetch (line 384-ish) --------------------

def test_detail_page_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"list": 0, "detail": 0}

    async def get(url, headers=None, follow_redirects=None):
        if url == URL:
            calls["list"] += 1
            return MagicMock(status_code=200, text=LIST_PAGE_HTML)
        calls["detail"] += 1
        if calls["detail"] < 3:
            raise httpx.ReadTimeout("boom")
        return MagicMock(status_code=200, text=DETAIL_PAGE_HTML)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M._fetch_state(STATE, URL))
    assert calls["detail"] == 3
    assert len(rows) == 1
    assert rows[0].county == "Caldwell", "enrichment must land once the retry succeeds"


def test_detail_page_timeout_that_never_clears_ends_cleanly_not_hangs(monkeypatch):
    calls = {"list": 0, "detail": 0}

    async def get(url, headers=None, follow_redirects=None):
        if url == URL:
            calls["list"] += 1
            return MagicMock(status_code=200, text=LIST_PAGE_HTML)
        calls["detail"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M._fetch_state(STATE, URL))
    assert calls["detail"] == 3        # stop_after_attempt(3), then gives up -- not a hang
    assert len(rows) == 1              # the list-page row itself still survives
    assert rows[0].county is None      # enrichment never landed, but it didn't crash the state


def test_detail_page_non_200_status_is_not_retried(monkeypatch):
    calls = {"list": 0, "detail": 0}

    async def get(url, headers=None, follow_redirects=None):
        if url == URL:
            calls["list"] += 1
            return MagicMock(status_code=200, text=LIST_PAGE_HTML)
        calls["detail"] += 1
        return MagicMock(status_code=500, text="")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M._fetch_state(STATE, URL))
    assert calls["detail"] == 1        # a real bad status is not a transport/timeout error
    assert len(rows) == 1
