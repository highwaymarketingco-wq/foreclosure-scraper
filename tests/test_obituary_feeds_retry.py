"""obituary_feeds.ObituaryFeeds.fetch: a transient transport error fetching a feed's RSS, or
fetching one obituary's own article page, gets retried -- not treated as "the whole feed" or
"the whole item" failed.

Found 2026-11-07 (gap-sweep, same pass as the other AsyncRetrying fixes tonight): this file has
two network call sites (both `await pf.get(...)`, both going through the shared
PoliteFetcher.get() helper imported from _obit_common.py), and PoliteFetcher.get()/.post() make
exactly one bare httpx call each with zero retry wrapper, decorator, or backoff loop -- same
root-cause gap already fixed tonight for a Column legal-notice API scraper,
spartan_weekly_legals.py, and the shared arcgis_webmap.query_features(). base_scraper.py (the
BaseScraper parent) has no retry logic either, so there is no framework-level safety net.

Scope note: the fix lives in THIS file (obituary_feeds.py), wrapping each call site inside
ObituaryFeeds.fetch() itself, not inside _obit_common.py -- PoliteFetcher is shared with
echovita_obituaries.py and is out of scope for this change. Blast radius here is already
contained by this file's own per-feed and per-item try/except/continue structure (one feed's
blip only zeroes that feed for the run; one item's detail-fetch blip only degrades it to its
feed excerpt), but a currently-unprotected network call is still worth the identical retry
cushioning used everywhere else in the repo tonight.

No network: PoliteFetcher is replaced with an in-process fake, same pattern as FakeFetcher in
test_obituary_readers.py."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.public_notices import obituary_feeds as of

FEED_URL = "https://flaky.example.test/category/obituaries/feed/"
DETAIL_URL = "https://flaky.example.test/2026/10/05/jane-sample/"

FEED_RSS_ONE_ITEM = f"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"
 xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>Obituaries</title>
<item><title>Jane Q Sample, 80</title><link>{DETAIL_URL}</link>
<pubDate>Mon, 05 Oct 2026 10:00:00 +0000</pubDate>
<content:encoded><![CDATA[<p>Jane Q Sample, 80, died peacefully at home.</p>]]></content:encoded></item>
</channel></rss>"""

# No "surviv.../left to cherish/..." in the excerpt above, so the trigger-word pre-check lets
# the detail-page fetch fire; this page supplies the richer text (and the survivor) instead.
DETAIL_PAGE = """<html><body><article><div class="entry-content">
<p>Jane Q Sample, 80, of Flaky Falls, died peacefully at home on October 3, 2026, after a long
illness bravely endured with grace and good humor among family and friends.</p>
<p>She is survived by her son, Tom Sample, of Flaky Falls, and a host of nieces, nephews, and
friends who will all miss her dearly for the rest of their lives.</p>
<div class="sharedaddy">Share this obituary</div></article></body></html>"""


class _FlakyFetcher:
    """Mirrors PoliteFetcher's async surface (async context manager + .get(url, params=None,
    content_rx=None)) with no network. Serves `pages` for any URL, except `flaky_url`, which
    raises `exc` on its first `fail_times` calls to it before serving its real page (or
    forever, if `fail_times` is high enough that the retry budget runs out first)."""

    def __init__(self, pages: dict, *, flaky_url: str | None = None, fail_times: int = 0, exc=None):
        self.pages = pages
        self.flaky_url = flaky_url
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectError("boom")
        self.flaky_calls = 0
        self.walled: dict = {}

    async def __aenter__(self) -> "_FlakyFetcher":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def get(self, url, params=None, content_rx=None):
        if url == self.flaky_url:
            self.flaky_calls += 1
            if self.flaky_calls <= self.fail_times:
                raise self.exc
        if url in self.pages:
            return self.pages[url]
        raise RuntimeError(f"no fixture for {url}")


def _http_status_error(status: int = 503) -> httpx.HTTPStatusError:
    """A real httpx.HTTPStatusError -- the exact exception PoliteFetcher.get() raises on a
    genuine bad status (_obit_common.py: `if r.status_code >= 400: raise httpx.HTTPStatusError
    (...)`). Not a transport/timeout error, so it must never be retried."""
    req = httpx.Request("GET", FEED_URL)
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError(f"HTTP {status}", request=req, response=resp)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(of, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _one_feed(*, detail: bool) -> of.Feed:
    """kind="wp" (not "townnews"): fetch() blanks the row's text for "townnews" feeds
    unconditionally (`text=body if feed.kind != "townnews" else ""`), which would hide
    whether the retried detail-page fetch's richer body actually made it into the row. Both
    fixture bodies below contain "died", so looks_like_obituary(body) passes either way."""
    return of.Feed("flaky.example.test", FEED_URL, "Polk", "NC", "wp", "Flaky Paper", detail)


def _run(monkeypatch, tmp_path, feed: of.Feed, fetcher: _FlakyFetcher):
    monkeypatch.setenv("HEIRS_PRIVATE_DIR", str(tmp_path))
    monkeypatch.setattr(of, "FEEDS", (feed,))
    monkeypatch.setattr(of, "PoliteFetcher", lambda: fetcher)
    s = of.ObituaryFeeds()
    rows = asyncio.run(s.fetch())
    return s, rows


# --------------------------------------------------------------------------------------------- #
# call site 1: `text = await pf.get(feed.url)` -- fetching a feed's own RSS
# --------------------------------------------------------------------------------------------- #

def test_feed_fetch_transient_error_is_retried_and_then_succeeds(monkeypatch, tmp_path):
    feed = _one_feed(detail=False)
    fetcher = _FlakyFetcher({FEED_URL: FEED_RSS_ONE_ITEM}, flaky_url=FEED_URL, fail_times=2)
    s, rows = _run(monkeypatch, tmp_path, feed, fetcher)
    assert fetcher.flaky_calls == 3  # 2 failures + the successful 3rd attempt
    assert "error" not in s.last_stats[feed.host]
    assert [r.owner_name for r in rows] == ["Jane Q Sample"]


def test_feed_fetch_transient_error_that_never_clears_still_raises_not_hangs(monkeypatch, tmp_path):
    feed = _one_feed(detail=False)
    fetcher = _FlakyFetcher({FEED_URL: FEED_RSS_ONE_ITEM}, flaky_url=FEED_URL, fail_times=99)
    s, rows = _run(monkeypatch, tmp_path, feed, fetcher)
    assert fetcher.flaky_calls == 3  # stop_after_attempt(3), then gives up -- not an infinite loop
    assert rows == []  # the per-feed try/except caught it and moved on (no more feeds to try)
    assert "boom" in s.last_stats[feed.host]["error"]


def test_feed_fetch_read_timeout_is_also_retried(monkeypatch, tmp_path):
    feed = _one_feed(detail=False)
    fetcher = _FlakyFetcher({FEED_URL: FEED_RSS_ONE_ITEM}, flaky_url=FEED_URL, fail_times=1,
                             exc=httpx.ReadTimeout("slow"))
    s, rows = _run(monkeypatch, tmp_path, feed, fetcher)
    assert fetcher.flaky_calls == 2
    assert [r.owner_name for r in rows] == ["Jane Q Sample"]


def test_feed_fetch_real_http_error_status_is_not_retried(monkeypatch, tmp_path):
    feed = _one_feed(detail=False)
    fetcher = _FlakyFetcher({FEED_URL: FEED_RSS_ONE_ITEM}, flaky_url=FEED_URL, fail_times=99,
                             exc=_http_status_error(503))
    s, rows = _run(monkeypatch, tmp_path, feed, fetcher)
    assert fetcher.flaky_calls == 1  # a real bad status is not a transport/timeout error
    assert rows == []
    assert "503" in s.last_stats[feed.host]["error"]


# --------------------------------------------------------------------------------------------- #
# call site 2: `page = await pf.get(link, content_rx=_CONTENT_START)` -- fetching one
# obituary's own article page, when the feed excerpt lacked the survivor trigger words
# --------------------------------------------------------------------------------------------- #

def test_detail_page_fetch_transient_error_is_retried_and_then_succeeds(monkeypatch, tmp_path):
    feed = _one_feed(detail=True)
    fetcher = _FlakyFetcher({FEED_URL: FEED_RSS_ONE_ITEM, DETAIL_URL: DETAIL_PAGE},
                             flaky_url=DETAIL_URL, fail_times=2)
    s, rows = _run(monkeypatch, tmp_path, feed, fetcher)
    assert fetcher.flaky_calls == 3
    assert s.last_stats[feed.host]["detail"] == 1
    assert [r.owner_name for r in rows] == ["Jane Q Sample"]
    jane = rows[0]
    assert [p["name"] for p in jane.raw["obituary_private"]["survivors"]] == ["Tom Sample"]


def test_detail_page_fetch_transient_error_that_never_clears_still_raises_not_hangs(monkeypatch, tmp_path):
    feed = _one_feed(detail=True)
    fetcher = _FlakyFetcher({FEED_URL: FEED_RSS_ONE_ITEM, DETAIL_URL: DETAIL_PAGE},
                             flaky_url=DETAIL_URL, fail_times=99)
    s, rows = _run(monkeypatch, tmp_path, feed, fetcher)
    assert fetcher.flaky_calls == 3  # stop_after_attempt(3), then gives up -- not an infinite loop
    # the detail fetch's own `except Exception: pass` swallows the failure; the row still
    # ships with the feed excerpt it already had, per obituary_feeds.py's own design.
    assert s.last_stats[feed.host]["detail"] == 0
    assert [r.owner_name for r in rows] == ["Jane Q Sample"]


def test_detail_page_fetch_real_http_error_status_is_not_retried(monkeypatch, tmp_path):
    feed = _one_feed(detail=True)
    fetcher = _FlakyFetcher({FEED_URL: FEED_RSS_ONE_ITEM, DETAIL_URL: DETAIL_PAGE},
                             flaky_url=DETAIL_URL, fail_times=99, exc=_http_status_error(403))
    s, rows = _run(monkeypatch, tmp_path, feed, fetcher)
    assert fetcher.flaky_calls == 1  # a real bad status is not a transport/timeout error
    assert s.last_stats[feed.host]["detail"] == 0
    assert [r.owner_name for r in rows] == ["Jane Q Sample"]
