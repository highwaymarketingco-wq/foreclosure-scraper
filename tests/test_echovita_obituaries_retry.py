"""echovita_obituaries.EchovitaObituaries.fetch: a transient transport error on either of its
two PoliteFetcher.get() calls gets retried, not treated as "the whole page/card failed."

Found 2026-11-07 (gap-sweep): both network call sites in fetch() -- the listing-page walk
(line ~166) and the per-card obituary-detail fetch (line ~194) -- route through the shared
PoliteFetcher.get() (_obit_common.py), which does not retry internally (a plain httpx.AsyncClient,
one bare `await self._client.get(...)`, no try/except/retry of its own). Same "caller must wrap
its own retries" gap already fixed tonight for the Column legal-notice API scrapers,
spartan_weekly_legals.py, and arcgis_webmap.query_features().

Listing-page site (higher severity): any exception -- including a transient
httpx.TransportError/TimeoutException -- landed in the bare `except Exception as exc:`, which
`break`s the page loop for that state with zero retries, abandoning every remaining page of that
state's listing for the run. Because obituary_listing() marks every row dateless and this source
is in main.DATELESS_OK_SOURCES, a zeroed run here has no fallback date window and can't self-heal.

Detail-page site (lower severity, genuine per-item loop): `except Exception: continue` only drops
that one card's survivor-list detail; the card's own name/city/age/date row still ships. Same
missing-retry defect, still worth the same fix.

Both sites already correctly leave the Walled exception (a real CAPTCHA/login/403/429) in its own
unretried branch -- never retry a real wall, and never retry a real bad HTTP status either.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.public_notices import echovita_obituaries as ev

NC_LISTING_URL = f"{ev.BASE}/us/obituaries/nc"
SC_LISTING_URL = f"{ev.BASE}/us/obituaries/sc"
DETAIL_URL = f"{ev.BASE}/us/obituaries/nc/nowhere/retry-person0-0"


def _listing_html(state: str, n: int = 1) -> str:
    """n real-shaped cards for `state` (markup the module's own _CARD regex matches),
    same structure as the sibling test_echovita_page_cap.py's _page() helper, made-up names."""
    cards = []
    for i in range(n):
        slug = f"retry-person{i}-{i}"
        cards.append(
            f'<div class="obit-list-wrapper"><a class="text-name-obit-in-list text-color-default" '
            f'href="/us/obituaries/{state}/nowhere/{slug}" title="Read the obituary of Retry Person{i}">'
            f'Retry Person{i}</a><p class="text-info-obit-in-list"><a class="text-primary" '
            f'title="Obituaries - Nowhere, {"North" if state == "nc" else "South"} Carolina" '
            f'href="/us/obituaries/{state}/nowhere">Nowhere</a></p><p class="text-info-obit-in-list">'
            f'<span class="my-auto">2026</span></p></div>')
    return "".join(cards)


_DETAIL_HTML = (
    '<script type="application/ld+json">{"@type": "Person", "name": "Retry Person0", '
    '"deathDate": "2026-10-01"}</script>'
    '<div id="obituary"><h1>Obituary</h1><p>Retry Person0 of Nowhere passed away peacefully. '
    'She is survived by her children and grandchildren.</p></div>'
)


def _fail_then_succeed(fail_times: int, result, exc=None):
    """Raise `exc` on the first `fail_times` calls, then return `result`."""
    exc = exc or httpx.ConnectTimeout("boom")

    def behavior(call_num: int):
        if call_num <= fail_times:
            raise exc
        return result
    return behavior


def _always_fail(exc=None):
    exc = exc or httpx.ConnectTimeout("boom")

    def behavior(call_num: int):
        raise exc
    return behavior


def _http_status_error(url: str, status: int = 503):
    def behavior(call_num: int):
        req = httpx.Request("GET", url)
        resp = httpx.Response(status, request=req)
        raise httpx.HTTPStatusError(f"HTTP {status}", request=req, response=resp)
    return behavior


class FakeFetcher:
    """Stands in for PoliteFetcher: a scriptable get() so we can drive EchovitaObituaries.fetch()
    through specific failure sequences on specific URLs, same spirit as test_echovita_page_cap.py's
    Fake class. A listing call passes no content_rx; a detail call always does -- that is how real
    fetch() tells them apart, so it is how this fake does too."""

    def __init__(self, listing_behavior=None, detail_behavior=None):
        self.calls: list[str] = []
        self._listing_behavior = listing_behavior or {}
        self._detail_behavior = detail_behavior or {}
        self.listing_call_counts: dict[str, int] = {}
        self.detail_call_counts: dict[str, int] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def get(self, url, params=None, content_rx=None):
        self.calls.append(url)
        if content_rx is None:
            counts, behaviors, default = self.listing_call_counts, self._listing_behavior, "<html></html>"
        else:
            counts, behaviors, default = self.detail_call_counts, self._detail_behavior, "<html></html>"
        n = counts.get(url, 0) + 1
        counts[url] = n
        behavior = behaviors.get(url)
        if behavior is not None:
            return behavior(n)
        return default


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Same trick as the arcgis_webmap reference test: patch the name fetch() calls at call time
    so the real exponential-jitter wait doesn't slow the test suite down."""
    monkeypatch.setattr(ev, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _run(monkeypatch, tmp_path, fake: FakeFetcher):
    monkeypatch.setenv("HEIRS_PRIVATE_DIR", str(tmp_path))      # empty private store, hermetic
    monkeypatch.setattr(ev, "PoliteFetcher", lambda: fake)
    scraper = ev.EchovitaObituaries()
    rows = asyncio.run(scraper.fetch())
    return rows, scraper


# --------------------------------------------------------------------------- #
# listing-page site (line ~166) -- the higher-severity call
# --------------------------------------------------------------------------- #

def test_listing_page_transient_error_is_retried_and_then_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "MAX_PAGES", 1)
    monkeypatch.setattr(ev, "MAX_DETAIL", 0)
    fake = FakeFetcher(listing_behavior={
        NC_LISTING_URL: _fail_then_succeed(2, _listing_html("nc", 1)),
    })
    rows, scraper = _run(monkeypatch, tmp_path, fake)

    assert fake.listing_call_counts[NC_LISTING_URL] == 3   # 2 failures + the successful 3rd attempt
    assert "errors" not in scraper.last_stats              # the retry absorbed it -- never surfaced
    assert "walled" not in scraper.last_stats
    assert len(rows) == 1                                  # the NC card made it through


def test_listing_page_transient_error_that_never_clears_still_raises_not_hangs(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "MAX_PAGES", 1)
    monkeypatch.setattr(ev, "MAX_DETAIL", 0)
    fake = FakeFetcher(listing_behavior={NC_LISTING_URL: _always_fail()})
    rows, scraper = _run(monkeypatch, tmp_path, fake)

    assert fake.listing_call_counts[NC_LISTING_URL] == 3   # stop_after_attempt(3), then gives up
    assert "errors" in scraper.last_stats                  # caught by the generic except, recorded
    assert rows == []


def test_listing_page_real_http_error_status_is_not_retried(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "MAX_PAGES", 1)
    monkeypatch.setattr(ev, "MAX_DETAIL", 0)
    fake = FakeFetcher(listing_behavior={
        NC_LISTING_URL: _http_status_error(NC_LISTING_URL),
    })
    rows, scraper = _run(monkeypatch, tmp_path, fake)

    assert fake.listing_call_counts[NC_LISTING_URL] == 1   # a real bad status is not a transport/timeout error
    assert "errors" in scraper.last_stats
    assert rows == []


def test_listing_page_walled_is_not_retried(monkeypatch, tmp_path):
    """A real wall (CAPTCHA/login/403/429) must never be retried either -- only transport/timeout
    errors are, and Walled is not one of them."""
    from foreclosure_scraper.quiet_title.fetch import Walled

    def behavior(call_num: int):
        raise Walled(NC_LISTING_URL, "captcha")

    monkeypatch.setattr(ev, "MAX_PAGES", 1)
    monkeypatch.setattr(ev, "MAX_DETAIL", 0)
    fake = FakeFetcher(listing_behavior={NC_LISTING_URL: behavior})
    rows, scraper = _run(monkeypatch, tmp_path, fake)

    assert fake.listing_call_counts[NC_LISTING_URL] == 1
    assert scraper.last_stats.get("walled") == "captcha"
    assert "errors" not in scraper.last_stats
    assert rows == []


# --------------------------------------------------------------------------- #
# detail-page site (line ~194) -- the lower-severity, genuinely per-item call
# --------------------------------------------------------------------------- #

def test_detail_page_transient_error_is_retried_and_then_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "MAX_PAGES", 1)
    monkeypatch.setattr(ev, "MAX_DETAIL", 5)
    fake = FakeFetcher(
        listing_behavior={NC_LISTING_URL: lambda n: _listing_html("nc", 1)},
        detail_behavior={DETAIL_URL: _fail_then_succeed(2, _DETAIL_HTML)},
    )
    rows, scraper = _run(monkeypatch, tmp_path, fake)

    assert fake.detail_call_counts[DETAIL_URL] == 3
    assert scraper.last_stats["detail"] == 1
    assert "errors" not in scraper.last_stats
    assert len(rows) == 1


def test_detail_page_transient_error_that_never_clears_is_skipped_not_hangs(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "MAX_PAGES", 1)
    monkeypatch.setattr(ev, "MAX_DETAIL", 5)
    fake = FakeFetcher(
        listing_behavior={NC_LISTING_URL: lambda n: _listing_html("nc", 1)},
        detail_behavior={DETAIL_URL: _always_fail()},
    )
    rows, scraper = _run(monkeypatch, tmp_path, fake)

    assert fake.detail_call_counts[DETAIL_URL] == 3        # stop_after_attempt(3), not an infinite hang
    assert scraper.last_stats["detail"] == 0                # per-item `continue`: this card's detail skipped
    assert len(rows) == 1                                   # but the card itself still ships (no detail)


def test_detail_page_real_http_error_is_not_retried(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "MAX_PAGES", 1)
    monkeypatch.setattr(ev, "MAX_DETAIL", 5)
    fake = FakeFetcher(
        listing_behavior={NC_LISTING_URL: lambda n: _listing_html("nc", 1)},
        detail_behavior={DETAIL_URL: _http_status_error(DETAIL_URL)},
    )
    rows, scraper = _run(monkeypatch, tmp_path, fake)

    assert fake.detail_call_counts[DETAIL_URL] == 1        # not retried
    assert scraper.last_stats["detail"] == 0
    assert len(rows) == 1
